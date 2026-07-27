"""
Background scheduler for auto-pay bills and bill-due notifications.

Runs daily at 00:05 UTC, plus a catch-up run on startup for anything missed
while the server was down.

Idempotency
-----------
Every effect this job produces is idempotent, because the job can legitimately
run more than once for the same day:

  * ``uvicorn --workers N`` starts N processes, each with its own scheduler
  * the server may be restarted several times a day (catch-up run each time)
  * a run may crash halfway and be retried

Auto-pay claims each occurrence with a conditional UPDATE and checks the
affected row count, so exactly one runner can ever pay a given occurrence.
Notifications carry a stable ``dedupe_key`` protected by a unique constraint.
Setting ``ENABLE_SCHEDULER=false`` on all but one worker avoids the redundant
work, but correctness does not depend on it.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")

# How many days past the due date an overdue reminder is sent. Previously a
# reminder went out on *every* run for *every* overdue bill, which meant an
# unpaid bill nagged all members daily, forever.
OVERDUE_REMINDER_DAYS = (1, 3, 7, 14, 30)

# Contract-expiry warnings, in days before contract_end_date.
CONTRACT_WARNING_DAYS = (30, 10)

# Bill drift: how far a charge must move from its own recent average before it
# is worth mentioning. Both gates must be passed, so a 30% jump on a EUR 3 bill
# stays quiet.
DRIFT_PCT_THRESHOLD = 25.0     # percent
DRIFT_MIN_ABSOLUTE = 5.0       # household currency
DRIFT_MIN_HISTORY = 3          # prior charges needed to form a baseline
DRIFT_LOOKBACK_DAYS = 35       # only comment on a recently-landed charge

# Budget warnings, as percentages of a bucket's monthly budget.
BUDGET_THRESHOLDS = (80, 100)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _members_by_household(db, household_ids: set[str]) -> dict[str, list[str]]:
    """Batch-load member user ids, keyed by household id.

    Returns plain strings rather than ORM objects so the mapping stays usable
    across the commits that happen inside the auto-pay loop.
    """
    from app.models import HouseholdMember

    if not household_ids:
        return {}
    members: dict[str, list[str]] = {}
    rows = (
        db.query(HouseholdMember.household_id, HouseholdMember.user_id)
        .filter(HouseholdMember.household_id.in_(household_ids))
        .all()
    )
    for hh_id, user_id in rows:
        members.setdefault(hh_id, []).append(user_id)
    return members


def _money(amount, currency: str | None) -> str:
    """Format an amount for a notification body, tolerating a missing amount."""
    from app.templates import format_currency

    if amount is None:
        return "Amount not set"
    return format_currency(float(amount), currency or "EUR")


def _notify_members(db, user_ids, *, household_id, type, title, body, link, dedupe_key):
    """Create + push one notification per member, skipping already-sent ones."""
    from app.notification_service import create_notification, send_push_for_notification

    for user_id in user_ids:
        notif = create_notification(
            db,
            household_id=household_id,
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            link=link,
            dedupe_key=dedupe_key,
        )
        if notif is not None:
            send_push_for_notification(db, notif)


# ---------------------------------------------------------------------------
# Auto-pay
# ---------------------------------------------------------------------------

def _auto_pay_due_bills(db, today: date) -> int:
    """Mark fixed-amount auto-pay occurrences as paid once they are due.

    Variable-amount bills with no pre-set occurrence amount are skipped — the
    user must enter the amount. Returns the number of occurrences paid.
    """
    from app.models import (
        BillOccurrence, NotificationType, OccurrenceStatus, RecurringBill,
        Transaction, TransactionSplit, TransactionType,
    )
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload

    occs = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill).joinedload(RecurringBill.splits))
        .filter(
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date <= today,
            BillOccurrence.transaction_id.is_(None),
            RecurringBill.is_auto_pay.is_(True),
            RecurringBill.is_active.is_(True),
            # Fixed-amount bill OR occurrence has a pre-set amount (standing order)
            or_(RecurringBill.amount.isnot(None), BillOccurrence.amount.isnot(None)),
        )
        .all()
    )
    if not occs:
        return 0

    members_by_hh = _members_by_household(db, {o.bill.household_id for o in occs})

    # Snapshot everything needed up front: the loop commits on every iteration,
    # which expires ORM instances and would otherwise re-query on each attribute.
    pending = []
    for occ in occs:
        bill = occ.bill
        pay_amount = occ.amount if occ.amount is not None else bill.amount
        if pay_amount is None:
            continue
        pending.append({
            "occ_id":     occ.id,
            "due_date":   occ.due_date,
            "amount":     pay_amount,
            "household_id":    bill.household_id,
            "bucket_id":       bill.bucket_id,
            "category_id":     bill.category_id,
            "paid_by_default": bill.paid_by_default,
            "currency":        bill.currency,
            "name":            bill.name,
            "splits": [(s.user_id, s.amount) for s in bill.splits],
        })

    count = 0
    for item in pending:
        # Atomically claim the occurrence. If another worker (or an earlier run
        # of this job) already claimed it, the UPDATE matches zero rows and we
        # skip it — this is what prevents duplicate auto-pay transactions.
        claimed = (
            db.query(BillOccurrence)
            .filter(
                BillOccurrence.id == item["occ_id"],
                BillOccurrence.status == OccurrenceStatus.unpaid,
                BillOccurrence.transaction_id.is_(None),
            )
            .update(
                {
                    BillOccurrence.status:  OccurrenceStatus.paid,
                    BillOccurrence.paid_at: _utcnow(),
                    BillOccurrence.paid_by: item["paid_by_default"],
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            logger.info("Occurrence %s already claimed elsewhere — skipping", item["occ_id"])
            db.rollback()
            continue

        if item["bucket_id"]:
            txn = Transaction(
                bucket_id=item["bucket_id"],
                household_id=item["household_id"],
                amount=item["amount"],
                currency=item["currency"],
                type=TransactionType.expense,
                paid_by=item["paid_by_default"],
                category_id=item["category_id"],
                notes=f"Auto-pay: {item['name']}",
                transaction_date=item["due_date"],
            )
            db.add(txn)
            db.flush()
            db.query(BillOccurrence).filter(BillOccurrence.id == item["occ_id"]).update(
                {BillOccurrence.transaction_id: txn.id}, synchronize_session=False
            )
            for user_id, amount in item["splits"]:
                db.add(TransactionSplit(
                    transaction_id=txn.id,
                    user_id=user_id,
                    amount=amount,
                ))

        _notify_members(
            db,
            members_by_hh.get(item["household_id"], []),
            household_id=item["household_id"],
            type=NotificationType.bill_auto_paid,
            title=f"Auto-paid: {item['name']}",
            body=f"{_money(item['amount'], item['currency'])} marked as paid",
            link="/bills",
            dedupe_key=f"bill_auto_paid:{item['occ_id']}",
        )

        # Commit per occurrence so the claim is durable immediately and a later
        # failure cannot roll back payments already made.
        db.commit()
        count += 1

    if count:
        logger.info("Auto-paid %d bill occurrence(s)", count)
    return count


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _notify_due_soon(db, today: date) -> None:
    """Remind members about bills due in 3 days."""
    from app.models import BillOccurrence, NotificationType, OccurrenceStatus, RecurringBill
    from sqlalchemy.orm import joinedload

    due_date = today + timedelta(days=3)
    occs = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date == due_date,
            RecurringBill.is_active.is_(True),
        )
        .all()
    )
    members_by_hh = _members_by_household(db, {o.bill.household_id for o in occs})

    for occ in occs:
        bill = occ.bill
        amount = occ.amount if occ.amount is not None else bill.amount
        _notify_members(
            db,
            members_by_hh.get(bill.household_id, []),
            household_id=bill.household_id,
            type=NotificationType.bill_due,
            title=f"Bill due in 3 days: {bill.name}",
            body=f"{_money(amount, bill.currency)} due on {occ.due_date}",
            link="/bills",
            dedupe_key=f"bill_due:{occ.id}",
        )
    db.commit()


def _notify_overdue(db, today: date) -> None:
    """Remind members about overdue bills at fixed milestones, not every day."""
    from app.models import BillOccurrence, NotificationType, OccurrenceStatus, RecurringBill
    from sqlalchemy.orm import joinedload

    milestone_dates = {today - timedelta(days=d): d for d in OVERDUE_REMINDER_DAYS}
    occs = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date.in_(list(milestone_dates)),
            RecurringBill.is_active.is_(True),
            RecurringBill.is_auto_pay.is_(False),
        )
        .all()
    )
    members_by_hh = _members_by_household(db, {o.bill.household_id for o in occs})

    for occ in occs:
        bill = occ.bill
        days_late = milestone_dates[occ.due_date]
        _notify_members(
            db,
            members_by_hh.get(bill.household_id, []),
            household_id=bill.household_id,
            type=NotificationType.bill_overdue,
            title=f"Overdue bill: {bill.name}",
            body=f"Was due on {occ.due_date} — {days_late} day(s) ago.",
            link="/bills",
            dedupe_key=f"bill_overdue:{occ.id}:{days_late}",
        )
    db.commit()


def _notify_contracts_expiring(db, today: date) -> None:
    """Warn members ahead of telco/power contract expiry."""
    from app.models import NotificationType, RecurringBill

    expiry_dates = {today + timedelta(days=d): d for d in CONTRACT_WARNING_DAYS}
    bills = (
        db.query(RecurringBill)
        .filter(
            RecurringBill.contract_end_date.in_(list(expiry_dates)),
            RecurringBill.is_active.is_(True),
        )
        .all()
    )
    members_by_hh = _members_by_household(db, {b.household_id for b in bills})

    for bill in bills:
        days_out = expiry_dates[bill.contract_end_date]
        _notify_members(
            db,
            members_by_hh.get(bill.household_id, []),
            household_id=bill.household_id,
            type=NotificationType.contract_expiring,
            title=f"Contract expiring: {bill.name}",
            body=f"Expires on {bill.contract_end_date} — {days_out} days to act.",
            link="/bills",
            dedupe_key=f"contract_expiring:{bill.id}:{bill.contract_end_date}:{days_out}",
        )
    db.commit()


def _notify_bill_drift(db, today: date) -> None:
    """Flag a bill whose latest charge departs from its own recent history.

    Only variable bills can drift: a fixed bill has no per-occurrence amount, so
    every occurrence costs bill.amount by definition. The baseline is the mean
    of the preceding occurrences, which is why at least MIN_HISTORY of them are
    required before anything is reported.
    """
    from app.models import (
        BillOccurrence, NotificationType, OccurrenceStatus, RecurringBill,
    )

    lookback_start = today - timedelta(days=DRIFT_LOOKBACK_DAYS)

    bills = (
        db.query(RecurringBill)
        .filter(RecurringBill.is_active.is_(True))
        .all()
    )
    members_by_hh = _members_by_household(db, {b.household_id for b in bills})

    for bill in bills:
        occs = (
            db.query(BillOccurrence)
            .filter(
                BillOccurrence.bill_id == bill.id,
                BillOccurrence.status == OccurrenceStatus.paid,
                BillOccurrence.amount.isnot(None),
            )
            .order_by(BillOccurrence.due_date)
            .all()
        )
        if len(occs) < DRIFT_MIN_HISTORY + 1:
            continue

        latest = occs[-1]
        # Only comment on a charge that actually landed recently, otherwise a
        # dormant bill would be re-analysed on every run forever.
        if latest.due_date < lookback_start:
            continue

        history = [float(o.amount) for o in occs[-(DRIFT_MIN_HISTORY + 1):-1]]
        baseline = sum(history) / len(history)
        if baseline <= 0:
            continue

        current = float(latest.amount)
        delta = current - baseline
        pct = delta / baseline * 100

        if abs(pct) < DRIFT_PCT_THRESHOLD or abs(delta) < DRIFT_MIN_ABSOLUTE:
            continue

        direction = "up" if delta > 0 else "down"
        _notify_members(
            db,
            members_by_hh.get(bill.household_id, []),
            household_id=bill.household_id,
            type=NotificationType.bill_drift,
            title=f"{bill.name} is {abs(pct):.0f}% {direction}",
            body=(
                f"{_money(current, bill.currency)} vs "
                f"{_money(round(baseline, 2), bill.currency)} average "
                f"over the last {len(history)} charges."
            ),
            link="/bills",
            dedupe_key=f"bill_drift:{latest.id}",
        )
    db.commit()


def _notify_budget_thresholds(db, today: date) -> None:
    """Warn when a bucket's spend for the current month crosses its budget."""
    from app.models import Bucket, BucketStatus, NotificationType
    from app.services import get_bucket_spend_this_month

    buckets = (
        db.query(Bucket)
        .filter(
            Bucket.budget.isnot(None),
            Bucket.status == BucketStatus.active,
        )
        .all()
    )
    if not buckets:
        return

    members_by_hh = _members_by_household(db, {b.household_id for b in buckets})
    period = f"{today.year}-{today.month:02d}"

    # One spend query per household rather than per bucket.
    spend_by_hh = {
        hh_id: get_bucket_spend_this_month(db, hh_id, today.year, today.month)
        for hh_id in {b.household_id for b in buckets}
    }

    for bucket in buckets:
        budget = float(bucket.budget)
        if budget <= 0:
            continue
        spent = spend_by_hh.get(bucket.household_id, {}).get(bucket.id, 0.0)
        pct = spent / budget * 100

        # Highest crossed threshold only — no point saying 80% and 100% together.
        crossed = max((t for t in BUDGET_THRESHOLDS if pct >= t), default=None)
        if crossed is None:
            continue

        currency = bucket.household.default_currency if bucket.household else "EUR"
        if crossed >= 100:
            title = f"{bucket.name} is over budget"
            body = (
                f"{_money(round(spent, 2), currency)} of "
                f"{_money(budget, currency)} — "
                f"{_money(round(spent - budget, 2), currency)} over."
            )
        else:
            title = f"{bucket.name} at {pct:.0f}% of budget"
            body = (
                f"{_money(round(spent, 2), currency)} of "
                f"{_money(budget, currency)} — "
                f"{_money(round(budget - spent, 2), currency)} left this month."
            )

        _notify_members(
            db,
            members_by_hh.get(bucket.household_id, []),
            household_id=bucket.household_id,
            type=NotificationType.budget_warning,
            title=title,
            body=body,
            link=f"/buckets/{bucket.id}",
            # Per bucket, per month, per threshold: crossing 80 then later 100
            # produces two notices, but neither repeats.
            dedupe_key=f"budget:{bucket.id}:{period}:{crossed}",
        )
    db.commit()


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------

def auto_mark_paid_job() -> None:
    """Daily bills job: auto-pay due bills, then send the reminder notifications.

    Each stage is isolated so a failure in one does not discard the others.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()
        for stage in (
            _auto_pay_due_bills,
            _notify_due_soon,
            _notify_overdue,
            _notify_contracts_expiring,
            _notify_bill_drift,
            _notify_budget_thresholds,
        ):
            try:
                stage(db, today)
            except Exception:
                logger.exception("Bills job stage %s failed", stage.__name__)
                db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    """Start the background scheduler and run an immediate catch-up job."""
    from app.config import settings

    if not settings.enable_scheduler:
        logger.info("Scheduler disabled via ENABLE_SCHEDULER — skipping start")
        return

    # Daily at 00:05 UTC
    scheduler.add_job(
        auto_mark_paid_job,
        CronTrigger(hour=0, minute=5),
        id="auto_mark_paid_daily",
        replace_existing=True,
        coalesce=True,        # collapse missed runs into one
        max_instances=1,      # never overlap with a still-running job
        misfire_grace_time=3600,
    )
    # Run shortly after startup to catch bills missed while the server was down.
    scheduler.add_job(
        auto_mark_paid_job,
        id="auto_mark_paid_startup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

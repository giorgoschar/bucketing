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
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core import clock

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()  # timezone applied in start_scheduler()

# How many days past the due date an overdue reminder is sent. Previously a
# reminder went out on *every* run for *every* overdue bill, which meant an
# unpaid bill nagged all members daily, forever.
OVERDUE_REMINDER_DAYS = (1, 3, 7, 14, 30)

# Contract-expiry warnings, in days before contract_end_date.
CONTRACT_WARNING_DAYS = (30, 10)

# Bill drift: how far a charge must move from its own recent average before it
# is worth mentioning. Both gates must be passed, so a 30% jump on a EUR 3 bill
# stays quiet.
DRIFT_PCT_THRESHOLD = 25.0  # percent
DRIFT_MIN_ABSOLUTE = 5.0  # household currency
DRIFT_MIN_HISTORY = 3  # prior charges needed to form a baseline
DRIFT_LOOKBACK_DAYS = 35  # only comment on a recently-landed charge

# Budget warnings, as percentages of a bucket's monthly budget.
BUDGET_THRESHOLDS = (80, 100)


def _tz():
    """The household calendar timezone (see app.core.clock.tz)."""
    return clock.tz()


def today_local() -> date:
    """Today on the household's calendar.

    Bill due dates are timezone-naive calendar dates entered in local time, so
    comparing them against the UTC date is wrong for any household not on UTC.
    """
    return clock.local_today()


def _utcnow() -> datetime:
    """UTC wall clock, naive, for stored timestamps (paid_at, created_at)."""
    return clock.utcnow_naive()


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
    return format_currency(amount, currency or "EUR")


def _notify_members(db, user_ids, *, household_id, type, title, body, link, dedupe_key):
    """Create + push one notification per member, skipping already-sent ones."""
    from app.services.notifications import create_notification, send_push_for_notification

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
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload

    from app.models import (
        BillOccurrence,
        NotificationType,
        OccurrenceStatus,
        RecurringBill,
    )
    from app.services import bills as bills_service

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
        # The bill's payer mode: own share (no payer, scaled splits) or a
        # single payer resolved from the default / owner.
        payer, payer_mode = bills_service.resolve_bill_payment(db, bill)
        pending.append(
            {
                "occ_id": occ.id,
                "due_date": occ.due_date,
                "amount": pay_amount,
                "household_id": bill.household_id,
                "bucket_id": bill.bucket_id,
                "category_id": bill.category_id,
                "paid_by_default": payer,
                "payer_mode": payer_mode,
                "currency": bill.currency,
                "name": bill.name,
            }
        )

    count = 0
    for item in pending:
        # pay_occurrence atomically claims the occurrence (and creates the
        # transaction with scaled splits). If another worker (or an earlier run
        # of this job) already claimed it nothing is written — this is what
        # prevents duplicate auto-pay transactions.
        occ = db.get(BillOccurrence, item["occ_id"])
        if not bills_service.settle_occurrence(
            db,
            occ,
            amount=item["amount"],
            paid_by=item["paid_by_default"],
            payer_mode=item["payer_mode"],
            paid_on=_utcnow(),
            note_prefix="Auto-pay",
        ):
            logger.info("Occurrence %s already claimed elsewhere — skipping", item["occ_id"])
            db.rollback()
            continue

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
    from sqlalchemy.orm import joinedload

    from app.models import BillOccurrence, NotificationType, OccurrenceStatus, RecurringBill

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
    from sqlalchemy.orm import joinedload

    from app.models import BillOccurrence, NotificationType, OccurrenceStatus, RecurringBill

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
        BillOccurrence,
        NotificationType,
        OccurrenceStatus,
        RecurringBill,
    )

    lookback_start = today - timedelta(days=DRIFT_LOOKBACK_DAYS)

    bills = db.query(RecurringBill).filter(RecurringBill.is_active.is_(True)).all()
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

        history = [float(o.amount) for o in occs[-(DRIFT_MIN_HISTORY + 1) : -1]]
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
                f"{_money(baseline, bill.currency)} average "
                f"over the last {len(history)} charges."
            ),
            link="/bills",
            dedupe_key=f"bill_drift:{latest.id}",
        )
    db.commit()


def _notify_budget_thresholds(db, today: date) -> None:
    """Warn when a bucket's spend for the current month crosses its budget."""
    from app.core.money import ZERO, to_decimal
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
        budget = to_decimal(bucket.budget)
        if budget <= 0:
            continue
        spent = spend_by_hh.get(bucket.household_id, {}).get(bucket.id, ZERO)
        pct = spent / budget * 100

        # Highest crossed threshold only — no point saying 80% and 100% together.
        crossed = max((t for t in BUDGET_THRESHOLDS if pct >= t), default=None)
        if crossed is None:
            continue

        currency = bucket.household.default_currency if bucket.household else "EUR"
        if crossed >= 100:
            title = f"{bucket.name} is over budget"
            body = (
                f"{_money(spent, currency)} of "
                f"{_money(budget, currency)} — "
                f"{_money(spent - budget, currency)} over."
            )
        else:
            title = f"{bucket.name} at {pct:.0f}% of budget"
            body = (
                f"{_money(spent, currency)} of "
                f"{_money(budget, currency)} — "
                f"{_money(budget - spent, currency)} left this month."
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
# Stock & prices (Phase 6)
# ---------------------------------------------------------------------------

# Consecutive PosoKanei failures after which the refresh stage gives up for
# the day: when the API is down every call would fail, so stop knocking.
PRICE_REFRESH_MAX_FAILURES = 3
PRICE_DROP_RATIO = 0.9  # current min ≤ 90% of the 30-day median


def _refresh_tracked_prices(db, today: date) -> int:
    """Store today's PosoKanei prices for every tracked, linked product.

    Idempotent: products that already have a snapshot for today are skipped.
    Requests are spaced by the client (≥ 250 ms, so ≤ 4 req/s). PosoKanei
    being unavailable is logged and ends the stage; the job carries on.
    """
    from sqlalchemy import func

    from app.integrations import posokanei
    from app.models import PriceSnapshot, Product, StockItem
    from app.services.stock import record_snapshots

    last_snap = (
        db.query(
            PriceSnapshot.product_id.label("pid"),
            func.max(PriceSnapshot.snapshot_date).label("last"),
        )
        .group_by(PriceSnapshot.product_id)
        .subquery()
    )
    rows = (
        db.query(Product.id, last_snap.c.last)
        .join(StockItem, StockItem.product_id == Product.id)
        .outerjoin(last_snap, last_snap.c.pid == Product.id)
        .filter(
            Product.posokanei_id.isnot(None),
            Product.archived_at.is_(None),
            StockItem.track_price.is_(True),
        )
        .all()
    )
    # Deterministic and fair: never-priced first, then the stalest, so a
    # stage cut short by an outage starts where it left off next time.
    product_ids = [
        pid
        for pid, last in sorted(rows, key=lambda r: (r[1] is not None, r[1] or today, r[0]))
        if last is None or last < today
    ]
    stored = failures = 0
    for pid in product_ids:
        product = db.get(Product, pid)
        try:
            summary = posokanei.get(product.posokanei_id)
        except posokanei.PosokaneiNotFound as exc:
            # One delisted/bogus id: skip it, it says nothing about an outage.
            logger.info("PosoKanei has no product %s (%s); skipping", product.posokanei_id, exc)
            continue
        except posokanei.PosokaneiUnavailable as exc:
            failures += 1
            logger.warning("PosoKanei unavailable for product %s: %s", pid, exc)
            if failures >= PRICE_REFRESH_MAX_FAILURES:
                logger.warning("PosoKanei unavailable — skipping today's remaining price refresh")
                break
            continue
        failures = 0
        stored += record_snapshots(db, product, summary, today)
        db.commit()
    if stored:
        logger.info("Stored %d price snapshot(s)", stored)
    return stored


def _notify_stock_and_prices(db, today: date) -> None:
    """stock_low when an item crossed down to its minimum since yesterday;
    price_drop when a tracked product's price today is ≤ 90% of its 30-day
    median. Both at most once per item per day."""
    from decimal import Decimal

    from app.core.money import to_decimal
    from app.models import NotificationType, Product, StockItem, StockMovement
    from app.services.stock import price_advice_bulk

    items = (
        db.query(StockItem)
        .join(Product, Product.id == StockItem.product_id)
        .filter(Product.archived_at.is_(None))
        .all()
    )
    if not items:
        return
    members_by_hh = _members_by_household(db, {i.household_id for i in items})

    # --- stock_low: "crossing" = it was above the minimum at some point
    # since the start of yesterday, and is at/below it now.
    since = datetime.combine(today - timedelta(days=1), datetime.min.time())
    low = [i for i in items if to_decimal(i.quantity) <= to_decimal(i.min_quantity)]
    recent: dict[str, list] = {}
    if low:
        for m in (
            db.query(StockMovement)
            .filter(
                StockMovement.stock_item_id.in_([i.id for i in low]),
                StockMovement.created_at >= since,
            )
            .order_by(StockMovement.created_at.desc())
        ):
            recent.setdefault(m.stock_item_id, []).append(m)
    for item in low:
        qty, crossed = to_decimal(item.quantity), False
        for m in recent.get(item.id, []):  # newest first: undo each
            qty -= to_decimal(m.delta)
            if qty > to_decimal(item.min_quantity):
                crossed = True
                break
        if not crossed:
            continue
        name = item.product.name
        _notify_members(
            db,
            members_by_hh.get(item.household_id, []),
            household_id=item.household_id,
            type=NotificationType.stock_low,
            title=f"Running low: {name}",
            body=f"{to_decimal(item.quantity):g} left (minimum {to_decimal(item.min_quantity):g}).",
            link="/stock/shopping",
            dedupe_key=f"stock_low:{item.id}:{today}",
        )

    # --- price_drop
    tracked = [i for i in items if i.track_price and i.product.posokanei_id]
    advice = price_advice_bulk(db, [i.product_id for i in tracked], today)
    ratio = Decimal(str(PRICE_DROP_RATIO))
    for item in tracked:
        a = advice[item.product_id]
        current, median = a["current_min"], a["median_30d"]
        # Only fresh data: a stale price (refresh failed today) is not news.
        if a["advice"] == "unknown" or a["as_of"] != today or current is None or not median:
            continue
        if current > median * ratio:
            continue
        product = item.product
        pct = (1 - current / median) * 100
        _notify_members(
            db,
            members_by_hh.get(item.household_id, []),
            household_id=item.household_id,
            type=NotificationType.price_drop,
            title=f"Price drop: {product.name} {pct:.0f}% below usual",
            body=f"{_money(current, 'EUR')} vs {_money(median, 'EUR')} 30-day median (PosoKanei).",
            link="/stock",
            dedupe_key=f"price_drop:{product.id}:{today}",
        )
    db.commit()


# ---------------------------------------------------------------------------
# Receipt trash
# ---------------------------------------------------------------------------

TRASH_RETENTION_DAYS = 30


def _purge_trash(db, today: date, uploads_dir: str | None = None) -> int:
    """Delete receipt FILES in <uploads>/.trash older than 30 days (by mtime).

    Files only: database rows (soft-deleted transactions) are never touched.
    """
    import os
    import time

    from app.services import TRASH_DIRNAME, UPLOADS_DIR

    trash = os.path.join(uploads_dir or UPLOADS_DIR, TRASH_DIRNAME)
    if not os.path.isdir(trash):
        return 0
    cutoff = time.time() - TRASH_RETENTION_DAYS * 86400
    removed = 0
    for entry in os.scandir(trash):
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
                removed += 1
        except OSError:
            logger.exception("Could not purge trash file %s", entry.path)
    return removed


# ---------------------------------------------------------------------------
# Planning (spec §3.3)
# ---------------------------------------------------------------------------


def _top_up_entries(db, today: date) -> int:
    """Extend every active item's entries to the rolling horizon.

    Never creates an entry dated before today. A bad rule on one item is
    logged and skipped; the others still get their entries.
    """
    from app.models import RecurringBill
    from app.services.bills import PAST_NONE, generate_occurrences

    bill_ids = [
        bill_id for (bill_id,) in db.query(RecurringBill.id).filter(RecurringBill.active_filter())
    ]
    created = 0
    for bill_id in bill_ids:
        bill = db.get(RecurringBill, bill_id)
        if bill is None:  # deleted since the id list was read
            continue
        try:
            created += generate_occurrences(db, bill, today=today, past=PAST_NONE)
            db.commit()
        except Exception:
            logger.exception("Could not top up entries for recurring item %s", bill_id)
            db.rollback()
    if created:
        logger.info("Created %d expected entries", created)
    return created


def _planning_stages():
    return (_top_up_entries,)


def planning_daily_job() -> None:
    """Daily planning job: top up expected entries. Each stage is isolated."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        today = today_local()
        for stage in _planning_stages():
            try:
                stage(db, today)
            except Exception:
                logger.exception("Planning job stage %s failed", stage.__name__)
                db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------


def auto_mark_paid_job() -> None:
    """Daily bills job: auto-pay due bills, then send the reminder notifications.

    Each stage is isolated so a failure in one does not discard the others.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        today = today_local()
        for stage in (
            _auto_pay_due_bills,
            _notify_due_soon,
            _notify_overdue,
            _notify_contracts_expiring,
            _notify_bill_drift,
            _notify_budget_thresholds,
            _refresh_tracked_prices,
            _notify_stock_and_prices,
            _purge_trash,
        ):
            try:
                stage(db, today)
            except Exception:
                logger.exception("Bills job stage %s failed", stage.__name__)
                db.rollback()
    finally:
        db.close()


# Arbitrary app-wide key for the Postgres advisory lock that elects the single
# worker/process allowed to run the scheduler.
SCHEDULER_LOCK_KEY = 727272
_lock_conn = None  # dedicated connection holding the lock for the process lifetime


def _acquire_scheduler_lock(engine=None) -> bool:
    """True if this process may run the scheduler.

    SQLite is single-process: always True. On Postgres, take a session-level
    advisory lock on a dedicated connection that stays open for the process
    lifetime (the lock is released automatically if the process dies)."""
    global _lock_conn
    if engine is None:
        from app.core.database import engine as app_engine

        engine = app_engine
    if engine.dialect.name != "postgresql":
        return True
    from sqlalchemy import text

    conn = engine.connect()
    # AUTOCOMMIT: otherwise SQLAlchemy's autobegin leaves this long-lived
    # connection idle-in-transaction, and idle_in_transaction_session_timeout
    # would silently kill it (and the lock with it).
    conn.execution_options(isolation_level="AUTOCOMMIT")
    try:
        got = bool(
            conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": SCHEDULER_LOCK_KEY}
            ).scalar()
        )
    except Exception:
        conn.close()
        raise
    if not got:
        conn.close()
        return False
    _lock_conn = conn
    return True


def _release_scheduler_lock() -> None:
    global _lock_conn
    conn, _lock_conn = _lock_conn, None
    if conn is not None:
        try:
            from sqlalchemy import text

            # Pooled close() would keep the session (and the lock) alive.
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCHEDULER_LOCK_KEY})
            conn.close()
        except Exception:
            logger.warning("Failed to close scheduler lock connection", exc_info=True)


def start_scheduler() -> None:
    """Start the background scheduler and run an immediate catch-up job."""
    from app.core.config import settings

    if not settings.enable_scheduler:
        logger.info("Scheduler disabled via ENABLE_SCHEDULER — skipping start")
        return

    if not _acquire_scheduler_lock():
        logger.info("Scheduler advisory lock held by another worker — not starting scheduler here")
        return

    # Just after midnight on the household's calendar, not UTC.
    scheduler.configure(timezone=_tz())
    scheduler.add_job(
        auto_mark_paid_job,
        CronTrigger(hour=0, minute=5, timezone=_tz()),
        id="auto_mark_paid_daily",
        replace_existing=True,
        coalesce=True,  # collapse missed runs into one
        max_instances=1,  # never overlap with a still-running job
        misfire_grace_time=3600,
    )
    # Run shortly after startup to catch bills missed while the server was down.
    scheduler.add_job(
        auto_mark_paid_job,
        id="auto_mark_paid_startup",
        replace_existing=True,
        max_instances=1,
    )
    # Expected entries before auto-pay looks at them; a separate job so the
    # bills job (and its tests) only ever see entries that already exist.
    scheduler.add_job(
        planning_daily_job,
        CronTrigger(hour=0, minute=1, timezone=_tz()),
        id="planning_daily",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        planning_daily_job,
        id="planning_startup",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _release_scheduler_lock()

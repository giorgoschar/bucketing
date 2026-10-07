"""Planning figures (spec §5): expected entries, the month picture, Upcoming.

All household-wide. Transactions count in base currency (exchange_rate
applied). Recurring items have no exchange rate, so entries count at face
value, as the old "Bills due" figure does. Anything not yet real is named as
a projection (``still_to_come``, ``projected``, ``net_projected``) and
``estimated`` marks a "≈" amount. Nothing here is a balance.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.clock import local_today
from app.core.money import ZERO, quantize
from app.models import (
    BillOccurrence,
    Bucket,
    BucketKind,
    BucketStatus,
    ItemDirection,
    OccurrenceStatus,
    RecurringBill,
    RuleKind,
    Transaction,
    TransactionType,
)
from app.services.bills import estimate_amount
from app.services.budgets import bucket_spent
from app.services.cash import cash_scope, cash_spending
from app.services.insights import _month_range
from app.services.money import base_amount_expr, to_base

# Stored status -> what people see (spec §3.3). Stored values never change.
STATUS_NAMES = {
    OccurrenceStatus.unpaid: "expected",
    OccurrenceStatus.paid: "done",
    OccurrenceStatus.skipped: "skipped",
}
YEARLY_KINDS = (RuleKind.yearly.value, RuleKind.easter_offset.value)


@dataclass(frozen=True)
class Entry:
    id: str
    item_id: str
    name: str
    direction: str  # "out" | "in"
    due_date: date
    status: str  # "expected" | "done" | "skipped"
    amount: Decimal | None  # done: what was paid; else set, item's, or estimate
    estimated: bool  # amount is the "≈" estimate
    currency: str
    bucket_id: str | None
    category_id: str | None
    transaction_id: str | None
    overdue: bool  # expected and due before today
    infrequent: bool  # the item recurs less than monthly (§5.3)


def _infrequent(bill: RecurringBill) -> bool:
    if bill.rule_kind in YEARLY_KINDS:
        return True
    return bill.rule_kind != RuleKind.weekly.value and (bill.interval_months or 1) > 1


def _entry(db: Session, occ: BillOccurrence, today: date, estimates: dict) -> Entry:
    bill, txn = occ.bill, occ.transaction
    estimated = False
    if occ.status == OccurrenceStatus.paid and txn is not None and txn.deleted_at is None:
        amount = quantize(to_base(txn.amount, txn.exchange_rate))
    elif occ.amount is not None:
        amount = quantize(occ.amount)
    elif bill.amount is not None:
        amount = quantize(bill.amount)
    else:
        if bill.id not in estimates:
            estimates[bill.id] = estimate_amount(db, bill.id)
        amount = estimates[bill.id]
        estimated = amount is not None
    status = STATUS_NAMES[occ.status]
    return Entry(
        id=occ.id,
        item_id=bill.id,
        name=bill.name,
        direction=bill.direction,
        due_date=occ.due_date,
        status=status,
        amount=amount,
        estimated=estimated,
        currency=bill.currency or "EUR",
        bucket_id=bill.bucket_id,
        category_id=bill.category_id,
        transaction_id=occ.transaction_id,
        overdue=status == "expected" and occ.due_date < today,
        infrequent=_infrequent(bill),
    )


def list_entries(
    db: Session, household_id: str, start: date, end: date, *, today: date | None = None
) -> list[Entry]:
    """Entries of active items due in [start, end], by date then name.

    A paused item's entries are hidden (spec §3.4.1); they stay stored.
    """
    today = today or local_today()
    occs = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill), joinedload(BillOccurrence.transaction))
        .filter(
            RecurringBill.household_id == household_id,
            RecurringBill.active_filter(),
            BillOccurrence.due_date >= start,
            BillOccurrence.due_date <= end,
        )
        .order_by(BillOccurrence.due_date, RecurringBill.name, BillOccurrence.id)
        .all()
    )
    estimates: dict = {}
    return [_entry(db, o, today, estimates) for o in occs]


def entry_for(db: Session, occ: BillOccurrence, *, today: date | None = None) -> Entry:
    """One entry, as list_entries shows it."""
    return _entry(db, occ, today or local_today(), {})


def _total(entries) -> Decimal:
    return quantize(sum((e.amount or ZERO for e in entries), ZERO))


def _transactions_sum(db: Session, *filters) -> Decimal:
    return quantize(
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .filter(Transaction.active(), *filters)
        .scalar()
    )


def _row(so_far: Decimal, still_to_come: Decimal) -> dict:
    return {
        "so_far": quantize(so_far),
        "still_to_come": quantize(still_to_come),
        "projected": quantize(so_far + still_to_come),
    }


def month_picture(
    db: Session, household_id: str, year: int, month: int, *, today: date | None = None
) -> dict:
    """Home's month picture (spec §5.1).

    - income: income this month; ``in`` entries still expected this month.
    - fixed: expenses linked to items with no bucket (plus the old app's
      claim-only payments of such items); ``out`` entries with no bucket
      still expected.
    - buckets: per monthly bucket, spent so far; still to come is budget
      minus spent, floored at 0; projected is max(budget, spent). A bucket
      without a budget projects its spend plus its items' expected entries.
    - net_projected: income projected minus fixed and buckets projected.
    - events_spent and cash: shown apart, not in the net.
    """
    today = today or local_today()
    start, end = _month_range(year, month)
    month_start = date(year, month, 1)
    in_month = (
        Transaction.household_id == household_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    )
    entries = list_entries(db, household_id, start, end, today=today)
    expected = [e for e in entries if e.status == "expected"]
    out, inc = ItemDirection.out.value, ItemDirection.in_.value

    income = _row(
        _transactions_sum(db, *in_month, Transaction.type == TransactionType.income),
        _total(e for e in expected if e.direction == inc),
    )
    fixed_paid = _transactions_sum(
        db,
        *in_month,
        Transaction.type == TransactionType.expense,
        Transaction.bucket_id.is_(None),
        Transaction.recurring_bill_id.isnot(None),
    )
    claimed = _total(
        e
        for e in entries
        if e.direction == out
        and e.status == "done"
        and e.transaction_id is None
        and e.bucket_id is None
    )
    fixed = _row(
        fixed_paid + claimed,
        _total(e for e in expected if e.direction == out and e.bucket_id is None),
    )

    spent_by_bucket = dict(
        db.query(Transaction.bucket_id, func.sum(base_amount_expr()))
        .filter(
            Transaction.active(),
            *in_month,
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.isnot(None),
        )
        .group_by(Transaction.bucket_id)
        .all()
    )
    expected_by_bucket: dict = defaultdict(Decimal)
    for e in expected:
        if e.direction == out and e.bucket_id:
            expected_by_bucket[e.bucket_id] += e.amount or ZERO
    rows, events_spent = [], ZERO
    totals = {"so_far": ZERO, "still_to_come": ZERO, "projected": ZERO}
    for b in (
        db.query(Bucket).filter(Bucket.household_id == household_id).order_by(Bucket.created_at)
    ):
        if b.kind == BucketKind.event.value:
            events_spent += quantize(spent_by_bucket.get(b.id) or 0)
            continue
        spent = bucket_spent(db, b, month_start)
        if b.status == BucketStatus.active and b.budget is not None:
            budget = quantize(b.budget)
            to_come = max(budget - spent, ZERO)
            projected = max(budget, spent)
        else:
            budget = None
            to_come = quantize(expected_by_bucket[b.id])
            projected = spent + to_come
        if not (spent or budget or to_come):
            continue
        rows.append(
            {
                "bucket_id": b.id,
                "name": b.name,
                "budget": budget,
                "so_far": spent,
                "still_to_come": to_come,
                "projected": projected,
            }
        )
        totals["so_far"] += spent
        totals["still_to_come"] += to_come
        totals["projected"] += projected
    buckets = {k: quantize(v) for k, v in totals.items()} | {"rows": rows}

    cash = cash_spending(db, household_id, start, end, cash_scope(db, household_id, None))
    return {
        "month": f"{year:04d}-{month:02d}",
        "income": income,
        "fixed": fixed,
        "buckets": buckets,
        "net_projected": quantize(income["projected"] - fixed["projected"] - buckets["projected"]),
        "events_spent": quantize(events_spent),
        "cash": cash.total,
        "estimated": any(e.estimated for e in expected),
    }


def upcoming(
    db: Session, household_id: str, *, today: date | None = None, days: int = 30
) -> list[dict]:
    """Plan › Upcoming (spec §5.2): the next ``days`` days of expected entries,
    day by day, with a running "net this month".

    The running net starts from this month's income minus expenses so far and
    adds each expected entry up to that day (in plus, out minus). Event-bucket
    spend is left out, as it is from Net (§5.1). It restarts
    at zero when the list crosses into the next month. It is a projection.
    """
    today = today or local_today()
    entries = [
        e
        for e in list_entries(db, household_id, today, today + timedelta(days=days), today=today)
        if e.status == "expected"
    ]
    start, _ = _month_range(today.year, today.month)
    so_far = (
        Transaction.household_id == household_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= today,
    )
    event_ids = db.query(Bucket.id).filter(
        Bucket.household_id == household_id, Bucket.kind == BucketKind.event.value
    )
    running = {
        (today.year, today.month): _transactions_sum(
            db, *so_far, Transaction.type == TransactionType.income
        )
        - _transactions_sum(
            db,
            *so_far,
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.is_(None) | Transaction.bucket_id.notin_(event_ids),
        )
    }
    out_days: list[dict] = []
    for e in entries:
        key = (e.due_date.year, e.due_date.month)
        sign = 1 if e.direction == ItemDirection.in_.value else -1
        running[key] = running.get(key, ZERO) + sign * (e.amount or ZERO)
        if not out_days or out_days[-1]["date"] != e.due_date:
            out_days.append({"date": e.due_date, "entries": [], "net_this_month": ZERO})
        out_days[-1]["entries"].append(e)
        out_days[-1]["net_this_month"] = quantize(running[key])
    return out_days

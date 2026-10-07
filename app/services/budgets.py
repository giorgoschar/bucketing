"""Bucket budgets by kind (spec §4.1).

A monthly bucket's budget is per calendar month (household timezone) and
resets on the 1st. An event bucket's budget is a total over its start_date to
end_date; either end may be open. Every new screen and the budget warnings use
these, so one bucket means one thing everywhere.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.money import percent, quantize
from app.models import Bucket, BucketKind, BucketStatus, Transaction, TransactionType
from app.services.insights import _month_range
from app.services.money import base_amount_expr


def bucket_period(bucket: Bucket, today: date) -> tuple[date | None, date | None]:
    """The dates a bucket's budget covers: this calendar month, or the event's dates."""
    if bucket.kind == BucketKind.event.value:
        return bucket.start_date, bucket.end_date
    return _month_range(today.year, today.month)


def bucket_spent(db: Session, bucket: Bucket, today: date) -> Decimal:
    """Expenses in the bucket over its budget period, in base currency."""
    start, end = bucket_period(bucket, today)
    q = db.query(func.coalesce(func.sum(base_amount_expr()), 0)).filter(
        Transaction.active(),
        Transaction.bucket_id == bucket.id,
        Transaction.type == TransactionType.expense,
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    return quantize(q.scalar())


@dataclass(frozen=True)
class BudgetRow:
    bucket_id: str
    name: str
    kind: str
    budget: Decimal | None
    spent: Decimal
    pct: Decimal | None  # spent / budget x 100, one decimal; None without a budget
    period_start: date | None
    period_end: date | None
    days_left: int | None  # event buckets with an end date, today included
    archive_suggested: bool  # an event whose end date has passed


def budget_rows(db: Session, household_id: str, today: date) -> list[BudgetRow]:
    """Every active bucket's spend against its budget, by kind."""
    buckets = (
        db.query(Bucket)
        .filter(Bucket.household_id == household_id, Bucket.status == BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )
    rows = []
    for b in buckets:
        start, end = bucket_period(b, today)
        spent = bucket_spent(db, b, today)
        budget = quantize(b.budget) if b.budget is not None else None
        event = b.kind == BucketKind.event.value
        rows.append(
            BudgetRow(
                bucket_id=b.id,
                name=b.name,
                kind=b.kind,
                budget=budget,
                spent=spent,
                pct=percent(spent, budget) if budget else None,
                period_start=start,
                period_end=end,
                days_left=max((end - today).days + 1, 0) if event and end else None,
                archive_suggested=bool(event and end and end < today),
            )
        )
    return rows

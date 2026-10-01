"""
Month/all-time summaries, bills and forecast for dashboards.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.clock import local_today
from app.models import (
    BillOccurrence,
    Bucket,
    BucketType,
    HouseholdMember,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)
from app.money import quantize
from app.services.money import split_to_base, to_base


def get_month_summary(db: Session, household_id: str, year: int, month: int, bucket_type: str = "", bucket_ids: list | None = None) -> dict:
    """
    Returns:
      - total_spent: total expense amount for the month
      - paid_by: {user_id: {"name": str, "color": str, "amount": Decimal}}
      - balance: who owes whom (simplified two-person logic + multi-person)
    """
    start = date(year, month, 1)
    # Last day of month
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    q = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
    if bucket_type:
        q = q.join(Bucket, Bucket.id == Transaction.bucket_id).filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    txns = q.options(joinedload(Transaction.splits)).all()

    total_spent = sum(to_base(t.amount, t.exchange_rate) for t in txns)

    # Amount paid by each user — use splits when present, else paid_by
    paid_by: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            paid_by[t.paid_by] += to_base(t.amount, t.exchange_rate)

    # Load member info
    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    member_map = {m.id: m for m in members}

    paid_by_detail = {}
    for uid, amount in paid_by.items():
        user = member_map.get(uid)
        if user:
            paid_by_detail[uid] = {
                "name": user.display_name,
                "color": user.avatar_color,
                "amount": quantize(amount),
            }

    return {
        "total_spent": quantize(total_spent),
        "paid_by": paid_by_detail,
        "period_start": start,
        "period_end": end,
    }


def get_all_time_summary(db: Session, household_id: str, bucket_type: str = "", bucket_ids: list | None = None) -> dict:
    """Total expenses and who-paid breakdown across all time for a household."""
    q = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
    if bucket_type:
        q = q.join(Bucket, Bucket.id == Transaction.bucket_id).filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    txns = q.options(joinedload(Transaction.splits)).all()
    total_spent = sum(to_base(t.amount, t.exchange_rate) for t in txns)

    paid_by: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            paid_by[t.paid_by] += to_base(t.amount, t.exchange_rate)

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    member_map = {m.id: m for m in members}

    paid_by_detail = {}
    for uid, amount in paid_by.items():
        user = member_map.get(uid)
        if user:
            paid_by_detail[uid] = {
                "name": user.display_name,
                "color": user.avatar_color,
                "amount": quantize(amount),
            }

    return {
        "total_spent": quantize(total_spent),
        "paid_by": paid_by_detail,
    }


def get_upcoming_bills(db: Session, household_id: str, days: int = 30) -> list:
    """Bills due within the next N days."""
    today = local_today()
    cutoff = today + timedelta(days=days)

    occurrences = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        # Templates render occ.bill.name/amount for every row — eager-load it.
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == household_id,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date >= today,
            BillOccurrence.due_date <= cutoff,
        )
        .order_by(BillOccurrence.due_date)
        .all()
    )
    return occurrences


def get_overdue_bills(db: Session, household_id: str) -> list:
    today = local_today()
    occurrences = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == household_id,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date < today,
        )
        .order_by(BillOccurrence.due_date)
        .all()
    )
    return occurrences

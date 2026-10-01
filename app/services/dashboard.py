"""
Month/all-time summaries, bills and forecast for dashboards.
"""
from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from app.clock import local_today
from app.models import (
    BillOccurrence,
    OccurrenceStatus,
    RecurringBill,
)
from app.services.insights import _month_range, get_insights_summary


def get_month_summary(db: Session, household_id: str, year: int, month: int, bucket_type: str = "", bucket_ids: list | None = None) -> dict:
    """
    Month total and who-paid breakdown, built from ``get_insights_summary`` so
    the dashboard and Insights agree: ``paid`` (alias ``amount``) is what each
    payer fronted, ``share`` what they owe; no-payer expenses go to an
    "Unassigned" row and payers who left show as "Former member".
    """
    start, end = _month_range(year, month)
    return get_insights_summary(db, household_id, start, end, bucket_type, bucket_ids)


def get_all_time_summary(db: Session, household_id: str, bucket_type: str = "", bucket_ids: list | None = None) -> dict:
    """Total expenses and who-paid breakdown across all time (Insights semantics)."""
    s = get_insights_summary(db, household_id, None, None, bucket_type, bucket_ids)
    return {"total_spent": s["total_spent"], "paid_by": s["paid_by"]}


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

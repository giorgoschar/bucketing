"""
Dashboard route.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import Household, Bucket, BucketStatus, Transaction, TransactionType
from app.services import get_month_summary, get_all_time_summary, get_upcoming_bills, get_overdue_bills
from app.templates import templates

router = APIRouter()


def _month_url(year: int, month: int) -> str:
    return f"/dashboard?year={year}&month={month}"


def _prev_month(year: int, month: int):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _next_month(year: int, month: int):
    if month == 12:
        return year + 1, 1
    return year, month + 1


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    year: int = Query(default=None),
    month: int = Query(default=None),
    all_time: bool = Query(default=False),
    bucket_type: str = Query(default=""),
    bucket_ids: str = Query(default=""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    today = date.today()

    # Default to current month
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    is_current_month = (year == today.year and month == today.month)

    py, pm = _prev_month(year, month)
    ny, nm = _next_month(year, month)
    prev_url = _month_url(py, pm)
    next_url = _month_url(ny, nm) if not is_current_month else None

    household = db.get(Household, hh_id)

    selected_bucket_ids = [b for b in bucket_ids.split(",") if b.strip()] if bucket_ids else []

    if all_time:
        summary = get_all_time_summary(db, hh_id, bucket_type=bucket_type, bucket_ids=selected_bucket_ids or None)
    else:
        summary = get_month_summary(db, hh_id, year, month, bucket_type=bucket_type, bucket_ids=selected_bucket_ids or None)
    upcoming = get_upcoming_bills(db, hh_id, days=30)
    overdue = get_overdue_bills(db, hh_id)

    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )

    recent = (
        db.query(Transaction)
        .filter_by(household_id=hh_id)
        .filter(Transaction.type == TransactionType.expense)
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(10)
        .all()
    )

    from app.models import HouseholdMember
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "household": household,
            "households": households,
            "summary": summary,
            "upcoming_bills": upcoming,
            "overdue_bills": overdue,
            "buckets": buckets,
            "recent": recent,
            "today": today,
            "year": year,
            "month": month,
            "is_current_month": is_current_month,
            "prev_url": prev_url,
            "next_url": next_url,
            "month_name": date(year, month, 1).strftime("%B %Y"),
            "all_time": all_time,
            "bucket_type": bucket_type,
            "selected_bucket_ids": selected_bucket_ids,
        },
    )

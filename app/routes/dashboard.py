"""
Dashboard route — lean daily health check.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import Household, HouseholdMember, Transaction, TransactionType
from app.services import (
    get_month_summary,
    get_income_total,
    get_bills_due_month_total,
    get_upcoming_bills,
    get_overdue_bills,
    get_bucket_spend_this_month,
)
from app.templates import templates

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    today = date.today()
    year, month = today.year, today.month

    household = db.get(Household, hh_id)

    from app.models import Bucket, BucketStatus
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )

    summary        = get_month_summary(db, hh_id, year, month)
    income_total   = get_income_total(db, hh_id, year, month)
    bills_due      = get_bills_due_month_total(db, hh_id, year, month)
    upcoming       = get_upcoming_bills(db, hh_id, days=30)
    overdue        = get_overdue_bills(db, hh_id)
    bucket_spend   = get_bucket_spend_this_month(db, hh_id, year, month)

    recent = (
        db.query(Transaction)
        .filter_by(household_id=hh_id)
        .filter(Transaction.type.in_([TransactionType.expense, TransactionType.income]))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(10)
        .all()
    )

    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households  = [db.get(Household, m.household_id) for m in memberships]

    # Only show income KPI card if there are income-tracked buckets with income this month
    show_income = income_total > 0 or any(b.show_income for b in buckets)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request":        request,
            "user":           user,
            "household":      household,
            "households":     households,
            "summary":        summary,
            "income_total":   income_total,
            "bills_due":      bills_due,
            "show_income":    show_income,
            "upcoming_bills": upcoming,
            "overdue_bills":  overdue,
            "buckets":        buckets,
            "bucket_spend":   bucket_spend,
            "recent":         recent,
            "today":          today,
            "month_name":     date(year, month, 1).strftime("%B %Y"),
        },
    )

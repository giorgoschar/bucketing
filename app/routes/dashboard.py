"""
Dashboard route — lean daily health check.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.clock import local_today
from app.database import get_db
from app.models import Transaction, TransactionType
from app.services import (
    base_ctx,
    get_bills_due_month_total,
    get_bucket_spend_this_month,
    get_income_total,
    get_month_summary,
    get_overdue_bills,
    get_upcoming_bills,
    in_out,
)
from app.templates import templates

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    today = local_today()
    year, month = today.year, today.month

    ctx = base_ctx(db, user, hh_id)
    household = ctx["household"]
    households = ctx["households"]

    from app.models import Bucket, BucketStatus
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )

    summary        = get_month_summary(db, hh_id, year, month, include_cash=True)
    income_total   = get_income_total(db, hh_id, year, month)
    bills_due      = get_bills_due_month_total(db, hh_id, year, month)
    upcoming       = get_upcoming_bills(db, hh_id, days=30)
    overdue        = get_overdue_bills(db, hh_id)
    bucket_spend   = get_bucket_spend_this_month(db, hh_id, year, month)

    recent = (
        db.query(Transaction)
        .filter_by(household_id=hh_id)
        .filter(Transaction.active())
        .filter(Transaction.type.in_([TransactionType.expense, TransactionType.income]))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(10)
        .all()
    )

    # Budget progress per bucket, clamped to 0..100 for the bar width.
    # Computed here rather than in the template: bucket.budget is a Decimal and
    # bucket_spend holds floats, and Jinja cannot divide the two.
    bucket_budget_pct = {}
    for b in buckets:
        if not b.budget:
            continue
        budget = float(b.budget)
        if budget <= 0:
            continue
        spent = float(bucket_spend.get(b.id, 0.0))
        bucket_budget_pct[b.id] = min(max(spent / budget * 100, 0), 100)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request":        request,
            "user":           user,
            "household":      household,
            "households":     households,
            "summary":        summary,
            "income_total":   income_total,
            # Always shown: income needs no bucket, and Out alone is useful.
            "in_out":         in_out(income_total, summary),
            "bills_due":      bills_due,
            "upcoming_bills": upcoming,
            "overdue_bills":  overdue,
            "buckets":        buckets,
            "bucket_spend":   bucket_spend,
            "bucket_budget_pct": bucket_budget_pct,
            "recent":         recent,
            "today":          today,
            "month_name":     date(year, month, 1).strftime("%B %Y"),
        },
    )

"""
Insights / Analytics route.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import Household, HouseholdMember
from app.services import (
    get_month_summary,
    get_all_time_summary,
    get_income_total,
    get_bills_due_month_total,
    get_category_breakdown,
    get_monthly_trend,
    get_forecast,
    get_bucket_budget_status,
)
from app.templates import templates

router = APIRouter()


def _month_url(year: int, month: int, **extra) -> str:
    params = f"year={year}&month={month}"
    for k, v in extra.items():
        if v:
            params += f"&{k}={v}"
    return f"/insights?{params}"


def _prev_month(year: int, month: int):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int):
    return (year + 1, 1) if month == 12 else (year, month + 1)


@router.get("/insights", response_class=HTMLResponse)
def insights(
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

    if year is None:
        year = today.year
    if month is None:
        month = today.month

    is_current_month = (year == today.year and month == today.month)

    py, pm = _prev_month(year, month)
    ny, nm = _next_month(year, month)
    prev_url = _month_url(py, pm, bucket_type=bucket_type, bucket_ids=bucket_ids)
    next_url = _month_url(ny, nm, bucket_type=bucket_type, bucket_ids=bucket_ids) if not is_current_month else None

    household = db.get(Household, hh_id)
    selected_bucket_ids = [b for b in bucket_ids.split(",") if b.strip()] if bucket_ids else []

    if all_time:
        summary = get_all_time_summary(db, hh_id, bucket_type=bucket_type, bucket_ids=selected_bucket_ids or None)
        income_total    = None
        bills_due       = None
        categories      = []
        budget_status   = []
        forecast        = {}
    else:
        summary         = get_month_summary(db, hh_id, year, month, bucket_type=bucket_type, bucket_ids=selected_bucket_ids or None)
        income_total    = get_income_total(db, hh_id, year, month)
        bills_due       = get_bills_due_month_total(db, hh_id, year, month)
        categories      = get_category_breakdown(db, hh_id, year, month, bucket_type=bucket_type, bucket_ids=selected_bucket_ids or None)
        budget_status   = get_bucket_budget_status(db, hh_id, year, month)
        forecast        = get_forecast(db, hh_id) if is_current_month else {}

    trend = get_monthly_trend(db, hh_id, n_months=6)
    trend_max = max((m["total"] for m in trend), default=1) or 1

    from app.models import Bucket, BucketStatus
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )

    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households  = [db.get(Household, m.household_id) for m in memberships]

    net = round((income_total or 0) - summary["total_spent"], 2) if income_total is not None else None

    template = "insights_partial.html" if request.headers.get("HX-Request") else "insights.html"
    return templates.TemplateResponse(
        template,
        {
            "request":              request,
            "user":                 user,
            "household":            household,
            "households":           households,
            "summary":              summary,
            "income_total":         income_total,
            "bills_due":            bills_due,
            "net":                  net,
            "categories":           categories,
            "budget_status":        budget_status,
            "forecast":             forecast,
            "trend":                trend,
            "trend_max":            trend_max,
            "buckets":              buckets,
            "today":                today,
            "year":                 year,
            "month":                month,
            "is_current_month":     is_current_month,
            "prev_url":             prev_url,
            "next_url":             next_url,
            "month_name":           date(year, month, 1).strftime("%B %Y"),
            "all_time":             all_time,
            "bucket_type":          bucket_type,
            "selected_bucket_ids":  selected_bucket_ids,
        },
    )

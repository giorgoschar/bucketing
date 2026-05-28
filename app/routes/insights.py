"""
Insights / Analytics route.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth, require_csrf
from app.models import Household, HouseholdMember, Bucket, BucketStatus, Category
from app.services import (
    get_insights_summary,
    get_insights_income,
    get_insights_bills_due,
    get_insights_category_breakdown,
    get_insights_bucket_breakdown,
    get_insights_category_trend,
    get_insights_budget_status,
    get_monthly_trend,
    get_forecast,
)
from app.templates import templates

router = APIRouter(dependencies=[Depends(require_csrf)])


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s) if s.strip() else None
    except ValueError:
        return None


@router.get("/insights", response_class=HTMLResponse)
def insights(
    request: Request,
    # Date range (default: current month)
    start_date: str = Query(default=""),
    end_date:   str = Query(default=""),
    # Preset shortcut sent by the filter bar (this_month, last_month, last_3m, last_6m, this_year, all_time, custom)
    preset:     str = Query(default="this_month"),
    # Filters
    bucket_type:  str = Query(default=""),
    bucket_ids:   str = Query(default=""),
    category_ids: str = Query(default=""),
    paid_by:      str = Query(default=""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    today = date.today()

    # --- Resolve date range ---
    start: date | None = None
    end:   date | None = None

    if preset == "all_time":
        start, end = None, None
    elif preset == "last_month":
        first_of_month = today.replace(day=1)
        end   = first_of_month - timedelta(days=1)
        start = end.replace(day=1)
    elif preset == "last_3m":
        end   = today
        m, y  = today.month - 3, today.year
        while m <= 0: m += 12; y -= 1  # noqa
        start = date(y, m, 1)
    elif preset == "last_6m":
        end   = today
        m, y  = today.month - 6, today.year
        while m <= 0: m += 12; y -= 1  # noqa
        start = date(y, m, 1)
    elif preset == "this_year":
        start = date(today.year, 1, 1)
        end   = today
    elif preset == "custom" and start_date and end_date:
        start = _parse_date(start_date)
        end   = _parse_date(end_date)
    else:  # this_month (default)
        start = date(today.year, today.month, 1)
        end   = today

    all_time = (start is None and end is None)
    is_current_month = (
        not all_time
        and start == date(today.year, today.month, 1)
        and end == today
    )

    selected_bucket_ids  = [b for b in bucket_ids.split(",")   if b.strip()]
    selected_category_ids = [c for c in category_ids.split(",") if c.strip()]

    # --- Fetch data ---
    summary = get_insights_summary(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    income_total   = get_insights_income(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    bills_due      = get_insights_bills_due(db, hh_id, start, end)
    categories     = get_insights_category_breakdown(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    budget_status  = get_insights_budget_status(db, hh_id, start, end)
    bucket_breakdown = get_insights_bucket_breakdown(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    category_trend = get_insights_category_trend(
        db, hh_id, n_months=6,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    forecast       = get_forecast(db, hh_id) if is_current_month else {}
    trend          = get_monthly_trend(db, hh_id, n_months=6)
    trend_max      = max((m["total"] for m in trend), default=1) or 1
    cat_trend_max  = max(
        (sum(row["values"]) for row in category_trend.get("series", []) if row["values"]),
        default=1
    ) or 1

    net = round(income_total - summary["total_spent"], 2)

    # --- Supporting data for filter dropdowns ---
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )
    all_categories = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .order_by(Category.name)
        .all()
    )
    members = (
        db.query(HouseholdMember)
        .filter_by(household_id=hh_id)
        .all()
    )
    member_users = [db.get(__import__('app.models', fromlist=['User']).User, m.user_id) for m in members]
    member_users = [u for u in member_users if u]

    household   = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households  = [db.get(Household, m.household_id) for m in memberships]

    # Human-readable period label
    if all_time:
        period_label = "All time"
    elif preset == "last_month":
        period_label = start.strftime("%B %Y") if start else "Last month"
    elif preset == "last_3m":
        period_label = "Last 3 months"
    elif preset == "last_6m":
        period_label = "Last 6 months"
    elif preset == "this_year":
        period_label = str(today.year)
    elif preset == "custom" and start and end:
        period_label = f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    else:
        period_label = today.strftime("%B %Y")

    is_partial = bool(request.headers.get("HX-Request")) and not request.headers.get("HX-Boosted")
    template = "insights_partial.html" if is_partial else "insights.html"

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
            "bucket_breakdown":     bucket_breakdown,
            "category_trend":       category_trend,
            "cat_trend_max":        cat_trend_max,
            "forecast":             forecast,
            "trend":                trend,
            "trend_max":            trend_max,
            "buckets":              buckets,
            "all_categories":       all_categories,
            "member_users":         member_users,
            "today":                today,
            "all_time":             all_time,
            "is_current_month":     is_current_month,
            "period_label":         period_label,
            "preset":               preset,
            "start_date":           start.isoformat() if start else "",
            "end_date":             end.isoformat() if end else "",
            "bucket_type":          bucket_type,
            "selected_bucket_ids":  selected_bucket_ids,
            "selected_category_ids": selected_category_ids,
            "paid_by":              paid_by,
        },
    )


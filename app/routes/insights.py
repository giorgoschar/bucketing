"""
Insights / Analytics route.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import Bucket, BucketStatus, Category, Household, HouseholdMember, User
from app.services import (
    resolve_insight_period,
    get_insights_summary,
    get_insights_income,
    get_insights_bills_due,
    get_insights_category_breakdown,
    get_insights_bucket_breakdown,
    get_insights_category_trend,
    get_insights_budget_status,
    get_insights_kpis,
    get_monthly_trend,
    get_forecast,
)
from app.templates import templates

# GET-only router: require_csrf was a no-op here (it returns early for safe
# methods) and only added confusion.
router = APIRouter()


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

    period = resolve_insight_period(preset, start_date, end_date, today)
    start, end = period["start"], period["end"]

    selected_bucket_ids   = [b for b in bucket_ids.split(",")   if b.strip()]
    selected_category_ids = [c for c in category_ids.split(",") if c.strip()]

    # Every chart below takes the same filter set, so the numbers on the page
    # all describe the same slice of data.
    common = {
        "bucket_type":  bucket_type,
        "bucket_ids":   selected_bucket_ids or None,
        "category_ids": selected_category_ids or None,
        "paid_by":      paid_by or None,
    }

    summary          = get_insights_summary(db, hh_id, start, end, **common)
    income_total     = get_insights_income(db, hh_id, start, end, **common)
    bills_due        = get_insights_bills_due(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
    )
    categories       = get_insights_category_breakdown(db, hh_id, start, end, **common)
    budget_status    = get_insights_budget_status(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
    )
    bucket_breakdown = get_insights_bucket_breakdown(db, hh_id, start, end, **common)
    category_trend   = get_insights_category_trend(db, hh_id, n_months=6, **common)
    trend            = get_monthly_trend(db, hh_id, n_months=6, **common)
    forecast         = get_forecast(db, hh_id) if period["is_current_month"] else {}
    kpis             = get_insights_kpis(db, hh_id, start, end, **common)

    trend_max = max((m["total"] for m in trend), default=1) or 1
    # The chart scales each bar against the largest single monthly value, which
    # the service now reports directly.
    cat_trend_max = category_trend.get("max_value") or 1

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
    # Single join instead of one db.get() per membership.
    member_users = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .order_by(User.display_name)
        .all()
    )

    household   = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households  = [db.get(Household, m.household_id) for m in memberships]

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
            "kpis":                 kpis,
            "forecast":             forecast,
            "trend":                trend,
            "trend_max":            trend_max,
            "buckets":              buckets,
            "all_categories":       all_categories,
            "member_users":         member_users,
            "today":                today,
            "all_time":             period["all_time"],
            "is_current_month":     period["is_current_month"],
            "period_label":         period["period_label"],
            "preset":               period["preset"],
            "start_date":           start.isoformat() if start else "",
            "end_date":             end.isoformat() if end else "",
            "bucket_type":          bucket_type,
            "selected_bucket_ids":  selected_bucket_ids,
            "selected_category_ids": selected_category_ids,
            "paid_by":              paid_by,
        },
    )

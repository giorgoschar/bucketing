"""
Insights / Analytics route.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.models import Bucket, BucketStatus, Category, Household, HouseholdMember, User
from app.services import InsightFilters, build_insights
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
    today = local_today()

    data = build_insights(db, hh_id, InsightFilters(
        preset=preset, start_date=start_date, end_date=end_date,
        bucket_type=bucket_type, bucket_ids=bucket_ids,
        category_ids=category_ids, paid_by=paid_by, today=today,
    ))
    period, start, end = data["period"], data["start"], data["end"]
    selected_bucket_ids = data["selected_bucket_ids"]
    selected_category_ids = data["selected_category_ids"]
    trend, category_trend = data["trend"], data["category_trend"]

    trend_max = max((m["total"] for m in trend), default=1) or 1
    # The chart scales each bar against the largest single monthly value, which
    # the service now reports directly.
    cat_trend_max = category_trend.get("max_value") or 1

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
            "summary":              data["summary"],
            "income_total":         data["income_total"],
            "bills_due":            data["bills_due"],
            "net":                  data["net"],
            "in_out":               data["in_out"],
            "categories":           data["categories"],
            "budget_status":        data["budget_status"],
            "bucket_breakdown":     data["bucket_breakdown"],
            "category_trend":       category_trend,
            "cat_trend_max":        cat_trend_max,
            "kpis":                 data["kpis"],
            "by_method":            data["by_method"],
            "cash_share":           data["cash_share"],
            "fuel":                 data["fuel"],
            "forecast":             data["forecast"],
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

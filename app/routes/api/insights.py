"""
API insights / analytics route.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
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

router = APIRouter(prefix="/insights", tags=["insights"])


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s.strip()) if s.strip() else None
    except ValueError:
        return None


@router.get("")
def insights(
    preset:       str = Query(default="this_month"),  # this_month | last_month | last_3m | last_6m | this_year | all_time | custom
    start_date:   str = Query(default=""),
    end_date:     str = Query(default=""),
    bucket_type:  str = Query(default=""),
    bucket_ids:   str = Query(default=""),   # comma-separated
    category_ids: str = Query(default=""),   # comma-separated
    paid_by:      str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """
    Full analytics summary: totals, category/bucket breakdown, trend, and forecast.
    Use the `preset` parameter for common date ranges, or `start_date`/`end_date` for custom.
    """
    user, hh_id = auth
    today = date.today()

    # Resolve date range from preset
    start: date | None = None
    end:   date | None = None

    if preset == "all_time":
        start, end = None, None
    elif preset == "last_month":
        first_of_month = today.replace(day=1)
        end   = first_of_month - timedelta(days=1)
        start = end.replace(day=1)
    elif preset == "last_3m":
        end = today
        m, y = today.month - 3, today.year
        while m <= 0:
            m += 12
            y -= 1
        start = date(y, m, 1)
    elif preset == "last_6m":
        end = today
        m, y = today.month - 6, today.year
        while m <= 0:
            m += 12
            y -= 1
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

    selected_bucket_ids   = [b for b in bucket_ids.split(",")   if b.strip()]
    selected_category_ids = [c for c in category_ids.split(",") if c.strip()]

    is_current_month = (
        start is not None
        and end is not None
        and start == date(today.year, today.month, 1)
        and end == today
    )

    summary = get_insights_summary(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    income_total = get_insights_income(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    bills_due = get_insights_bills_due(db, hh_id, start, end)
    categories = get_insights_category_breakdown(
        db, hh_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
        paid_by=paid_by or None,
    )
    budget_status = get_insights_budget_status(db, hh_id, start, end)
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
    trend    = get_monthly_trend(db, hh_id, n_months=6)
    forecast = get_forecast(db, hh_id) if is_current_month else {}

    return {
        "preset":          preset,
        "start_date":      start.isoformat() if start else None,
        "end_date":        end.isoformat()   if end   else None,
        "total_spent":     summary["total_spent"],
        "income_total":    income_total,
        "bills_due_total": bills_due,
        "net":             round(income_total - summary["total_spent"], 2),
        "paid_by":         summary.get("paid_by", {}),
        "categories":      categories,
        "budget_status":   budget_status,
        "bucket_breakdown": bucket_breakdown,
        "category_trend":  category_trend,
        "monthly_trend":   trend,
        "forecast":        forecast,
    }

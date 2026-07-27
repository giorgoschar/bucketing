"""
API insights / analytics route.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.services import (
    resolve_insight_period,
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


def _bucket_row(row: dict, extra: dict) -> dict:
    """Flatten a {"bucket": <Bucket ORM>, ...} row into an explicit payload.

    Returning the ORM object directly works — jsonable_encoder dumps its
    columns — but it silently exposes every column and reshapes whenever the
    model changes. Clients get a defined contract instead.
    """
    b = row["bucket"]
    return {
        "bucket_id":   b.id,
        "bucket_name": b.name,
        "icon":        b.icon,
        "color":       b.color,
        **extra,
    }


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

    # Shared with the HTML route so both endpoints resolve ranges identically.
    period = resolve_insight_period(preset, start_date, end_date)
    start, end = period["start"], period["end"]

    selected_bucket_ids   = [b for b in bucket_ids.split(",")   if b.strip()]
    selected_category_ids = [c for c in category_ids.split(",") if c.strip()]

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

    return {
        "preset":          period["preset"],
        "period_label":    period["period_label"],
        "start_date":      start.isoformat() if start else None,
        "end_date":        end.isoformat()   if end   else None,
        "total_spent":     summary["total_spent"],
        "income_total":    income_total,
        "bills_due_total": bills_due,
        "net":             round(income_total - summary["total_spent"], 2),
        "paid_by":         summary.get("paid_by", {}),
        "categories":      categories,
        "budget_status":   [
            _bucket_row(row, {
                "spent":       row["spent"],
                "budget":      row["budget"],
                "pct":         row["pct_actual"],
                "remaining":   row["remaining"],
                "over_budget": row["over_budget"],
            })
            for row in budget_status
        ],
        "bucket_breakdown": [
            _bucket_row(row, {"total": row["total"], "pct": row["pct"]})
            for row in bucket_breakdown
        ],
        "category_trend":  category_trend,
        "monthly_trend":   trend,
        "forecast":        forecast,
    }

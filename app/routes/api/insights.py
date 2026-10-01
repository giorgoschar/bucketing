"""
API insights / analytics route.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.services import InsightFilters, build_insights

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

    # Shared with the HTML route so both endpoints compute identical figures.
    data = build_insights(db, hh_id, InsightFilters(
        preset=preset, start_date=start_date, end_date=end_date,
        bucket_type=bucket_type, bucket_ids=bucket_ids,
        category_ids=category_ids, paid_by=paid_by,
    ))
    period, start, end = data["period"], data["start"], data["end"]
    summary = data["summary"]

    return {
        "preset":          period["preset"],
        "period_label":    period["period_label"],
        "start_date":      start.isoformat() if start else None,
        "end_date":        end.isoformat()   if end   else None,
        "total_spent":     summary["total_spent"],
        "income_total":    data["income_total"],
        "bills_due_total": data["bills_due"],
        "net":             data["net"],
        "paid_by":         summary.get("paid_by", {}),
        "kpis":            data["kpis"],
        "categories":      data["categories"],
        "budget_status":   [
            _bucket_row(row, {
                "spent":       row["spent"],
                "budget":      row["budget"],
                "pct":         row["pct_actual"],
                "remaining":   row["remaining"],
                "over_budget": row["over_budget"],
            })
            for row in data["budget_status"]
        ],
        "bucket_breakdown": [
            _bucket_row(row, {"total": row["total"], "pct": row["pct"]})
            for row in data["bucket_breakdown"]
        ],
        "category_trend":  data["category_trend"],
        "monthly_trend":   data["trend"],
        "forecast":        data["forecast"],
        "by_method":       data["by_method"],
        "cash_share":      data["cash_share"],
    }

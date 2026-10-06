"""
API dashboard route — monthly overview summary.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.config import settings
from app.core.database import get_db
from app.core.money import quantize
from app.services import (
    get_income_total,
    get_month_summary,
    get_overdue_bills,
    get_upcoming_bills,
    in_out,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard_summary(
    year: int = Query(default=None),
    month: int = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """
    Monthly expense summary: total spent, who paid, income total, In / Out /
    Net, upcoming bills (next 60 days), and overdue bills.
    """
    user, hh_id = auth
    today = local_today()
    y = year or today.year
    m = month or today.month

    summary = get_month_summary(db, hh_id, y, m, include_cash=True)
    income = get_income_total(db, hh_id, y, m)
    upcoming = get_upcoming_bills(db, hh_id, days=settings.upcoming_bills_days)
    overdue = get_overdue_bills(db, hh_id)

    def _occ(o):
        return {
            "id": o.id,
            "bill_id": o.bill_id,
            "bill_name": o.bill.name if o.bill else None,
            "due_date": o.due_date.isoformat(),
            "amount": quantize(o.amount or (o.bill.amount if o.bill else None)),
            "currency": o.bill.currency if o.bill else None,
            "status": o.status.value,
        }

    return {
        "year": y,
        "month": m,
        # Includes cash not logged yet (see app.services.cash).
        "total_spent": summary["total_spent"],
        "cash_not_logged": summary["cash_not_logged"],
        "income_total": income,
        # In / Out / Net for the month, as on the dashboard and Insights.
        "in_out": in_out(income, summary),
        "paid_by": summary["paid_by"],
        "period_start": summary["period_start"].isoformat(),
        "period_end": summary["period_end"].isoformat(),
        "upcoming_bills": [_occ(o) for o in upcoming],
        "overdue_bills": [_occ(o) for o in overdue],
    }

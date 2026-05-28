"""
API dashboard route — monthly overview summary.
"""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.services import get_month_summary, get_upcoming_bills, get_overdue_bills, get_income_total
from app.config import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard_summary(
    year:  int = Query(default=None),
    month: int = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """
    Monthly expense summary: total spent, who paid, income total,
    upcoming bills (next 60 days), and overdue bills.
    """
    user, hh_id = auth
    today = date.today()
    y = year  or today.year
    m = month or today.month

    summary  = get_month_summary(db, hh_id, y, m)
    income   = get_income_total(db, hh_id, y, m)
    upcoming = get_upcoming_bills(db, hh_id, days=settings.upcoming_bills_days)
    overdue  = get_overdue_bills(db, hh_id)

    def _occ(o):
        return {
            "id":       o.id,
            "bill_id":  o.bill_id,
            "bill_name": o.bill.name if o.bill else None,
            "due_date": o.due_date.isoformat(),
            "amount":   float(o.amount or o.bill.amount or 0) if o.bill else float(o.amount or 0),
            "currency": o.bill.currency if o.bill else None,
            "status":   o.status.value,
        }

    return {
        "year":          y,
        "month":         m,
        "total_spent":   summary["total_spent"],
        "income_total":  income,
        "paid_by":       summary["paid_by"],
        "period_start":  summary["period_start"].isoformat(),
        "period_end":    summary["period_end"].isoformat(),
        "upcoming_bills": [_occ(o) for o in upcoming],
        "overdue_bills":  [_occ(o) for o in overdue],
    }

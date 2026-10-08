"""
/api/v1/plan — the planning figures (spec §5): the month picture, Upcoming,
the Year, budgets by bucket kind and bucket pace. Every projected figure is
named as one.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.planning_models import (
    BudgetRowOut,
    MonthPictureOut,
    PaceOut,
    UpcomingDayOut,
    YearOut,
)
from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.services.budgets import bucket_pace, budget_rows
from app.services.planning import month_picture, upcoming, year_outlook

router = APIRouter(prefix="/plan", tags=["plan"])

_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value: str | None) -> tuple[int, int]:
    """'YYYY-MM' -> (year, month); blank is this month. HTTP 400 otherwise."""
    if not value:
        today = local_today()
        return today.year, today.month
    m = _MONTH.match(value.strip())
    if not m or not 1 <= int(m.group(2)) <= 12 or not 1970 <= int(m.group(1)) <= 2200:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM.")
    return int(m.group(1)), int(m.group(2))


@router.get("/month", response_model=MonthPictureOut)
def month(
    month: str | None = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    year, mon = parse_month(month)
    return month_picture(db, hh_id, year, mon)


@router.get("/upcoming", response_model=list[UpcomingDayOut])
def upcoming_days(
    days: int = Query(default=30, ge=1, le=90),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    return upcoming(db, hh_id, days=days)


@router.get("/year", response_model=YearOut)
def year(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return year_outlook(db, hh_id)


@router.get("/pace", response_model=list[PaceOut])
def pace(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return bucket_pace(db, hh_id, today=local_today())


@router.get("/budgets", response_model=list[BudgetRowOut])
def budgets(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Every active bucket against its budget: monthly per calendar month,
    events over their dates with days left (spec §4.1)."""
    user, hh_id = auth
    return budget_rows(db, hh_id, local_today())

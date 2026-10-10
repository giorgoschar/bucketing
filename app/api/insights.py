"""
API insights / analytics route.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.plan import parse_month
from app.api.planning_models import BillRowOut, CategoryUsualOut, Money
from app.api.statement_models import StatementListOut, StatementOut
from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.services import InsightFilters, build_insights
from app.services.bill_history import bills_overview
from app.services.insights import get_category_detail, resolve_insight_period
from app.services.person import get_person_summary
from app.services.statement import (
    build_list,
    build_statement,
    first_data_month,
    is_past,
    mark_reviewed,
    month_key,
    parse_month_key,
)
from app.services.usual import categories_vs_usual
from app.validators import household_member_ids

router = APIRouter(prefix="/insights", tags=["insights"])

MONTH_SERIES = ("6", "12", "24")


def _bucket_row(row: dict, extra: dict) -> dict:
    """Flatten a {"bucket": <Bucket ORM>, ...} row into an explicit payload.

    Returning the ORM object directly works — jsonable_encoder dumps its
    columns — but it silently exposes every column and reshapes whenever the
    model changes. Clients get a defined contract instead.
    """
    b = row["bucket"]
    return {
        "bucket_id": b.id,
        "bucket_name": b.name,
        "icon": b.icon,
        "color": b.color,
        **extra,
    }


@router.get("")
def insights(
    preset: str = Query(
        default="this_month"
    ),  # this_month | last_month | last_3m | last_6m | this_year | all_time | custom
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    bucket_type: str = Query(default=""),
    bucket_ids: str = Query(default=""),  # comma-separated
    category_ids: str = Query(default=""),  # comma-separated
    paid_by: str = Query(default=""),
    months: str = Query(default="6"),  # 6 | 12 | 24: the length of monthly_in_out
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """
    Full analytics summary: totals, category/bucket breakdown, trend, and forecast.
    Use the `preset` parameter for common date ranges, or `start_date`/`end_date` for custom.
    """
    user, hh_id = auth
    if months not in MONTH_SERIES:
        raise HTTPException(status_code=400, detail="months must be 6, 12 or 24.")

    # Shared with the HTML route so both endpoints compute identical figures.
    data = build_insights(
        db,
        hh_id,
        InsightFilters(
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            bucket_type=bucket_type,
            bucket_ids=bucket_ids,
            category_ids=category_ids,
            paid_by=paid_by,
            months=int(months),
        ),
    )
    period, start, end = data["period"], data["start"], data["end"]
    summary = data["summary"]

    return {
        "preset": period["preset"],
        "period_label": period["period_label"],
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        # Includes cash spending; logged_total is the expenses alone.
        "total_spent": summary["total_spent"],
        "logged_total": summary["logged_total"],
        "cash_not_logged": summary["cash_not_logged"],
        "cash_outs": summary["cash_outs"],
        "income_total": data["income_total"],
        "bills_due_total": data["bills_due"],
        "net": data["net"],
        # In / Out (logged + not-yet-logged cash) / Net for the period.
        "in_out": data["in_out"],
        # `months` (6, 12 or 24) calendar months to this one, oldest first; ignores the period (2d §7.3).
        "monthly_in_out": data["monthly_in_out"],
        "paid_by": summary.get("paid_by", {}),
        "kpis": data["kpis"],
        "categories": data["categories"],
        "budget_status": [
            _bucket_row(
                row,
                {
                    "spent": row["spent"],
                    "budget": row["budget"],
                    "pct": row["pct_actual"],
                    "remaining": row["remaining"],
                    "over_budget": row["over_budget"],
                },
            )
            for row in data["budget_status"]
        ],
        "bucket_breakdown": [
            _bucket_row(row, {"total": row["total"], "pct": row["pct"]})
            for row in data["bucket_breakdown"]
        ],
        "category_trend": data["category_trend"],
        "monthly_trend": data["trend"],
        "forecast": data["forecast"],
        "by_method": data["by_method"],
        "cash_share": data["cash_share"],
        # Litres, spend and price per litre of fuel expenses; null without any.
        "fuel": data["fuel"],
    }


@router.get("/categories-vs-usual", response_model=list[CategoryUsualOut])
def categories_usual(
    month: str | None = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Each category this month against its usual (spec §4.2); flagged ones first."""
    user, hh_id = auth
    year, mon = parse_month(month)
    return categories_vs_usual(db, hh_id, year, mon)


@router.get("/bills", response_model=list[BillRowOut])
def bills(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Every recurring out item that is active or has been paid, with its last
    amount, a sparkline, its 12-month total and, when the latest payment is
    recent and unusual, its change. Ignores the Insights lens and period."""
    user, hh_id = auth
    return bills_overview(db, hh_id, local_today())


class PersonLargestOut(BaseModel):
    amount: Money
    notes: str | None
    date: dt.date


class PersonShareOut(BaseModel):
    user_id: str
    paid_out: Money
    my_share: Money
    balance: Money  # paid_out - my_share; positive: paid more than their share
    share_pct: Money | None
    household_total: Money
    largest: PersonLargestOut | None
    shared_count: int
    transaction_count: int


def _member_or_404(db: Session, hh_id: str, user_id: str) -> str:
    if user_id not in household_member_ids(db, hh_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return user_id


@router.get("/person", response_model=PersonShareOut)
def person_share(
    user_id: str = Query(...),
    preset: str = Query(default="this_month"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Paid out vs my share for one member over the period (2d §7.1). The
    settle-up ``net`` and ``by_bucket`` of get_person_summary are left out:
    there is no settle up in the new app."""
    user, hh_id = auth
    _member_or_404(db, hh_id, user_id)
    period = resolve_insight_period(preset, start_date, end_date)
    s = get_person_summary(db, hh_id, user_id, period["start"], period["end"])
    return PersonShareOut(
        user_id=user_id,
        paid_out=s["paid_out"],
        my_share=s["my_share"],
        balance=s["balance"],
        share_pct=s["share_pct"],
        household_total=s["household_total"],
        largest=s["largest"],
        shared_count=s["shared_count"],
        transaction_count=s["transaction_count"],
    )


class CategoryRefOut(BaseModel):
    id: str
    name: str
    icon: str | None
    color: str | None


class CategoryMonthOut(BaseModel):
    year: int
    month: int
    label: str
    total: Money


class CategoryMerchantOut(BaseModel):
    merchant: str  # "Other" groups expenses without one
    count: int
    total: Money


class CategoryExpenseOut(BaseModel):
    id: str
    date: dt.date
    merchant: str | None
    notes: str | None
    amount: Money  # the lens person's share under a member lens
    paid_by: str | None


class CategoryRuleRefOut(BaseModel):
    id: str
    pattern: str
    match_count: int


class CategoryDetailOut(BaseModel):
    category: CategoryRefOut | None  # null: uncategorised
    total: Money
    count: int
    avg_per_month: Money | None
    months: list[CategoryMonthOut]
    merchants: list[CategoryMerchantOut]
    recent: list[CategoryExpenseOut]
    rules: list[CategoryRuleRefOut]


@router.get("/categories/{category_id}", response_model=CategoryDetailOut)
def category_detail(
    category_id: str,
    preset: str = Query(default="this_month"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    paid_by: str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """One category over the period (2d §7.2). ``category_id`` may be
    ``uncategorised``."""
    user, hh_id = auth
    if paid_by:
        _member_or_404(db, hh_id, paid_by)
    period = resolve_insight_period(preset, start_date, end_date)
    data = get_category_detail(
        db, hh_id, category_id, period["start"], period["end"], paid_by=paid_by or None
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return data


# --- Month statements (Phase B). Static paths under /statements cannot clash
# with /categories/{id} or /bills; /statements/{month} is one segment.


def _past_month(value: str, today: dt.date) -> tuple[int, int]:
    """'YYYY-MM' of a month before the current one: 400 for a bad format, 404
    for the current or a future month (no statement yet)."""
    parsed = parse_month_key(value)
    if parsed is None:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM.")
    if not is_past(*parsed, today):
        raise HTTPException(status_code=404, detail="No statement for this month yet.")
    return parsed


@router.get("/statements", response_model=StatementListOut)
def statements(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Every past month with its In, Out and Net, newest first, and the month
    waiting for review (if any). Household-wide; ignores the Insights lens."""
    user, hh_id = auth
    return build_list(db, hh_id, today=local_today())


@router.get("/statements/{month}", response_model=StatementOut)
def statement(month: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """One past month, recalculated now from the services behind each screen."""
    user, hh_id = auth
    today = local_today()
    year, mon = _past_month(month, today)
    return build_statement(db, hh_id, year, mon, today=today, viewer_id=user.id)


@router.post("/statements/{month}/review", response_model=StatementOut)
def review_statement(month: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Mark a past month as reviewed for the whole household. Idempotent: the
    first reviewer and time are kept. There is no un-review."""
    user, hh_id = auth
    today = local_today()
    year, mon = _past_month(month, today)
    first = first_data_month(db, hh_id)
    if first is not None and (year, mon) < first:
        # Nothing to review before the household's first data.
        raise HTTPException(status_code=404, detail="No statement for this month.")
    mark_reviewed(db, hh_id, month_key(year, mon), user.id)
    db.commit()
    return build_statement(db, hh_id, year, mon, today=today, viewer_id=user.id)

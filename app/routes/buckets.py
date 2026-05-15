"""
Buckets CRUD routes.
"""
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import Bucket, BucketType, BucketStatus, Household, HouseholdMember, Transaction, TransactionType
from app.services import get_bucket_balance, get_bucket_month_summary, get_bucket_settlement
from app.templates import templates

router = APIRouter(prefix="/buckets")

BUCKET_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444",
    "#f97316", "#f59e0b", "#10b981", "#06b6d4",
    "#3b82f6", "#84cc16",
]

BUCKET_ICONS = ["🪣", "🏠", "✈️", "🛒", "💡", "🎯", "🏖️", "🚗", "💰", "🎉"]


@router.get("", response_class=HTMLResponse)
def bucket_list(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    household = db.get(Household, hh_id)

    active_buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )
    archived_buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.archived)
        .order_by(Bucket.created_at)
        .all()
    )

    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]

    return templates.TemplateResponse(
        "buckets/list.html",
        {
            "request": request,
            "user": user,
            "household": household,
            "households": households,
            "active_buckets": active_buckets,
            "archived_buckets": archived_buckets,
            "bucket_types": [t.value for t in BucketType],
            "colors": BUCKET_COLORS,
            "icons": BUCKET_ICONS,
        },
    )


@router.post("", response_class=HTMLResponse)
def create_bucket(
    request: Request,
    name: str = Form(...),
    type: str = Form("custom"),
    color: str = Form("#6366f1"),
    icon: str = Form("🪣"),
    budget: str = Form(""),
    description: str = Form(""),
    show_income: str = Form(""),
    enable_settlement: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bucket = Bucket(
        household_id=hh_id,
        name=name.strip(),
        type=BucketType(type),
        color=color,
        icon=icon,
        budget=float(budget) if budget.strip() else None,
        description=description.strip() or None,
        show_income=(show_income == "on"),
        enable_settlement=(enable_settlement == "on"),
    )
    db.add(bucket)
    db.commit()
    return RedirectResponse(f"/buckets/{bucket.id}", status_code=302)


@router.get("/{bucket_id}", response_class=HTMLResponse)
def bucket_detail(
    bucket_id: str,
    request: Request,
    year: int = Query(default=None),
    month: int = Query(default=None),
    all_time: bool = Query(default=False),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    from datetime import date, timedelta
    user, hh_id = auth
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Bucket not found")

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    is_current_month = (year == today.year and month == today.month)

    # Month navigation URLs
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    prev_url = f"/buckets/{bucket_id}?year={py}&month={pm}"
    next_url = f"/buckets/{bucket_id}?year={ny}&month={nm}" if not is_current_month else None

    household = db.get(Household, hh_id)
    balance = get_bucket_balance(db, bucket_id)

    if all_time:
        transactions = (
            db.query(Transaction)
            .filter(Transaction.bucket_id == bucket_id)
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .all()
        )
        all_time_total = sum(t.amount for t in transactions if t.type == TransactionType.expense)
        month_summary = None
    else:
        start = date(year, month, 1)
        end = (
            date(year + 1, 1, 1) - timedelta(days=1)
            if month == 12
            else date(year, month + 1, 1) - timedelta(days=1)
        )
        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.bucket_id == bucket_id,
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= end,
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .all()
        )
        all_time_total = None
        month_summary = get_bucket_month_summary(db, bucket_id, year, month)

    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]

    settlement = get_bucket_settlement(db, bucket_id) if bucket.enable_settlement else []

    return templates.TemplateResponse(
        "buckets/detail.html",
        {
            "request": request,
            "user": user,
            "household": household,
            "households": households,
            "bucket": bucket,
            "balance": balance,
            "month_summary": month_summary,
            "transactions": transactions,
            "colors": BUCKET_COLORS,
            "icons": BUCKET_ICONS,
            "bucket_types": [t.value for t in BucketType],
            "year": year,
            "month": month,
            "is_current_month": is_current_month,
            "prev_url": prev_url,
            "next_url": next_url,
            "month_name": date(year, month, 1).strftime("%B %Y"),
            "all_time": all_time,
            "all_time_total": all_time_total,
            "settlement": settlement,
        },
    )


@router.post("/{bucket_id}/edit", response_class=HTMLResponse)
def edit_bucket(
    bucket_id: str,
    name: str = Form(...),
    type: str = Form("custom"),
    color: str = Form("#6366f1"),
    icon: str = Form("🪣"),
    budget: str = Form(""),
    description: str = Form(""),
    show_income: str = Form(""),
    enable_settlement: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404)

    bucket.name = name.strip()
    bucket.type = BucketType(type)
    bucket.color = color
    bucket.icon = icon
    bucket.budget = float(budget) if budget.strip() else None
    bucket.description = description.strip() or None
    bucket.show_income = (show_income == "on")
    bucket.enable_settlement = (enable_settlement == "on")
    db.commit()
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)


@router.post("/{bucket_id}/archive", response_class=HTMLResponse)
def archive_bucket(
    bucket_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404)
    bucket.status = BucketStatus.archived
    db.commit()
    return RedirectResponse("/buckets", status_code=302)


@router.post("/{bucket_id}/unarchive", response_class=HTMLResponse)
def unarchive_bucket(
    bucket_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404)
    bucket.status = BucketStatus.active
    db.commit()
    return RedirectResponse("/buckets", status_code=302)

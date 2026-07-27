"""
Buckets CRUD routes.
"""
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth, require_csrf
from app.models import Bucket, BucketType, BucketStatus, Household, HouseholdMember, Transaction, TransactionType
from app.services import (
    get_bucket_balance, get_bucket_month_summary, get_bucket_settlement,
    get_bucket_settlement_history, record_bucket_settlement, base_ctx,
)
from app.templates import templates
from app.validators import parse_amount, parse_year_month, require_member

router = APIRouter(prefix="/buckets", dependencies=[Depends(require_csrf)])

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
    ctx = base_ctx(db, user, hh_id)
    household = ctx["household"]
    households = ctx["households"]

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
        budget=parse_amount(budget, field="Budget", allow_blank=True),
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
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    from datetime import date, timedelta
    user, hh_id = auth
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Bucket not found")

    # ?month=13 or ?year=0 reached date() unchecked and raised a 500.
    parse_year_month(year, month)

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
        total_pages = 1
    else:
        PAGE_SIZE = 50
        start = date(year, month, 1)
        end = (
            date(year + 1, 1, 1) - timedelta(days=1)
            if month == 12
            else date(year, month + 1, 1) - timedelta(days=1)
        )
        base_q = (
            db.query(Transaction)
            .filter(
                Transaction.bucket_id == bucket_id,
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= end,
            )
        )
        total_count = base_q.count()
        total_pages = max(1, -(-total_count // PAGE_SIZE))  # ceiling division
        page = min(page, total_pages)
        transactions = (
            base_q
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
            .all()
        )
        all_time_total = None
        month_summary = get_bucket_month_summary(db, bucket_id, year, month)

    ctx = base_ctx(db, user, hh_id)
    households = ctx["households"]

    settlement = get_bucket_settlement(db, bucket_id) if bucket.enable_settlement else []
    settlement_history = (
        get_bucket_settlement_history(db, bucket_id) if bucket.enable_settlement else []
    )

    # Budget progress, clamped to 0..100 for the bar width. Computed here
    # because bucket.budget is a Decimal and balance["expenses"] is a float.
    budget_pct = 0.0
    if bucket.budget and float(bucket.budget) > 0:
        budget_pct = round(
            min(max(float(balance["expenses"]) / float(bucket.budget) * 100, 0), 100), 1
        )

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
            "settlement_history": settlement_history,
            "budget_pct": budget_pct,
            "page": page,
            "total_pages": total_pages,
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
    bucket.budget = parse_amount(budget, field="Budget", allow_blank=True)
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


@router.post("/{bucket_id}/settle", response_class=HTMLResponse)
def settle_bucket(
    bucket_id: str,
    request: Request,
    from_user_id: str = Form(""),
    to_user_id: str = Form(""),
    amount: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Record that a debt has been paid.

    With no arguments, clears everything currently outstanding in the bucket.
    Supplying from/to (and optionally an amount) records a single, possibly
    partial, payment instead.
    """
    user, hh_id = auth
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404)
    if not bucket.enable_settlement:
        raise HTTPException(status_code=400, detail="Settlement is not enabled for this bucket.")

    payer = require_member(db, from_user_id, hh_id) if from_user_id else None
    payee = require_member(db, to_user_id, hh_id) if to_user_id else None
    if bool(payer) != bool(payee):
        raise HTTPException(status_code=400, detail="Both payer and payee are required.")
    if payer and payer == payee:
        raise HTTPException(status_code=400, detail="Payer and payee must differ.")

    value = parse_amount(amount, field="Amount", allow_blank=True)

    created = record_bucket_settlement(
        db, bucket_id, hh_id,
        created_by=user.id,
        from_user_id=payer,
        to_user_id=payee,
        amount=float(value) if value is not None else None,
        note=note.strip() or None,
    )
    db.commit()

    if not created:
        # Nothing outstanding — treat as a no-op rather than an error.
        pass
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)

"""
Income entry routes — separate from the expense wizard.
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth, require_csrf
from app.models import (
    Transaction, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.templates import templates
from app.config import settings
from app.services import full_ctx as _full_ctx
from app.validators import parse_amount, require_category, require_member

router = APIRouter(prefix="/income", dependencies=[Depends(require_csrf)])


@router.get("/new", response_class=HTMLResponse)
def new_income(
    request: Request,
    bucket_id: str = None,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    ctx = _full_ctx(db, user, hh_id)
    household = ctx["household"]
    households = ctx["households"]
    members = ctx["members"]
    categories = ctx["categories"]

    # Only buckets with show_income=True
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active, show_income=True)
        .order_by(Bucket.created_at)
        .all()
    )

    # Validate pre-selected bucket belongs to this household and has show_income
    selected_bucket_id = ""
    if bucket_id:
        pre = db.get(Bucket, bucket_id)
        if pre and pre.household_id == hh_id and pre.show_income and pre.status == BucketStatus.active:
            selected_bucket_id = bucket_id

    return templates.TemplateResponse(
        "transactions/income_new.html",
        {
            "request": request,
            "user": user,
            "household": household,
            "households": households,
            "buckets": buckets,
            "categories": categories,
            "members": members,
            "currencies": settings.currencies,
            "today": date.today().isoformat(),
            "selected_bucket_id": selected_bucket_id,
        },
    )


@router.post("", response_class=HTMLResponse)
def create_income(
    request: Request,
    bucket_id: str = Form(...),
    transaction_date: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("EUR"),
    category_id: str = Form(""),
    received_by: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=400, detail="Invalid bucket")

    if currency not in settings.currencies:
        raise HTTPException(status_code=400, detail=f"Unsupported currency '{currency}'.")
    try:
        txn_date = date.fromisoformat(transaction_date.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Date must be a valid date (YYYY-MM-DD).")

    txn = Transaction(
        bucket_id=bucket_id,
        household_id=hh_id,
        amount=parse_amount(amount, field="Amount"),
        currency=currency,
        exchange_rate=1.0,
        type=TransactionType.income,
        paid_by=require_member(db, received_by, hh_id),
        category_id=require_category(db, category_id, hh_id),
        notes=notes.strip() or None,
        transaction_date=txn_date,
    )
    db.add(txn)
    db.commit()

    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)

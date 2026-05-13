"""
Income entry routes — separate from the expense wizard.
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import (
    Transaction, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.templates import templates

router = APIRouter(prefix="/income")


@router.get("/new", response_class=HTMLResponse)
def new_income(
    request: Request,
    bucket_id: str = None,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    # Only buckets with show_income=True
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active, show_income=True)
        .order_by(Bucket.created_at)
        .all()
    )
    categories = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .order_by(Category.is_default.desc(), Category.name)
        .all()
    )
    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .all()
    )
    household = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]

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
            "currencies": ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD", "SEK", "NOK", "DKK"],
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

    txn = Transaction(
        bucket_id=bucket_id,
        household_id=hh_id,
        amount=amount,
        currency=currency,
        exchange_rate=1.0,
        type=TransactionType.income,
        paid_by=received_by or None,
        category_id=category_id or None,
        notes=notes.strip() or None,
        transaction_date=date.fromisoformat(transaction_date),
    )
    db.add(txn)
    db.commit()

    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)

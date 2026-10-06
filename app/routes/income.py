"""
Income entry routes — separate from the expense wizard.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.clock import local_today
from app.config import settings
from app.database import get_db
from app.models import (
    Bucket,
    BucketStatus,
    TransactionType,
)
from app.schemas import TransactionCreate
from app.services import after_save_url, create_transaction
from app.services import full_ctx as _full_ctx
from app.templates import templates
from app.validators import require_income_bucket

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
            "today": local_today().isoformat(),
            "selected_bucket_id": selected_bucket_id,
        },
    )


@router.post("", response_class=HTMLResponse)
def create_income(
    request: Request,
    bucket_id: str = Form(""),
    transaction_date: str = Form(...),
    amount: str = Form(...),
    currency: str = Form("EUR"),
    exchange_rate: str = Form("1"),
    category_id: str = Form(""),
    received_by: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Save an income entry. The bucket is optional: bucket-less income always
    counts as income, a bucket must have "Track income" on."""
    user, hh_id = auth

    bucket = require_income_bucket(db, bucket_id, hh_id, not_found_status=400)
    # Same field validation as an expense (currency, rate > 0, amount, date),
    # and the same service (category and recipient must be in the household).
    try:
        data = TransactionCreate(
            bucket_id=bucket.id if bucket else None,
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            type=TransactionType.income,
            paid_by=received_by,
            category_id=category_id,
            notes=notes,
            transaction_date=transaction_date,
        )
    except ValidationError as exc:
        msg = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise HTTPException(status_code=400, detail=msg) from None

    txn = create_transaction(db, household_id=hh_id, bucket=bucket, user=user, data=data)
    return RedirectResponse(after_save_url(txn.bucket_id), status_code=302)

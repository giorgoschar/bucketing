"""
API income route — create income transactions.
Income is a thin wrapper over the transactions API with type forced to 'income'.
The bucket is optional; when given it must be active and track income.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.money import quantize
from app.models import TransactionType
from app.schemas import TransactionCreate
from app.services import create_transaction
from app.validators import require_income_bucket

router = APIRouter(prefix="/income", tags=["income"])


class IncomeIn(BaseModel):
    bucket_id:        str | None = None
    amount:           Decimal
    currency:         str        = "EUR"
    exchange_rate:    Decimal    = Decimal("1")
    category_id:      str | None = None
    notes:            str | None = None
    transaction_date: str        = ""   # ISO date; defaults to today


@router.post("", status_code=status.HTTP_201_CREATED)
def create_income(
    body: IncomeIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth

    bucket = require_income_bucket(db, body.bucket_id, hh_id)
    # The expense field checks (supported currency, rate > 0, amount, date)
    # and the shared service (category in this household) apply to income too.
    try:
        data = TransactionCreate(
            bucket_id=bucket.id if bucket else None,
            amount=body.amount,
            currency=body.currency,
            exchange_rate=body.exchange_rate,
            type=TransactionType.income,
            paid_by=user.id,
            category_id=body.category_id,
            notes=body.notes,
            transaction_date=body.transaction_date,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None

    txn = create_transaction(db, household_id=hh_id, bucket=bucket, user=user, data=data)

    return {
        "id":               txn.id,
        "bucket_id":        txn.bucket_id,
        "household_id":     txn.household_id,
        "amount":           quantize(txn.amount),
        "currency":         txn.currency,
        "exchange_rate":    float(txn.exchange_rate or 1),
        "type":             txn.type.value,
        "paid_by":          txn.paid_by,
        "category_id":      txn.category_id,
        "notes":            txn.notes,
        "transaction_date": txn.transaction_date.isoformat(),
        "created_at":       txn.created_at.isoformat() if txn.created_at else None,
    }

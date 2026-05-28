"""
API income route — create income transactions.
Income is a thin wrapper over the transactions API with type forced to 'income'.
"""
from datetime import date

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.models import Transaction, TransactionType, Bucket

router = APIRouter(prefix="/income", tags=["income"])


class IncomeIn(BaseModel):
    bucket_id:        str
    amount:           float
    currency:         str        = "EUR"
    exchange_rate:    float      = 1.0
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

    bucket = db.query(Bucket).filter_by(id=body.bucket_id, household_id=hh_id).first()
    if not bucket:
        raise Exception("Bucket not found")

    txn_date = date.fromisoformat(body.transaction_date) if body.transaction_date else date.today()

    txn = Transaction(
        bucket_id=body.bucket_id,
        household_id=hh_id,
        amount=body.amount,
        currency=body.currency,
        exchange_rate=body.exchange_rate,
        type=TransactionType.income,
        paid_by=user.id,
        category_id=body.category_id,
        notes=body.notes,
        transaction_date=txn_date,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    return {
        "id":               txn.id,
        "bucket_id":        txn.bucket_id,
        "household_id":     txn.household_id,
        "amount":           float(txn.amount),
        "currency":         txn.currency,
        "type":             txn.type.value,
        "paid_by":          txn.paid_by,
        "category_id":      txn.category_id,
        "notes":            txn.notes,
        "transaction_date": txn.transaction_date.isoformat(),
        "created_at":       txn.created_at.isoformat() if txn.created_at else None,
    }

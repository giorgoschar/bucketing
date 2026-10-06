"""
POST /api/v1/ingest/apple-pay — called by an iOS Shortcut on every Apple Pay
purchase. Auth is a personal ``pat_`` token (require_ingest_token), never a
JWT. Rate limited to 60/hour per token.

Responses:
  201 {id, amount, currency, category, bucket, ...}   new expense
  200 {..., duplicate: true}                          replay of the same purchase
  409                                                 replay of an expense since deleted
                                                      (never resurrected)
  400 bad amount · 401 bad/revoked token · 422 no bucket / bad input · 429 rate limit
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_ingest_token
from app.core.database import get_db
from app.core.ratelimit import ingest_token_key, limiter
from app.models import Bucket, Category, PersonalApiToken, Transaction
from app.services import DeletedTransactionReplay, ingest_apple_pay, notify_ingest_created

router = APIRouter(prefix="/ingest", tags=["ingest"])


class ApplePayIn(BaseModel):
    merchant: str
    # Shortcuts sends the amount as a locale string ("12,50"); numbers work too.
    amount: str | int | float | Decimal
    currency: str | None = None
    card: str | None = None
    occurred_at: str | None = None
    notes: str | None = None
    exchange_rate: str | int | float | Decimal | None = None


def _result(db: Session, txn: Transaction) -> dict:
    category = db.get(Category, txn.category_id) if txn.category_id else None
    bucket = db.get(Bucket, txn.bucket_id)
    return {
        "id": txn.id,
        "amount": txn.amount,
        "currency": txn.currency,
        "category": category.name if category else None,
        "category_id": txn.category_id,
        "bucket": bucket.name if bucket else None,
        "bucket_id": txn.bucket_id,
        "transaction_date": txn.transaction_date.isoformat(),
    }


@router.post("/apple-pay", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/hour", key_func=ingest_token_key)
def apple_pay(
    request: Request,
    response: Response,
    body: ApplePayIn,
    token: PersonalApiToken = Depends(require_ingest_token),
    db: Session = Depends(get_db),
):
    try:
        txn, created = ingest_apple_pay(
            db, token,
            merchant=body.merchant, amount=body.amount, currency=body.currency,
            card=body.card, occurred_at=body.occurred_at, notes=body.notes,
            exchange_rate=body.exchange_rate,
        )
    except DeletedTransactionReplay:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This purchase was already added and has since been deleted.",
        ) from None
    if not created:
        response.status_code = status.HTTP_200_OK
        return {**_result(db, txn), "duplicate": True}
    notify_ingest_created(db, txn)
    return _result(db, txn)

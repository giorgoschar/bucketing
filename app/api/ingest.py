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

Every attempt is recorded (app/services/ingest.py:record_ingest_attempt) —
including the ones rejected by auth, the rate limiter or body validation, in
app/main.py — and logged as one ``ingest:`` line. The Shortcut is built by
hand on the phone, so a bare "422" in the access log has to come with the
payload that caused it.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth, require_ingest_token
from app.core.database import get_db
from app.core.ratelimit import ingest_token_key, limiter
from app.models import Bucket, Category, PersonalApiToken, Transaction
from app.services import (
    DeletedTransactionReplay,
    ingest_apple_pay,
    notify_ingest_created,
    recent_ingest_attempts,
    record_ingest_attempt,
)
from app.services.ingest import NO_MERCHANT_DETAIL, PLACEHOLDER_MERCHANT

router = APIRouter(prefix="/ingest", tags=["ingest"])


def is_ingest_path(path: str) -> bool:
    """True for the ingest endpoint — used by app-wide handlers (validation,
    rate limiting) to know a request is one of ours to record."""
    return path.rstrip("/").endswith("/api/v1/ingest/apple-pay")


class ApplePayIn(BaseModel):
    """The Shortcut's JSON body, accepted as-is and coerced downstream.

    Fields are deliberately untyped: FastAPI's own checks would only answer
    "Input should be a valid string", which says nothing about *what*
    arrived. A Shortcuts row set to the whole transaction record sends a
    dictionary; a row left empty sends null. app/services/ingest.py turns
    what it can into text or a number, and refuses the rest with a message
    naming the field and the shape it got — which is what the log on
    Settings → Automations then shows.
    """

    merchant: Any = None
    amount: Any = None
    currency: Any = None
    card: Any = None
    occurred_at: Any = None
    notes: Any = None
    exchange_rate: Any = None


def raw_body(request: Request) -> str | None:
    """The request body exactly as received, decoded.

    FastAPI reads it before dependencies or validation run, so the bytes sit
    in the request's cache; reading ``await request.body()`` again here (this
    is a sync endpoint) would be a second read of a consumed stream.
    """
    body = getattr(request, "_body", None)
    if not body:
        return None
    if isinstance(body, bytes):
        return body.decode("utf-8", errors="replace")
    return str(body)


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if value and scheme.lower() == "bearer":
        return value.strip()
    return header.strip() or None


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
    attempt = {
        "db": db,
        "token": token,
        "payload": raw_body(request),
        "content_type": request.headers.get("content-type"),
        "path": request.url.path,
    }
    try:
        txn, created = ingest_apple_pay(
            db,
            token,
            merchant=body.merchant,
            amount=body.amount,
            currency=body.currency,
            card=body.card,
            occurred_at=body.occurred_at,
            notes=body.notes,
            exchange_rate=body.exchange_rate,
        )
    except DeletedTransactionReplay:
        detail = "This purchase was already added and has since been deleted."
        record_ingest_attempt(status=409, detail=detail, **attempt)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None
    except HTTPException as exc:
        record_ingest_attempt(status=exc.status_code, detail=exc.detail, **attempt)
        raise
    except Exception as exc:  # a crash is a failed attempt too — log it, re-raise
        record_ingest_attempt(
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
            **attempt,
        )
        raise
    if not created:
        response.status_code = status.HTTP_200_OK
        record_ingest_attempt(
            status=200,
            detail="duplicate — an expense for this purchase already exists",
            transaction_id=txn.id,
            **attempt,
        )
        return {**_result(db, txn), "duplicate": True}
    record_ingest_attempt(
        status=201,
        detail=NO_MERCHANT_DETAIL if txn.merchant == PLACEHOLDER_MERCHANT else "created",
        transaction_id=txn.id,
        **attempt,
    )
    notify_ingest_created(db, txn)
    return _result(db, txn)


class IngestAttemptOut(BaseModel):
    id: str
    created_at: datetime
    status: int
    # created (201) | duplicate (200) | rejected (anything else)
    outcome: Literal["created", "duplicate", "rejected"]
    detail: str | None = None
    payload: str | None = None
    token_prefix: str | None = None
    transaction_id: str | None = None


class IngestAttemptsOut(BaseModel):
    items: list[IngestAttemptOut]


def attempt_outcome(status_code: int) -> str:
    return {201: "created", 200: "duplicate"}.get(status_code, "rejected")


@router.get("/attempts", response_model=IngestAttemptsOut)
def list_attempts(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Your newest 50 ingest attempts (made with your own tokens), newest
    first. Attempts no token can be attributed to are never listed."""
    user, hh_id = auth
    rows = recent_ingest_attempts(db, hh_id, user.id, limit=50)
    return {
        "items": [
            {
                "id": a.id,
                "created_at": a.created_at,
                "status": a.status,
                "outcome": attempt_outcome(a.status),
                "detail": a.detail,
                "payload": a.payload,
                "token_prefix": a.token_prefix,
                "transaction_id": a.transaction_id,
            }
            for a in rows
        ]
    }

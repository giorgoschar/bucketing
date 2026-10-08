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
hand on the phone, so a bare "422" in the access log has to come with what
caused it: a SUMMARY of the body (type and a short preview per known key, a
count of the others), never the body itself.
"""

import re
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
from app.services.ingest import (
    CANNOT_CLASSIFY,
    NO_MERCHANT_DETAIL,
    PLACEHOLDER_MERCHANT,
    _text_value,
    classifiable,
    classify_ingested,
    ingest_choices,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


_CLASSIFY_PATH = re.compile(r"/api/v1/ingest/apple-pay/[^/]+/classify$")


def is_ingest_path(path: str) -> bool:
    """True for the ingest endpoint — used by app-wide handlers (validation,
    rate limiting) to know a request is one of ours to record."""
    path = path.rstrip("/")
    return path.endswith("/api/v1/ingest/apple-pay") or bool(_CLASSIFY_PATH.search(path))


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


def _result(db: Session, txn: Transaction, token: PersonalApiToken) -> dict:
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
        # Additive (polish S6). needs_category for every token; the name lists
        # only for a token created with the classify scope.
        **ingest_choices(db, token, txn),
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
        "token": token,
        "raw_token": bearer_token(request),
        "payload": raw_body(request),
        "content_type": request.headers.get("content-type"),
        "path": request.url.path,
    }

    def refuse(code: int, detail: str) -> None:
        # The request's transaction is decided first (nothing half-done
        # survives a refusal), then the attempt is written on its own.
        db.rollback()
        record_ingest_attempt(status=code, detail=detail, **attempt)

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
        refuse(409, detail)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None
    except HTTPException as exc:
        refuse(exc.status_code, str(exc.detail))
        raise
    except Exception as exc:  # a crash is a failed attempt too: record, re-raise
        # Fixed text: an exception message can echo the input.
        refuse(500, f"unexpected error ({type(exc).__name__})")
        raise
    if not created:
        response.status_code = status.HTTP_200_OK
        result = {**_result(db, txn, token), "duplicate": True}
        record_ingest_attempt(
            status=200,
            detail="duplicate — an expense for this purchase already exists",
            transaction_id=txn.id,
            **attempt,
        )
        return result
    notify_ingest_created(db, txn)  # commits its own work
    result = _result(db, txn, token)
    record_ingest_attempt(
        status=201,
        detail=NO_MERCHANT_DETAIL if txn.merchant == PLACEHOLDER_MERCHANT else "created",
        transaction_id=txn.id,
        **attempt,
    )
    return result


class IngestAttemptOut(BaseModel):
    id: str
    created_at: datetime
    status: int
    # created (201) | duplicate (200) | classified (200, a classify call) | rejected
    outcome: Literal["created", "duplicate", "rejected", "classified"]
    detail: str | None = None
    payload: str | None = None
    token_prefix: str | None = None
    transaction_id: str | None = None


class IngestAttemptsOut(BaseModel):
    items: list[IngestAttemptOut]


def attempt_outcome(status_code: int, detail: str | None = None) -> str:
    if status_code == 200 and (detail or "").startswith("classified:"):
        return "classified"
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
                "outcome": attempt_outcome(a.status, a.detail),
                "detail": a.detail,
                "payload": a.payload,
                "token_prefix": a.token_prefix,
                "transaction_id": a.transaction_id,
            }
            for a in rows
        ]
    }


class ClassifyIn(BaseModel):
    """Untyped on purpose, like ApplePayIn: a Choose from List result can be
    text, a list or a dictionary; the values are coerced with ``_text_value``.
    ``category``/``bucket``: an id or an exact name (trimmed, case-insensitive),
    at least one. Other keys (a ``remember`` from an older recipe) are ignored."""

    category: Any = None
    bucket: Any = None


@router.post("/apple-pay/{transaction_id}/classify")
@limiter.limit("60/hour", key_func=ingest_token_key)
def classify(
    request: Request,
    response: Response,
    transaction_id: str,
    body: ClassifyIn,
    token: PersonalApiToken = Depends(require_ingest_token),
    db: Session = Depends(get_db),
):
    """Save first, then ask: set the category and/or bucket of a purchase this
    same token added less than 15 minutes ago. Needs a token created with the
    classify scope (403 otherwise). Anything that is not the token's own,
    recent, live purchase is a bare 404. Returns the ingest result again."""
    attempt = {
        "token": token,
        "raw_token": bearer_token(request),
        "payload": raw_body(request),
        "content_type": request.headers.get("content-type"),
        "path": request.url.path,
        "transaction_id": None,
    }

    def reject(code: int, detail: str, public: str | None = None) -> HTTPException:
        db.rollback()
        record_ingest_attempt(status=code, detail=detail, **attempt)
        return HTTPException(status_code=code, detail=public) if public else HTTPException(code)

    if not token.can_classify:
        raise reject(403, CANNOT_CLASSIFY, CANNOT_CLASSIFY)
    txn = classifiable(db, token, transaction_id)
    if txn is None:
        raise reject(
            404,
            "classify: no such purchase for this token (not found, not made by this token, "
            "older than 15 minutes, or deleted)",
        )
    attempt["transaction_id"] = txn.id
    category = (_text_value(body.category) or "").strip()
    bucket = (_text_value(body.bucket) or "").strip()
    if not category and not bucket:
        raise reject(422, "classify: send a category or a bucket", "Send a category or a bucket.")
    try:
        txn, chosen = classify_ingested(
            db, token, txn, category=category or None, bucket=bucket or None
        )
    except HTTPException as exc:
        db.rollback()
        raise reject(exc.status_code, str(exc.detail), exc.detail) from None
    detail = "classified: " + " / ".join(c[:80] for c in chosen)
    result = _result(db, txn, token)
    record_ingest_attempt(status=200, detail=detail, **attempt)
    return result

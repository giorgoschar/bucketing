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

Every authenticated request is kept in the token owner's attempts log (their
newest 50, GET /api/v1/ingest/attempts) with the reason for a rejection, and
every rejection is logged at WARNING: a Shortcut cannot be debugged from a
bare "422". The handler therefore reads and validates the body itself, after
the token is known.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth, require_ingest_token
from app.core.database import get_db
from app.core.ratelimit import ingest_token_key, limiter
from app.models import Bucket, Category, PersonalApiToken, Transaction
from app.services import DeletedTransactionReplay, ingest_apple_pay, notify_ingest_created
from app.services import ingest as ingest_svc

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

    @field_validator("*", mode="before")
    @classmethod
    def _unwrap(cls, v):
        # Shortcuts actions often hand over a list ("Get Numbers from Input"
        # gives [12.5], "Get Text" ["Sklavenitis"]): its first element is meant.
        return v[0] if isinstance(v, list) and v else v


class IngestAttemptOut(BaseModel):
    id: str
    created_at: datetime  # naive UTC
    status_code: int
    outcome: Literal["created", "duplicate", "rejected"]
    reason: str | None  # why it was rejected
    merchant: str | None  # the start of what was sent (80 characters)
    amount_raw: str | None  # the amount exactly as sent (40 characters)
    transaction_id: str | None
    token_name: str | None


class IngestAttemptsOut(BaseModel):
    items: list[IngestAttemptOut]


NOT_AN_OBJECT = "Body must be JSON with merchant and amount"
# A real payload is a few hundred bytes; a bigger body is refused unparsed.
MAX_BODY_BYTES = 16 * 1024


async def _raw_body(request: Request) -> bytes:
    return await request.body()


def _validation_detail(exc: ValidationError) -> list[dict]:
    """The ``detail`` list FastAPI itself sends for a body that fails
    validation (``loc`` starts at "body")."""
    out = []
    for e in exc.errors(include_url=False):
        item = {"type": e["type"], "loc": ["body", *e["loc"]], "msg": e["msg"], "input": e["input"]}
        if e.get("ctx"):
            item["ctx"] = {
                k: str(v) if isinstance(v, Exception) else v for k, v in e["ctx"].items()
            }
        out.append(item)
    return jsonable_encoder(out)


def _reason(detail) -> str:
    """One line for the log from an error ``detail`` (a string, or FastAPI's
    list): "merchant: Field required"."""
    if isinstance(detail, list):
        parts = []
        for e in detail:
            # Only a field of ours is named: a key the client made up is not.
            where = ".".join(str(p) for p in e.get("loc", [])[1:2] if p in ApplePayIn.model_fields)
            parts.append(f"{where}: {e.get('msg')}" if where else str(e.get("msg")))
        return "; ".join(parts)
    return str(detail)


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


@router.post(
    "/apple-pay",
    status_code=status.HTTP_201_CREATED,
    # The handler reads the body itself (see the module docstring); this
    # keeps it documented.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": ApplePayIn.model_json_schema()}},
        }
    },
)
@limiter.limit("60/hour", key_func=ingest_token_key)
def apple_pay(
    request: Request,
    response: Response,
    token: PersonalApiToken = Depends(require_ingest_token),
    raw: bytes = Depends(_raw_body),
    db: Session = Depends(get_db),
):
    # Plain values: the session is rolled back before an attempt is recorded.
    who = {"household_id": token.household_id, "token_id": token.id, "user_id": token.user_id}
    payload = None
    if len(raw) <= MAX_BODY_BYTES:
        try:
            payload = json.loads(raw)
        except ValueError:  # not JSON (or not UTF-8)
            payload = None
    merchant, amount_raw = ingest_svc.attempt_fields(payload)

    def reject(status_code: int, detail) -> HTTPException:
        reason = _reason(detail)
        ingest_svc.log_rejection(status_code, reason, payload)
        ingest_svc.record_attempt(
            db,
            **who,
            status_code=status_code,
            outcome=ingest_svc.REJECTED,
            reason=reason,
            merchant=merchant,
            amount_raw=amount_raw,
        )
        return HTTPException(status_code=status_code, detail=detail)

    if len(raw) > MAX_BODY_BYTES:
        raise reject(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Body is too large")
    if not isinstance(payload, dict):
        raise reject(422, NOT_AN_OBJECT)
    try:
        body = ApplePayIn.model_validate(payload)
    except ValidationError as exc:
        raise reject(422, _validation_detail(exc)) from None
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
        raise reject(
            status.HTTP_409_CONFLICT,
            "This purchase was already added and has since been deleted.",
        ) from None
    except HTTPException as exc:
        raise reject(exc.status_code, exc.detail) from None
    result = _result(db, txn)
    ingest_svc.record_attempt(
        db,
        **who,
        status_code=201 if created else 200,
        outcome=ingest_svc.CREATED if created else ingest_svc.DUPLICATE,
        merchant=merchant,
        amount_raw=amount_raw,
        transaction_id=txn.id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        return {**result, "duplicate": True}
    notify_ingest_created(db, db.get(Transaction, result["id"]))
    return result


@router.get("/attempts", response_model=IngestAttemptsOut)
def attempts(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Your last 50 Apple Pay ingest requests in this household (the ones
    your own tokens sent), newest first, with the reason for each rejection.
    Tokens are personal: no role sees another member's."""
    user, hh_id = auth
    return {
        "items": [
            {
                "id": a.id,
                "created_at": a.created_at,
                "status_code": a.status_code,
                "outcome": a.outcome,
                "reason": a.reason,
                "merchant": a.merchant,
                "amount_raw": a.amount_raw,
                "transaction_id": a.transaction_id,
                "token_name": a.token.name if a.token else None,
            }
            for a in ingest_svc.list_attempts(db, hh_id, user.id)
        ]
    }

"""Apple Pay ingest: turn an iOS Shortcut payload into an expense.

The Shortcut fires once per Wallet transaction but iOS is known to retry or
double-fire it, so every payload maps to a deterministic ``client_id``
(:func:`ingest_client_id`) and the existing unique
``(household_id, client_id)`` makes replays idempotent.

The body is built by hand on the phone, so nothing about it is guaranteed:
values arrive as text, as numbers, or — when a row picks the whole
transaction record instead of one field — as dictionaries. :func:`ingest_apple_pay`
coerces what it can and, whatever it cannot, records through
:func:`record_ingest_attempt` so the miss can be read back on
Settings → Automations instead of guessed at from a bare "422".
"""

import hashlib
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.clock import local_today, tz, utcnow
from app.core.money import quantize
from app.models import (
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    Household,
    IngestAttempt,
    NotificationType,
    PaymentMethod,
    PersonalApiToken,
    Transaction,
)
from app.schemas import TransactionCreate
from app.services.category_rules import resolve_category
from app.services.personal_tokens import (
    DISPLAY_PREFIX_LEN,
    active_household_bucket,
    hash_personal_token,
)
from app.services.transactions import DuplicateTransaction, create_transaction
from app.validators import parse_amount

logger = logging.getLogger(__name__)

# How many attempts each scope keeps: the table is a debugging tail, not a
# ledger, and it is written on every purchase (and every failed attempt).
KEEP_PER_SCOPE = 100
# Cap on attempts no token can be attributed to. An attacker varying token
# prefixes must not be able to grow the table without bound.
KEEP_UNATTRIBUTED = 200
MAX_PAYLOAD_CHARS = 2000
MAX_LOG_PAYLOAD_CHARS = 600

# Non-numeric characters stripped from a Shortcut amount before parsing:
# currency symbols, codes and separators ("€12,50", "12,50 EUR", "1 234,50").
_NON_NUMERIC = re.compile(r"[^0-9.,-]")
# "1.234.567" — a dot-grouped integer with no decimal part. Requires a second
# group so "12.500" keeps parse_amount's reading (12.5, not 12500).
_DOT_GROUPED = re.compile(r"^\d{1,3}(?:\.\d{3}){2,}$")
# Keys a "name" might hide under when a whole record was sent instead of a
# field. Case variants cover the Wallet record's own key spellings.
_NAME_KEYS = (
    "name",
    "Name",
    "merchant",
    "Merchant",
    "title",
    "label",
    "value",
    "Value",
    "description",
)
_AMOUNT_KEYS = (
    "value",
    "amount",
    "Value",
    "Amount",
    "number",
    "decimalValue",
    "numericValue",
)


# ---------------------------------------------------------------------------
# Payload coercion — the Shortcut is built by hand, so be liberal in what
# is accepted and precise about what is refused.
# ---------------------------------------------------------------------------


def _text_value(value) -> str | None:
    """The text inside a Shortcut value, or None when there is none.

    A Shortcuts row can resolve to the whole record ("Card or Pass" is a
    dictionary) rather than one field. Recurse into dictionaries and lists
    looking for a name-ish key; anything unrecognised becomes None instead of
    a 422 the person reading the log cannot map back to their Shortcut.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, dict):
        for key in _NAME_KEYS:
            if key in value:
                found = _text_value(value[key])
                if found:
                    return found
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _text_value(item)
            if found:
                return found
        return None
    return None


def _field_text(value, *, field: str, required: bool = False) -> str | None:
    """``_text_value`` with a message that names the field when it fails."""
    text = _text_value(value)
    if text is None and value is not None and required:
        raise HTTPException(
            status_code=422,
            detail=f"{field} could not be read: send {field} as text, "
            "not the whole transaction record.",
        )
    return text


def normalise_amount(raw) -> str:
    """Shortcut amount → the plain decimal string :func:`parse_amount` wants.

    Handles the shapes a phone sends: numbers as-is, and strings carrying
    currency symbols/codes or locale separators — "€12,50", "12,50 EUR",
    "1.234,50", "1,234.56", "1 234,50". When both separators appear the one
    written last is the decimal mark (EU "1.234,50" vs US "1,234.56").
    """
    if not isinstance(raw, str):
        return str(raw)
    cleaned = _NON_NUMERIC.sub("", raw)
    if not cleaned:
        # Nothing numeric at all ("abc", "EUR") — hand the original to
        # parse_amount so the message stays the standard one.
        return raw
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif _DOT_GROUPED.match(cleaned):
        cleaned = cleaned.replace(".", "")
    else:
        cleaned = cleaned.replace(",", ".")
    return cleaned


def coerce_amount(raw) -> Decimal:
    """Any Shortcut amount → a validated Decimal, or HTTP 400.

    Accepts numbers, locale strings and — when a row picked the whole record —
    a dictionary holding the number under a plausible key. The message says
    what came in, because that is exactly what the reader is missing.
    """
    if raw is None:
        raise HTTPException(status_code=400, detail="Amount is required.")
    if isinstance(raw, dict):
        for key in _AMOUNT_KEYS:
            if key in raw:
                return coerce_amount(raw[key])
        if len(raw) == 1:
            return coerce_amount(next(iter(raw.values())))
        raise HTTPException(
            status_code=400,
            detail="Amount must be a number: the Shortcut sent a record "
            f"(keys: {', '.join(list(raw)[:6])}) — pick the Amount field, not the transaction.",
        )
    if isinstance(raw, (list, tuple)):
        if len(raw) == 1:
            return coerce_amount(raw[0])
        raise HTTPException(status_code=400, detail="Amount must be a single number.")
    if isinstance(raw, bool):
        raise HTTPException(status_code=400, detail="Amount must be a number.")
    return parse_amount(normalise_amount(raw))


# ---------------------------------------------------------------------------
# Attempt log
# ---------------------------------------------------------------------------


def token_from_raw(db: Session, raw: str | None) -> PersonalApiToken | None:
    """The token row a plaintext ``pat_`` value belongs to (revoked included),
    or None when it matches nothing. Lookup is by stored hash."""
    if not raw or not raw.startswith("pat_"):
        return None
    return db.query(PersonalApiToken).filter_by(token_hash=hash_personal_token(raw)).first()


def _payload_text(payload) -> str | None:
    if payload is None:
        return None
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    elif not isinstance(payload, str):
        from fastapi.encoders import jsonable_encoder

        try:
            payload = str(jsonable_encoder(payload))
        except Exception:  # pragma: no cover - a log line never breaks a payment
            payload = repr(payload)
    payload = payload.strip()
    return payload[:MAX_PAYLOAD_CHARS] or None


def _keep_newest(db: Session, scope, count: int) -> None:
    """Delete everything but the ``count`` newest rows matching ``scope``."""
    keep = [
        r[0]
        for r in db.query(IngestAttempt.id)
        .filter(scope)
        .order_by(IngestAttempt.created_at.desc(), IngestAttempt.id.desc())
        .limit(count)
        .all()
    ]
    if not keep:  # pragma: no cover - the row just inserted is always in scope
        return
    db.query(IngestAttempt).filter(scope, IngestAttempt.id.notin_(keep)).delete(
        synchronize_session=False
    )


def _prune(db: Session, *, household_id: str | None, token_prefix: str | None) -> None:
    """Keep the near-term history of this attempt's scope (and the global cap
    on unattributed rows)."""
    if household_id:
        _keep_newest(db, IngestAttempt.household_id == household_id, KEEP_PER_SCOPE)
    else:
        if token_prefix:
            _keep_newest(
                db,
                and_(
                    IngestAttempt.household_id.is_(None),
                    IngestAttempt.token_prefix == token_prefix,
                ),
                KEEP_PER_SCOPE,
            )
        _keep_newest(db, IngestAttempt.household_id.is_(None), KEEP_UNATTRIBUTED)


def record_ingest_attempt(
    *,
    status: int,
    detail: str | None = None,
    payload=None,
    content_type: str | None = None,
    raw_token: str | None = None,
    token: PersonalApiToken | None = None,
    transaction_id: str | None = None,
    path: str = "/api/v1/ingest/apple-pay",
    db: Session | None = None,
) -> None:
    """Persist one attempt and log one line. Never raises.

    ``db`` is the request's session when the caller has one (same SQLite
    connection, so no lock fight with its open reads); exception handlers pass
    none and get their own session. A failure to record is logged and
    swallowed: the diagnostic must never break the payment it describes.
    """
    own_session = db is None
    session = db
    prefix = None
    try:
        if session is None:
            from app.core.database import SessionLocal

            session = SessionLocal()
        if token is None and raw_token:
            token = token_from_raw(session, raw_token)
        if token is not None:
            prefix = token.prefix
        elif raw_token and raw_token.startswith("pat_"):
            prefix = raw_token[:DISPLAY_PREFIX_LEN]
        payload_text = _payload_text(payload)
        if detail is not None and not isinstance(detail, str):
            detail = str(detail)
        row = IngestAttempt(
            household_id=token.household_id if token is not None else None,
            token_id=token.id if token is not None else None,
            token_prefix=prefix,
            status=int(status),
            detail=(detail or "").strip()[:500] or None,
            payload=payload_text,
            content_type=(content_type or "").strip()[:100] or None,
            transaction_id=transaction_id,
        )
        session.add(row)
        session.flush()
        _prune(session, household_id=row.household_id, token_prefix=prefix)
        session.commit()
    except Exception:
        try:
            if session is not None:
                session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        logger.exception("ingest: could not record the attempt (status %s)", status)
        return
    finally:
        if own_session and session is not None:
            session.close()

    level = logging.INFO if status < 400 else logging.WARNING
    logger.log(
        level,
        "ingest: %s → %s%s | token=%s | type=%s | payload=%s",
        path,
        status,
        f" {detail}" if detail else "",
        prefix or "-",
        content_type or "-",
        (payload_text or "-")[:MAX_LOG_PAYLOAD_CHARS],
    )


def recent_ingest_attempts(
    db: Session, household_id: str, token_prefixes: tuple[str, ...] = (), limit: int = 20
) -> list[IngestAttempt]:
    """Newest attempts this household may see: its own, plus any whose token
    prefix matches one of its tokens — so an attempt made with a revoked or
    mistyped token still appears next to the token it resembles."""
    conds = [IngestAttempt.household_id == household_id]
    prefixes = [p for p in token_prefixes if p]
    if prefixes:
        conds.append(IngestAttempt.token_prefix.in_(prefixes))
    return (
        db.query(IngestAttempt)
        .filter(or_(*conds))
        .order_by(IngestAttempt.created_at.desc(), IngestAttempt.id.desc())
        .limit(limit)
        .all()
    )


def parse_occurred_at(raw) -> datetime | None:
    """ISO-8601 → aware datetime, or None when absent/unparseable.

    A naive value is read as household-local time. Unparseable input is
    ignored rather than rejected: losing the expense because the Shortcut
    sent an odd date format is worse than dating it "now".
    """
    if not raw or not str(raw).strip():
        return None
    try:
        moment = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        logger.info("ingest: ignoring unparseable occurred_at %r", str(raw)[:80])
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz())
    return moment


def ingest_client_id(
    token_id: str, merchant: str, amount: Decimal, occurred_at: datetime | None
) -> str:
    """Deterministic idempotency key for one Apple Pay purchase.

    Normalised so that equivalent replays collide: the merchant is
    whitespace-collapsed and casefolded (the stored merchant keeps its
    casing), the amount is quantized to
    2dp ("12,50", "12.5" and 12.5 all become "12.50") and the moment is
    converted to UTC and floored to the minute (second-level jitter between
    retries is ignored). ``occurred_at`` absent → the current minute.
    """
    moment = (occurred_at or utcnow()).astimezone(UTC).replace(second=0, microsecond=0)
    merchant_key = " ".join(merchant.split()).casefold()
    key = f"{token_id}|{merchant_key}|{quantize(amount)}|{moment.strftime('%Y-%m-%dT%H:%MZ')}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def resolve_ingest_bucket(db: Session, token: PersonalApiToken) -> Bucket:
    """The token's default bucket if still active, else the household's first
    active day-to-day bucket, else HTTP 422."""
    bucket = active_household_bucket(db, token.household_id, token.default_bucket_id)
    if bucket is None:
        bucket = (
            db.query(Bucket)
            .filter(
                Bucket.household_id == token.household_id,
                Bucket.status == BucketStatus.active,
                Bucket.type == BucketType.day2day,
            )
            .order_by(Bucket.created_at, Bucket.id)
            .first()
        )
    if bucket is None:
        raise HTTPException(
            status_code=422,
            detail="No bucket to add this expense to: set a default bucket on the "
            "token or create an active day-to-day bucket.",
        )
    return bucket


def _notes(card: str | None, extra: str | None) -> str | None:
    parts = [f"Apple Pay · {card}"] if card else []
    if extra:
        parts.append(extra)
    return " · ".join(parts) or None


def ingest_apple_pay(
    db: Session,
    token: PersonalApiToken,
    *,
    merchant,
    amount,
    currency=None,
    card=None,
    occurred_at=None,
    notes=None,
    exchange_rate=None,
) -> tuple[Transaction, bool]:
    """Create (or find, on replay) the expense. Returns (transaction, created).

    Every field is coerced rather than trusted: the Shortcut may send text,
    numbers or a whole record. Raises HTTPException 400 (missing/unreadable
    amount), 422 (blank merchant, unreadable currency, bad currency,
    no bucket) and propagates DeletedTransactionReplay (the caller maps it to
    409: a deleted expense is never resurrected by a retry).
    """
    merchant = " ".join((_field_text(merchant, field="Merchant", required=True) or "").split())
    if not merchant:
        raise HTTPException(status_code=422, detail="Merchant is required.")
    if currency is not None:
        currency = _text_value(currency)
        if currency is None:
            raise HTTPException(
                status_code=422, detail="Currency could not be read: send a code like EUR."
            )
    raw_card = card
    card = _text_value(card)
    if raw_card is not None and card is None:
        logger.info(
            "ingest: the card value (%r) is not text — leaving it out of the notes", raw_card
        )
    notes = _text_value(notes)
    value = coerce_amount(amount)
    moment = parse_occurred_at(occurred_at)
    household = db.get(Household, token.household_id)
    bucket = resolve_ingest_bucket(db, token)
    # Rules only: the built-in guess fuzzy-matches a category *hint*, and
    # merchant names ("Corner Kiosk" ~ "Groceries") give false positives.
    category_id = resolve_category(db, token.household_id, merchant=merchant, hint=None)

    fields = {
        "bucket_id": bucket.id,
        "amount": value,
        "currency": (currency or "").strip().upper() or household.default_currency or "EUR",
        "paid_by": token.user_id,
        "category_id": category_id,
        "notes": _notes((card or "").strip() or None, (notes or "").strip() or None),
        "transaction_date": moment.astimezone(tz()).date() if moment else local_today(),
        "client_id": ingest_client_id(token.id, merchant, value, moment),
        "payment_method": PaymentMethod.apple_pay.value,
        "merchant": merchant,
    }
    if exchange_rate is not None:
        fields["exchange_rate"] = exchange_rate
    try:
        data = TransactionCreate(**fields)
    except ValidationError as exc:
        msg = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
        raise HTTPException(status_code=422, detail=msg) from None

    user = token.user
    try:
        txn = create_transaction(
            db, household_id=token.household_id, bucket=bucket, user=user, data=data
        )
    except DuplicateTransaction as dup:
        return dup.existing, False
    return txn, True


def notify_ingest_created(db: Session, txn: Transaction) -> None:
    """In-app + push notification so the payer can re-categorise.

    Deduped by transaction id; failures never break the ingest response.
    """
    from app.services.notifications import create_notification, send_push_for_notification
    from app.templates import format_currency

    category = db.get(Category, txn.category_id) if txn.category_id else None
    title = f"Apple Pay: {format_currency(txn.amount, txn.currency)} at {txn.merchant}"
    if category:
        title += f" → {category.name}"
    try:
        notif = create_notification(
            db,
            household_id=txn.household_id,
            user_id=txn.paid_by,
            type=NotificationType.ingest_created,
            title=title[:200],
            body="Tap to check the category or bucket.",
            link=f"/transactions/{txn.id}/edit",
            dedupe_key=f"ingest:{txn.id}",
        )
        db.commit()
        send_push_for_notification(db, notif)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("ingest: notification for transaction %s failed", txn.id)

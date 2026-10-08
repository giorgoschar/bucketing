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
import sys
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import unquote

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_
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
# Longest amount string looked at before any regex work (R2d). Nothing a phone
# sends for a price comes close; longer is refused, not parsed.
MAX_AMOUNT_CHARS = 64
# Raw bodies are cut to this before redaction regexes run, so work stays bounded.
_REDACT_INPUT_CHARS = 20_000
REDACTED_TOKEN = "pat_…redacted"
TOKEN_PREFIX_RAW = "pat_"

# A personal token pasted anywhere in what was sent (R2a).
_TOKEN_RE = re.compile(r"pat_[A-Za-z0-9_-]+")
# A body field named authorization / token, quoted JSON (also truncated JSON)
# or form-encoded; the whole value goes, whatever it is.
_SECRET_FIELD_JSON = re.compile(
    r'("(?:authorization|token)"\s*:\s*)("(?:[^"\\]|\\.)*(?:"|$)|[^,}\]\s]+)', re.IGNORECASE
)
_SECRET_FIELD_FORM = re.compile(r"((?:^|[&?\s])(?:authorization|token)=)[^&\s]*", re.IGNORECASE)
# Anything that can end or fake a log line: C0 controls, DEL, NEL, LS, PS.
_LOG_UNSAFE = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029]")


_BEARER_RE = re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_TRAILING_PARTIAL = re.compile(r"pat_[A-Za-z0-9_-]*$")
_WINDOW = 12
WITHHELD = "[payload withheld: it contained the token]"


def _normalise(text: str) -> str:
    """A copy for detection: JSON ``\\uXXXX`` and percent escapes decoded
    (twice, for double encoding)."""
    for _ in range(2):
        text = _JSON_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text).replace("\\/", "/")
        text = unquote(text)
    return text


def _redact_plain(text: str) -> str:
    text = _TOKEN_RE.sub(REDACTED_TOKEN, text)
    text = _BEARER_RE.sub("Bearer …redacted", text)
    text = _SECRET_FIELD_JSON.sub(lambda m: f'{m.group(1)}"…redacted"', text)
    return _SECRET_FIELD_FORM.sub(lambda m: f"{m.group(1)}…redacted", text)


def _mentions_secret(text: str) -> bool:
    return bool(
        _TOKEN_RE.search(text)
        or _BEARER_RE.search(text)
        or _SECRET_FIELD_JSON.search(text)
        or _SECRET_FIELD_FORM.search(text)
    )


def _leaks(text: str, secret: str | None) -> bool:
    """True when ``text`` holds the real token or any 12+ character run of
    its secret part, also with separators (whitespace, quotes, ``+``) between
    the characters."""
    if not secret:
        return False
    body = secret[len(TOKEN_PREFIX_RAW) :] if secret.startswith(TOKEN_PREFIX_RAW) else secret
    if len(body) < _WINDOW:
        return secret in text
    windows = [body[i : i + _WINDOW] for i in range(len(body) - _WINDOW + 1)]
    variants = (text, _normalise(text))
    for variant in variants:
        collapsed = re.sub(r"[^A-Za-z0-9_-]", "", variant)
        if any(w in variant or w in collapsed for w in windows):
            return True
    return False


def scrub(text: str | None, secret: str | None = None, *, label: str = "payload") -> str | None:
    """The one place stored and logged text is cleaned of credentials.

    Works on the final text, whatever produced it (bytes, str, a dict run
    through the encoder, a repr, form data, broken JSON): tokens, ``Bearer``
    values and ``authorization``/``token`` fields are replaced, also when
    hidden behind JSON ``\\u`` escapes or percent-encoding (then the decoded,
    redacted text is kept instead of the original). The caller's own token,
    when known, is a last guard: any trace of it left makes the whole text
    withheld. Redaction runs before any truncation.
    """
    if not text:
        return text
    text = text[:_REDACT_INPUT_CHARS]
    normalised = _normalise(text)
    source = normalised if normalised != text and _mentions_secret(normalised) else text
    out = _redact_plain(source)
    if _leaks(out, secret):
        return WITHHELD if label == "payload" else f"[{label} withheld: it contained the token]"
    return out


def redact_secrets(text: str | None) -> str | None:
    return scrub(text)


def log_safe(value, limit: int | None = None, secret: str | None = None) -> str:
    """Request-derived text made safe for one log line: control characters
    become visible escapes (``\\n``, ``\\x1b``), then the length cap applies."""
    text = scrub(str(value), secret, label="text") if value is not None else ""
    text = _LOG_UNSAFE.sub(lambda m: m.group().encode("unicode_escape").decode(), text)
    return text[:limit] if limit else text


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


def _text_value(value, _depth: int = 0) -> str | None:
    """The text inside a Shortcut value, or None when there is none.

    A Shortcuts row can resolve to the whole record ("Card or Pass" is a
    dictionary) rather than one field. Recurse into dictionaries and lists
    looking for a name-ish key; anything unrecognised becomes None instead of
    a 422 the person reading the log cannot map back to their Shortcut.
    """
    if value is None or isinstance(value, bool) or _depth > 6:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, dict):
        for key in _NAME_KEYS:
            if key in value:
                found = _text_value(value[key], _depth + 1)
                if found:
                    return found
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _text_value(item, _depth + 1)
            if found:
                return found
        return None
    return None


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


def coerce_amount(raw, _depth: int = 0) -> Decimal:
    """Any Shortcut amount → a validated Decimal, or HTTP 400.

    Accepts numbers, locale strings and — when a row picked the whole record —
    a dictionary holding the number under a plausible key. The message says
    what came in, because that is exactly what the reader is missing.
    """
    if raw is None:
        raise HTTPException(status_code=400, detail="Amount is required.")
    if _depth > 6:
        raise HTTPException(status_code=400, detail="Amount must be a number.")
    if isinstance(raw, str) and len(raw) > MAX_AMOUNT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Amount is too long ({len(raw)} characters; at most {MAX_AMOUNT_CHARS}).",
        )
    if isinstance(raw, dict):
        for key in _AMOUNT_KEYS:
            if key in raw:
                return coerce_amount(raw[key], _depth + 1)
        if len(raw) == 1:
            return coerce_amount(next(iter(raw.values())), _depth + 1)
        raise HTTPException(
            status_code=400,
            detail="Amount must be a number: the Shortcut sent a record "
            f"(keys: {', '.join(list(raw)[:6])}) — pick the Amount field, not the transaction.",
        )
    if isinstance(raw, (list, tuple)):
        if len(raw) == 1:
            return coerce_amount(raw[0], _depth + 1)
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
    return payload.strip() or None


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
        # The last step before anything is stored or logged: credentials out
        # of the final text, then the length cap (never the other way round).
        secret = raw_token or None
        payload_text = scrub(_payload_text(payload), secret)
        if payload_text:
            payload_text = _TRAILING_PARTIAL.sub("", payload_text[:MAX_PAYLOAD_CHARS]) or None
        if detail is not None and not isinstance(detail, str):
            detail = str(detail)
        detail = scrub(detail, secret, label="detail")
        content_type = scrub(content_type, secret, label="content type")
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
        # No traceback: a database error can echo the bound parameters.
        logger.error(
            "ingest: could not record the attempt (status %s): %s",
            int(status),
            sys.exc_info()[0].__name__,
        )
        return
    finally:
        if own_session and session is not None:
            session.close()

    level = logging.INFO if status < 400 else logging.WARNING
    logger.log(
        level,
        "ingest: %s → %s%s | token=%s | type=%s | payload=%s",
        log_safe(path, 200, secret),
        int(status),
        f" {log_safe(detail, 500, secret)}" if detail else "",
        log_safe(prefix, 12, secret) or "-",
        log_safe(content_type, 100, secret) or "-",
        log_safe(payload_text, MAX_LOG_PAYLOAD_CHARS, secret) or "-",
    )


def recent_ingest_attempts(
    db: Session, household_id: str, user_id: str, limit: int = 20
) -> list[IngestAttempt]:
    """Newest attempts made with ``user_id``'s own tokens in this household.

    Personal, like the token: another member of the household sees none of
    them, and an attempt no token can be attributed to (null household or
    token) is shown to nobody in-app: it exists in the server log only.
    """
    return (
        db.query(IngestAttempt)
        .join(PersonalApiToken, PersonalApiToken.id == IngestAttempt.token_id)
        .filter(
            IngestAttempt.household_id == household_id,
            PersonalApiToken.user_id == user_id,
            PersonalApiToken.household_id == household_id,
        )
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
        logger.info("ingest: ignoring unparseable occurred_at %s", log_safe(repr(str(raw)[:80])))
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


PLACEHOLDER_MERCHANT = "Apple Pay purchase"
NO_MERCHANT_NOTE = "Merchant not received from the Shortcut"
NO_MERCHANT_DETAIL = "created without a merchant — the Shortcut sent no merchant"


def _notes(card: str | None, extra: str | None, *, no_merchant: bool = False) -> str | None:
    parts = [NO_MERCHANT_NOTE] if no_merchant else []
    if card:
        parts.append(f"Apple Pay · {card}")
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
    amount), 422 (unreadable currency, bad currency,
    no bucket) and propagates DeletedTransactionReplay (the caller maps it to
    409: a deleted expense is never resurrected by a retry).
    """
    # A missing, blank or unreadable merchant must not lose a real purchase:
    # the amount decides (below); the merchant falls back to a placeholder.
    merchant = " ".join((_text_value(merchant) or "").split())
    no_merchant = not merchant
    value = coerce_amount(amount)
    if no_merchant:
        merchant = PLACEHOLDER_MERCHANT
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
            "ingest: the card value (%s) is not text — leaving it out of the notes",
            log_safe(repr(raw_card), 200),
        )
    notes = _text_value(notes)
    moment = parse_occurred_at(occurred_at)
    household = db.get(Household, token.household_id)
    bucket = resolve_ingest_bucket(db, token)
    # Rules only: the built-in guess fuzzy-matches a category *hint*, and
    # merchant names ("Corner Kiosk" ~ "Groceries") give false positives.
    category_id = (
        None
        if no_merchant
        else resolve_category(db, token.household_id, merchant=merchant, hint=None)
    )

    fields = {
        "bucket_id": bucket.id,
        "amount": value,
        "currency": (currency or "").strip().upper() or household.default_currency or "EUR",
        "paid_by": token.user_id,
        "category_id": category_id,
        "notes": _notes(
            (card or "").strip() or None, (notes or "").strip() or None, no_merchant=no_merchant
        ),
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

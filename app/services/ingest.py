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
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import unquote

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.clock import local_today, tz, utcnow, utcnow_naive
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
from app.services.transactions import DuplicateTransaction, create_transaction, update_transaction
from app.validators import parse_amount

logger = logging.getLogger(__name__)

# How many attempts each scope keeps: the table is a debugging tail, not a
# ledger, and it is written on every purchase (and every failed attempt).
KEEP_PER_SCOPE = 100
# Cap on attempts no token can be attributed to. An attacker varying token
# prefixes must not be able to grow the table without bound.
KEEP_UNATTRIBUTED = 200
# Longest amount string looked at before any regex work (R2d). Nothing a phone
# sends for a price comes close; longer is refused, not parsed.
MAX_AMOUNT_CHARS = 64

# ---------------------------------------------------------------------------
# What an attempt keeps of a request
#
# The raw body is NEVER stored or logged: it is where a pasted token, a card
# number or an injected log line would arrive. Instead the attempt keeps a
# summary built from the parsed body: for each known key its type and a short
# preview of scalar values, a count of the unknown keys, nothing else. The one
# guard left runs over those short strings we built ourselves.
# ---------------------------------------------------------------------------

KNOWN_KEYS = ("merchant", "amount", "currency", "card", "occurred_at", "notes", "exchange_rate")
CLASSIFY_KEYS = ("category", "bucket")
PREVIEW_CHARS = 40
MAX_NAMES = 6
NAME_CHARS = 20
MAX_PARSED_BODY_CHARS = 1_000_000
WITHHELD = "[withheld]"
_GUARD_WINDOW = 8
# Anything that can end or fake a log line: C0 controls, DEL, NEL, LS, PS.
_LOG_UNSAFE = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029]")
_TOKEN_WORDS = re.compile(r"pat_|bearer", re.IGNORECASE)
_PREFIX_OK = re.compile(r"pat_[A-Za-z0-9_-]{0,8}")
_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9_ -]")
_CT_UNSAFE = re.compile(r"[^A-Za-z0-9/+.;=_ -]")


def _clean(text, limit: int) -> str:
    """Control characters out, then the length cap."""
    return _LOG_UNSAFE.sub("", str(text))[:limit]


def guard(text: str, secret: str | None = None) -> str:
    """``text`` itself, or ``[withheld]`` when it looks like or holds a
    credential: ``pat_`` or ``bearer`` anywhere (also percent-encoded or with
    separators between the characters), or any 8+ character piece of the
    authenticated token's plaintext when that is known. Only ever applied to
    short strings built here, never to a raw body."""
    if not text:
        return text
    pieces = (
        [secret[i : i + _GUARD_WINDOW] for i in range(len(secret) - _GUARD_WINDOW + 1)]
        if (secret and len(secret) >= _GUARD_WINDOW)
        else []
    )
    plain = unquote(text)
    for variant in (text, plain, re.sub(r"[^A-Za-z0-9_-]", "", plain)):
        if _TOKEN_WORDS.search(variant) or any(piece in variant for piece in pieces):
            return WITHHELD
    return text


def log_safe(value, limit: int | None = None, secret: str | None = None) -> str:
    """Request-derived text made safe for one log line: guarded, control
    characters made visible escapes, then the length cap."""
    text = guard(str(value), secret) if value is not None else ""
    text = _LOG_UNSAFE.sub(lambda m: m.group().encode("unicode_escape").decode(), text)
    return text[:limit] if limit else text


def log_safe_plain(value, limit: int) -> str:
    """Control characters escaped and capped, no credential guard: for values
    already validated to a safe shape (the 12-character token prefix)."""
    text = _LOG_UNSAFE.sub(lambda m: m.group().encode("unicode_escape").decode(), str(value or ""))
    return text[:limit]


def safe_names(keys, secret: str | None = None) -> list[str]:
    """At most 6 key names, 20 characters each, of ``[A-Za-z0-9_ -]``."""
    names = []
    for key in list(keys)[:MAX_NAMES]:
        name = _NAME_UNSAFE.sub("", str(key))[:NAME_CHARS] or "?"
        names.append(guard(name, secret))
    return names


def _field_summary(value, secret: str | None) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "text", "value": "true" if value else "false"}
    if isinstance(value, (int, float)):
        return {"type": "number", "value": guard(_clean(value, PREVIEW_CHARS), secret)}
    if isinstance(value, str):
        return {"type": "text", "value": guard(_clean(value, PREVIEW_CHARS), secret)}
    if isinstance(value, list):
        return {"type": "list", "value": f"{len(value)} items"}
    if isinstance(value, dict):
        return {"type": "record", "value": "keys: " + ", ".join(safe_names(value, secret))}
    return {"type": "text", "value": WITHHELD}


def summarise_payload(
    payload, content_type: str | None = None, secret: str | None = None, keys=KNOWN_KEYS
) -> str | None:
    """The request body as an allow-listed, compact JSON summary (see above).

    A body that is not a JSON object is described by its size and content type
    only. ``payload`` is the raw body (bytes/str) or the already parsed value.
    """
    if payload is None:
        return None
    body, size = payload, None
    if isinstance(payload, (bytes, str)):
        size = len(payload)
        try:
            text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
            body = json.loads(text) if len(text) <= MAX_PARSED_BODY_CHARS else None
        except (ValueError, RecursionError):
            body = None
    if not isinstance(body, dict):
        ct = guard(_CT_UNSAFE.sub("", content_type or "")[:60].strip(), secret) or "no content type"
        shown = "unknown size" if size is None else f"{size} bytes"
        return f"not a JSON object ({shown}, {ct})"
    out: dict = {}
    for key in keys:
        out[key] = _field_summary(body[key], secret) if key in body else {"type": "missing"}
    out["unknown_keys"] = sum(1 for k in body if k not in keys)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


SUMMARY_VERSION = 1
LEGACY_PAYLOAD_LINE = "[older entry: details not kept]"
LEGACY_DETAIL = "[older entry]"
# Statuses whose detail main's diagnostics wrote as fixed text only.
FIXED_DETAIL_STATUSES = (200, 201, 401, 409, 429)


def summary_lines(payload: str | None) -> list[str]:
    """A stored summary (written by :func:`summarise_payload`) as ``key:
    preview`` lines for the page. Only called for summary_version 1 rows."""
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except ValueError:
        return [payload]
    if not isinstance(data, dict):
        return [payload]
    lines = []
    for key, field in data.items():
        if key == "unknown_keys":
            if field:
                lines.append(f"other keys: {field}")
        elif isinstance(field, dict):
            value, kind = field.get("value"), field.get("type", "?")
            lines.append(f"{key}: {value} ({kind})" if value is not None else f"{key}: {kind}")
    return lines


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
            f"(keys: {', '.join(safe_names(raw))}) — pick the Amount field, not the transaction.",
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


def _prune(
    db: Session, *, token_id: str | None, household_id: str | None, token_prefix: str | None
) -> None:
    """Keep the newest ``KEEP_PER_SCOPE`` rows of each TOKEN (so one token's
    flood cannot evict another's), and a global cap on unattributed rows."""
    if token_id:
        _keep_newest(db, IngestAttempt.token_id == token_id, KEEP_PER_SCOPE)
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
    client_ip: str | None = None,
    db: Session | None = None,
) -> None:
    """Persist one attempt and log one line. Never raises.

    The row is written in its OWN short-lived session, never the request's:
    this function does not flush, commit or roll back the caller's work, so a
    failing request cannot have half of it committed (or undone) by its own
    log. Call it after the request's transaction is decided (commit or
    rollback). ``db`` is accepted for older callers and ignored. A failure to
    record is logged as one fixed line and swallowed: the diagnostic must
    never change the payment it describes.

    What is kept of the body is a summary (:func:`summarise_payload`), never
    the body.
    """
    try:
        secret = (raw_token or None) and raw_token[:128]  # a header, so bounded
        token_id = token.id if token is not None else None
        prefix = (token.prefix if token is not None else None) or (
            raw_token[:DISPLAY_PREFIX_LEN] if raw_token and raw_token.startswith("pat_") else None
        )
        if prefix and not _PREFIX_OK.fullmatch(prefix):
            prefix = None
        path = path or "/api/v1/ingest/apple-pay"
        keys = CLASSIFY_KEYS if path.rstrip("/").endswith("/classify") else KNOWN_KEYS
        summary = summarise_payload(payload, content_type, secret, keys)
        detail_text = guard(_clean(detail, 300), secret) if detail is not None else None
        ct_text = (
            guard(_CT_UNSAFE.sub("", content_type or "")[:100].strip(), secret) or None
            if content_type
            else None
        )
        status = int(status)
    except Exception:
        logger.error("ingest: could not summarise an attempt")
        return

    written = False
    try:
        written = _store_attempt(
            client_ip=client_ip,
            raw_token=raw_token,
            token_id=token_id,
            prefix=prefix,
            status=status,
            detail=detail_text,
            payload=summary,
            content_type=ct_text,
            transaction_id=transaction_id,
        )
    except Exception:
        # Fixed text on purpose: an error can echo the bound parameters.
        logger.error("ingest: could not record an attempt")
        written = True  # still log the line below: it is all there is

    if not written:
        # Past the per-source allowance: write nothing, say so once a minute.
        if _hit("1/minute", "ingest-suppressed", "all"):
            logger.warning("ingest: unattributed attempts are being suppressed")
        return

    try:
        logger.log(
            logging.INFO if status < 400 else logging.WARNING,
            "ingest: %s → %s%s | token=%s | type=%s | payload=%r",
            log_safe(path, 200, secret),
            status,
            f" {log_safe(detail_text, 300)}" if detail_text else "",
            log_safe_plain(prefix, 12) or "-",
            log_safe(ct_text, 100) or "-",
            log_safe(summary, 1500) or "-",
        )
    except Exception:  # pragma: no cover - a log line never breaks a payment
        logger.error("ingest: could not log an attempt")


UNATTRIBUTED_PER_IP = "20/hour"


def _hit(rate: str, scope: str, key: str | None) -> bool:
    """One hit on the shared limiter; True while within ``rate``. A broken
    limiter never blocks a payment or a log row."""
    from limits import parse

    from app.core.ratelimit import limiter

    try:
        return bool(limiter.limiter.hit(parse(rate), scope, key or "unknown"))
    except Exception:  # pragma: no cover
        return True


def is_live_token(db: Session, token: PersonalApiToken) -> bool:
    """Not revoked, and its owner is still a member of its household."""
    from app.models import HouseholdMember

    if token.revoked_at is not None:
        return False
    return (
        db.query(HouseholdMember.id)
        .filter(
            HouseholdMember.household_id == token.household_id,
            HouseholdMember.user_id == token.user_id,
        )
        .first()
        is not None
    )


def live_token_id(raw: str | None) -> str | None:
    """The id of the live token a plaintext value belongs to, else None. Opens
    its own session; any failure is None (the request is then unattributed)."""
    if not raw or not raw.startswith("pat_"):
        return None
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        token = token_from_raw(session, raw[:128])
        return token.id if token is not None and is_live_token(session, token) else None
    except Exception:
        return None
    finally:
        session.close()


def _store_attempt(
    *,
    raw_token,
    token_id,
    prefix,
    status,
    detail,
    payload,
    content_type,
    transaction_id,
    client_ip=None,
) -> bool:
    """Write one row in its own session; False when it was suppressed (an
    unattributed attempt past its per-source-IP hourly allowance)."""
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        token = session.get(PersonalApiToken, token_id) if token_id else None
        if token is None and raw_token:
            token = token_from_raw(session, raw_token)
        # Only a live token of a current member owns an attempt; a revoked or
        # orphaned one is unattributed (and throttled like an unknown one).
        if token is not None and not is_live_token(session, token):
            token = None
        if token is None and not _hit(UNATTRIBUTED_PER_IP, "ingest-unattributed", client_ip):
            return False
        row = IngestAttempt(
            household_id=token.household_id if token is not None else None,
            token_id=token.id if token is not None else None,
            token_prefix=token.prefix if token is not None else prefix,
            status=status,
            detail=detail,
            payload=payload,
            content_type=content_type,
            transaction_id=transaction_id,
            summary_version=SUMMARY_VERSION,
        )
        session.add(row)
        session.flush()
        _prune(
            session,
            token_id=row.token_id,
            household_id=row.household_id,
            token_prefix=row.token_prefix,
        )
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


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
        logger.info("ingest: ignoring an unparseable occurred_at")
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
        logger.info("ingest: the card value is not text — leaving it out of the notes")
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


# ---------------------------------------------------------------------------
# Save first, then ask (polish S6): classify what the token just added
# ---------------------------------------------------------------------------

CLASSIFY_WINDOW = timedelta(minutes=15)
_CHOICE_MAX = 200  # a category or bucket name, or an id
CANNOT_CLASSIFY = "This token cannot classify. Create a token with the category prompt enabled."


def ingest_choices(db: Session, token: PersonalApiToken, txn: Transaction) -> dict:
    """What the ingest response says about classifying.

    ``needs_category`` (no rule matched) is for every token: a boolean about
    the token's own just-created expense. The names of the household's
    categories and buckets are given only to a token created with the
    ``classify`` scope: ``categories``/``category_names`` while it needs a
    category, ``buckets``/``bucket_names`` always (the purchase's own first).
    """
    out: dict = {"needs_category": txn.category_id is None}
    if not token.can_classify:
        return out
    hh = token.household_id
    if out["needs_category"]:
        cats = _category_rows(db, hh)
        out["categories"] = [{"id": c.id, "name": c.name} for c in cats]
        out["category_names"] = [c.name for c in cats]
    buckets = _bucket_rows(db, hh)
    buckets.sort(key=lambda b: b.id != txn.bucket_id)  # stable: the chosen one first
    out["buckets"] = [{"id": b.id, "name": b.name} for b in buckets]
    out["bucket_names"] = [b.name for b in buckets]
    return out


def _category_rows(db: Session, household_id: str):
    return (
        db.query(Category.id, Category.name)
        .filter(Category.household_id == household_id)
        .order_by(Category.is_default.desc(), Category.name, Category.id)
        .all()
    )


def _bucket_rows(db: Session, household_id: str):
    return (
        db.query(Bucket.id, Bucket.name)
        .filter(Bucket.household_id == household_id, Bucket.status == BucketStatus.active)
        .order_by(Bucket.created_at, Bucket.id)
        .all()
    )


def classifiable(db: Session, token: PersonalApiToken, transaction_id: str) -> Transaction | None:
    """The purchase, if this token may classify it: a live transaction of the
    token's household that THIS token's ingest created (an attempts row with
    status 200/201 says so; transactions carry no token) less than 15 minutes
    ago. None for anything else, with no hint as to which check failed."""
    if not transaction_id or len(transaction_id) > 64:
        return None
    txn = db.get(Transaction, transaction_id)
    if (
        txn is None
        or txn.household_id != token.household_id
        or txn.deleted_at is not None
        or txn.created_at is None
        or txn.created_at < utcnow_naive() - CLASSIFY_WINDOW
    ):
        return None
    mine = (
        db.query(IngestAttempt.id)
        .filter(
            IngestAttempt.household_id == token.household_id,
            IngestAttempt.token_id == token.id,
            IngestAttempt.transaction_id == txn.id,
            IngestAttempt.status.in_((200, 201)),
        )
        .first()
    )
    return txn if mine is not None else None


def _unknown(kind: str, choice: str) -> HTTPException:
    return HTTPException(
        status_code=422, detail=f"Unknown {kind} '{_clean(choice, PREVIEW_CHARS)}'"
    )


def _pick(rows, choice: str):
    """The row whose id is ``choice``, else the one whose name is (trimmed,
    case-insensitive; the first in picker order when two share a name)."""
    wanted = choice.strip()
    for row in rows:
        if row.id == wanted:
            return row
    folded = wanted.casefold()
    for row in rows:
        if (row.name or "").strip().casefold() == folded:
            return row
    return None


def classify_ingested(
    db: Session,
    token: PersonalApiToken,
    txn: Transaction,
    *,
    category=None,
    bucket=None,
) -> tuple[Transaction, list[str]]:
    """Set the category and/or bucket of a purchase the token just added.

    ``category`` and ``bucket`` are an id or an exact name (Shortcuts' Choose
    from List gives the name); an unknown one, another household's or an
    archived bucket is HTTP 422 "Unknown category 'X'". The edit goes through
    :func:`app.services.transactions.update_transaction` with every other
    field as stored, so its rules hold (a Fixed cost stays bucket-less).
    It never creates, changes or deletes a category rule: the merchant string
    is chosen by whoever holds the token, so a rule from it would be planted
    household-wide. Returns (transaction, the chosen names). Commits.
    """
    from app.schemas import SplitIn, TransactionUpdate
    from app.validators import require_bucket, require_category

    hh = token.household_id
    category_id, bucket_id = txn.category_id, txn.bucket_id
    chosen: list[str] = []
    if category:
        if len(category) > _CHOICE_MAX:
            raise _unknown("category", category)
        found = _pick(_category_rows(db, hh), category)
        if found is None:
            raise _unknown("category", category)
        category_id = require_category(db, found.id, hh)
        chosen.append(found.name)
    if bucket:
        if len(bucket) > _CHOICE_MAX:
            raise _unknown("bucket", bucket)
        found = _pick(_bucket_rows(db, hh), bucket)
        if found is None:
            raise _unknown("bucket", bucket)
        bucket_id = require_bucket(db, found.id, hh).id
        chosen.append(found.name)

    try:
        data = TransactionUpdate(
            bucket_id=bucket_id,
            amount=txn.amount,
            currency=txn.currency,
            exchange_rate=txn.exchange_rate,
            type=txn.type,
            paid_by=txn.paid_by,
            payer_mode=txn.payer_mode,
            category_id=category_id,
            notes=txn.notes,
            transaction_date=txn.transaction_date,
            payment_method=txn.payment_method,
            merchant=txn.merchant,
            exclude_from_forecast=txn.exclude_from_forecast,
            exclude_from_settlement=txn.exclude_from_settlement,
            splits=[SplitIn(user_id=s.user_id, amount=s.amount) for s in txn.splits],
        )
    except ValidationError as exc:
        msg = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
        raise HTTPException(status_code=422, detail=msg) from None
    update_transaction(db, txn, household_id=hh, user=token.user, data=data)

    db.commit()
    db.refresh(txn)
    return txn, chosen

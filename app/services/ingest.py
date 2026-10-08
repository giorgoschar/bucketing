"""Apple Pay ingest: turn an iOS Shortcut payload into an expense.

The Shortcut fires once per Wallet transaction but iOS is known to retry or
double-fire it, so every payload maps to a deterministic ``client_id``
(:func:`ingest_client_id`) and the existing unique
``(household_id, client_id)`` makes replays idempotent.
"""

import hashlib
import json
import logging
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
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
from app.services.personal_tokens import active_household_bucket
from app.services.transactions import DuplicateTransaction, create_transaction
from app.validators import parse_amount

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The amount, as iOS sends it
# ---------------------------------------------------------------------------

_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}
# ISO 4217 currencies with three decimal places.
THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})
_GROUPING_MARKS = "'\u2019"  # 1'234.56
_ASCII_DIGITS = "0123456789"
_ASCII_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
# Longer than any real amount ("EUR 1.234.567,89" is 16): anything beyond is
# refused before it is looked at, so parsing costs the same whatever is sent.
MAX_AMOUNT_TEXT = 40
MAX_MERCHANT = 200  # app.schemas._clean_merchant's limit
MAX_OCCURRED_AT = 40


def parse_ingest_amount(raw, currency: str | None = None) -> tuple[Decimal, str | None]:
    """The amount of an Apple Pay payload, and the currency its text names.

    iOS's Transaction trigger gives the amount as a locale currency string
    ("12,50 €", "€1.234,56"), which the shared :func:`parse_amount` rejects.
    This reads it (ingest only; numbers go straight to ``parse_amount``):

    * **Spaces** anywhere are dropped: normal, non-breaking (U+00A0) and narrow
      non-breaking (U+202F), so "1 234,56" is 1234.56.
    * **Currency**: one symbol (€ EUR, $ USD, £ GBP) or one three-letter code,
      anywhere, is removed and returned as the detected currency ("€12,50",
      "12,50 €", "EUR 12.50", "12.50EUR" are all 12.50 EUR). The caller uses
      it only when the payload has no ``currency`` of its own.
    * **Separators**. With both "." and ",", the last one is the decimal
      separator and the other groups thousands ("1.234,56" and "1,234.56" are
      1234.56). One kind used more than once groups thousands ("1.234.567").
      A single separator is the decimal separator, **except** when exactly
      three digits follow it: then it groups thousands ("1.234" and "1,234"
      are 1234), unless

      - the currency has three decimals (:data:`THREE_DECIMAL_CURRENCIES`; the
        code in the text, else ``currency``): "1.234" KWD is 1.234;
      - nothing but zeros comes before it ("0.500" is a half, not 500);
      - the three digits end in "00": that is a two-decimal amount padded to
        three places ("12.500" is 12.50, as it has always been read here).

    * A **minus** (or U+2212), i.e. a refund, is rejected as before, and so
      is zero: 400 "Amount must be greater than zero."
    * Anything else is a 400 that shows the start of what was sent (the
      caller's own input): "Amount must be a number like 12,50 (got: '...')".
      So is any text longer than :data:`MAX_AMOUNT_TEXT` characters, refused
      before it is read; the rest is one pass over the characters.

    Returns ``(amount, detected currency or None)``; the amount is quantized
    like ``parse_amount``'s.
    """
    if not isinstance(raw, str):
        return parse_amount(raw), None

    def bad() -> HTTPException:
        return HTTPException(
            status_code=400,
            detail=f"Amount must be a number like 12,50 (got: '{raw[:40].strip()[:20]}')",
        )

    if len(raw) > MAX_AMOUNT_TEXT:
        raise bad()
    if not raw.strip():
        return parse_amount(raw), None  # 400 "Amount is required."

    # One pass over at most MAX_AMOUNT_TEXT characters (no regular
    # expressions): digits and separators are kept, a currency symbol or a
    # run of letters is noted, anything else is not an amount.
    kept: list[str] = []
    found: set[str] = set()
    word = ""
    negative = False

    def end_word() -> None:
        nonlocal word
        if word:
            if len(word) != 3:
                raise bad()
            found.add(word.upper())
            word = ""

    for ch in raw:
        if ch in _ASCII_LETTERS:
            word += ch
            continue
        if ch.isspace():
            continue  # U+00A0 and U+202F included
        end_word()
        if ch in _ASCII_DIGITS or ch in ".,":
            kept.append(ch)
        elif ch in _SYMBOLS:
            found.add(_SYMBOLS[ch])
        elif ch in _GROUPING_MARKS:
            continue
        elif ch in "-\u2212" and not kept and not negative:
            negative = True  # only before the number: "-€12,50", "€-12,50"
        else:
            raise bad()
    end_word()
    if len(found) > 1:
        raise bad()
    detected = next(iter(found), None)
    text = "".join(kept)
    if not any(ch in _ASCII_DIGITS for ch in text):
        raise bad()

    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        decimal = "." if text.rfind(".") > text.rfind(",") else ","
        if text.count(decimal) != 1:
            raise bad()
        text = text.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif dots + commas > 1:
        text = text.replace(".", "").replace(",", "")
    elif dots + commas == 1:
        whole, _, fraction = text.replace(",", ".").partition(".")
        groups_thousands = (
            len(fraction) == 3
            and whole.strip("0") != ""
            and not fraction.endswith("00")
            and (detected or currency or "").upper() not in THREE_DECIMAL_CURRENCIES
        )
        text = whole + fraction if groups_thousands else f"{whole}.{fraction}"
    if negative:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    return parse_amount(text), detected


def parse_occurred_at(raw: str | None) -> datetime | None:
    """ISO-8601 → aware datetime, or None when absent/unparseable.

    A naive value is read as household-local time. Unparseable input is
    ignored rather than rejected: losing the expense because the Shortcut
    sent an odd date format is worse than dating it "now".
    """
    if not raw or not str(raw).strip():
        return None
    if len(str(raw)) > MAX_OCCURRED_AT:
        logger.info("ingest: ignoring an over-long occurred_at")
        return None
    try:
        moment = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        logger.info("ingest: ignoring unparseable occurred_at")
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
    merchant: str,
    amount,
    currency: str | None = None,
    card: str | None = None,
    occurred_at: str | None = None,
    notes: str | None = None,
    exchange_rate=None,
) -> tuple[Transaction, bool]:
    """Create (or find, on replay) the expense. Returns (transaction, created).

    Raises HTTPException 400 (bad amount), 422 (blank merchant, bad currency,
    no bucket) and propagates DeletedTransactionReplay (the caller maps it to
    409: a deleted expense is never resurrected by a retry).
    """
    merchant = merchant or ""
    # Checked before anything scans it (the rules match on the merchant).
    if len(merchant) > 4 * MAX_MERCHANT or len(" ".join(merchant.split())) > MAX_MERCHANT:
        raise HTTPException(
            status_code=422, detail=f"Merchant must be at most {MAX_MERCHANT} characters."
        )
    merchant = " ".join(merchant.split())
    if not merchant:
        raise HTTPException(status_code=422, detail="Merchant is required.")
    household = db.get(Household, token.household_id)
    currency = (currency or "").strip().upper() or None
    value, detected = parse_ingest_amount(amount, currency or household.default_currency)
    moment = parse_occurred_at(occurred_at)
    bucket = resolve_ingest_bucket(db, token)
    # Rules only: the built-in guess fuzzy-matches a category *hint*, and
    # merchant names ("Corner Kiosk" ~ "Groceries") give false positives.
    category_id = resolve_category(db, token.household_id, merchant=merchant, hint=None)

    fields = {
        "bucket_id": bucket.id,
        "amount": value,
        # The payload's own currency, else the one its amount names ("12,50 €").
        "currency": currency or detected or household.default_currency or "EUR",
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


# ---------------------------------------------------------------------------
# The attempts log (polish S5)
# ---------------------------------------------------------------------------

ATTEMPTS_KEPT = 50
CREATED, DUPLICATE, REJECTED = "created", "duplicate", "rejected"
CLASSIFIED = "classified"
_LOG_VALUE_MAX = 40


# The payload's own keys; any other key name is counted, never logged.
KNOWN_KEYS = frozenset(
    {"merchant", "amount", "currency", "card", "occurred_at", "notes", "exchange_rate"}
)


def safe_text(value, limit: int = _LOG_VALUE_MAX) -> str:
    """``value`` made safe to log or store: control and format characters (CR,
    LF, NUL, escape, bidi overrides, U+2028/9...) dropped and at most
    ``limit`` characters kept. Only the first ``4 * limit`` characters are
    ever looked at. Request-derived text goes through this before it reaches
    a log line or an ``ingest_attempts`` row, so it cannot forge a log line."""
    text = str(value)[: 4 * limit]
    kept = [ch for ch in text if unicodedata.category(ch) not in _UNSAFE_CATEGORIES]
    return "".join(kept)[:limit]


# Cc control, Cf format (bidi), Cs surrogate, Co private use, Cn unassigned,
# Zl / Zp line and paragraph separators.
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def _json_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    return {str: "str", int: "int", float: "float", list: "list", dict: "dict"}.get(
        type(value), "other"
    )


def _first(value):
    """What a one-element Shortcuts list holds (see ApplePayIn)."""
    return value[0] if isinstance(value, list) and value else value


def attempt_fields(payload) -> tuple[str | None, str | None]:
    """``(merchant, amount_raw)`` for the log from a parsed JSON body: the
    start of what was sent (80 and 40 characters), cleaned (:func:`safe_text`),
    whatever its shape."""
    if not isinstance(payload, dict):
        return None, None
    merchant = _first(payload.get("merchant"))
    # Cut before anything scans it: at most 320 characters are ever touched.
    merchant = (
        safe_text(" ".join(merchant[:320].split()), 80) or None
        if isinstance(merchant, str)
        else None
    )
    amount = payload.get("amount")
    if amount is None:
        raw = None
    elif isinstance(amount, str):
        raw = safe_text(amount[:160].strip(), 40) or None
    elif isinstance(amount, bool | int | float):
        raw = safe_text(repr(amount), 40)
    else:
        # A list or object: its shape and the start of its first element,
        # never a dump of all of it.
        first = _first(amount) if isinstance(amount, list) else None
        inner = safe_text(repr(first), 30) if isinstance(first, str | int | float) else "…"
        raw = f"[{inner}]" if isinstance(amount, list) else "{…}"
    return merchant, raw


def describe_payload(payload) -> str:
    """A safe one-line summary of a body for the server log: which of the
    known keys it has, how many others, and the shape of the amount and
    merchant. Nothing the client chose is in it: no values, no key names
    beyond :data:`KNOWN_KEYS`."""
    if not isinstance(payload, dict):
        return f"body_type={_json_type(payload)}"
    known = sorted(k for k in KNOWN_KEYS if k in payload)
    merchant = _first(payload.get("merchant"))
    return (
        f"keys=[{','.join(known)}] "
        f"unknown_keys={len(payload) - len(known)} "
        f"amount_type={_json_type(payload['amount']) if 'amount' in payload else 'missing'} "
        f"merchant_len={len(merchant) if isinstance(merchant, str) else 0}"
    )


def log_rejection(status_code: int, reason: str, payload, *, what: str = "apple-pay") -> None:
    """Every rejected ingest, at WARNING, with the reason. Never the token.
    One record, one line: the reason (the only part that can echo input, at
    most 20 characters of the amount) is cleaned by :func:`safe_text` and
    JSON-quoted."""
    if what != "apple-pay":
        logger.warning(
            "ingest %s rejected status=%s reason=%s",
            "classify",
            int(status_code),
            json.dumps(safe_text(reason, 300), ensure_ascii=False),
        )
        return
    logger.warning(
        "ingest apple-pay rejected status=%s reason=%s %s",
        int(status_code),
        json.dumps(safe_text(reason, 300), ensure_ascii=False),
        describe_payload(payload),
    )


def record_attempt(
    db: Session,
    *,
    household_id: str,
    token_id: str | None,
    user_id: str | None,
    status_code: int,
    outcome: str,
    reason: str | None = None,
    merchant: str | None = None,
    amount_raw: str | None = None,
    transaction_id: str | None = None,
) -> None:
    """Store one attempt and drop that member's rows (in the household)
    beyond the newest :data:`ATTEMPTS_KEPT`; commits. ``household_id`` and
    ``user_id`` are the authenticated token's, never the request's. Best effort: a failure here is logged and
    never changes the ingest's own response."""
    try:
        db.rollback()  # a rejected save may have left the session mid-transaction
        db.add(
            IngestAttempt(
                household_id=household_id,
                token_id=token_id,
                user_id=user_id,
                status_code=status_code,
                outcome=outcome,
                reason=(safe_text(reason, 300) or None) if reason is not None else None,
                merchant=(safe_text(merchant, 80) or None) if merchant else None,
                amount_raw=(safe_text(amount_raw, 40) or None) if amount_raw else None,
                transaction_id=transaction_id,
            )
        )
        db.flush()
        # Tokens are personal, so is the log: the newest 50 per member.
        mine = [IngestAttempt.household_id == household_id, IngestAttempt.user_id == user_id]
        keep = (
            db.query(IngestAttempt.id)
            .filter(*mine)
            .order_by(IngestAttempt.created_at.desc(), IngestAttempt.id.desc())
            .limit(ATTEMPTS_KEPT)
        )
        # Rows that still say "this token added that purchase" outlive the
        # cut for as long as the purchase can be classified (15 minutes).
        marker = (
            IngestAttempt.outcome.in_((CREATED, DUPLICATE))
            & IngestAttempt.transaction_id.isnot(None)
            & (IngestAttempt.created_at >= utcnow_naive() - timedelta(minutes=15))
        )
        db.query(IngestAttempt).filter(
            *mine, IngestAttempt.id.notin_([i for (i,) in keep]), ~marker
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("ingest: recording the attempt failed")


def list_attempts(db: Session, household_id: str, user_id: str) -> list[IngestAttempt]:
    """The member's own attempts in the household (what their tokens sent),
    newest first, at most :data:`ATTEMPTS_KEPT`. Never another member's:
    tokens are personal, whatever the caller's role."""
    from sqlalchemy.orm import joinedload

    return (
        db.query(IngestAttempt)
        .options(joinedload(IngestAttempt.token))
        .filter(IngestAttempt.household_id == household_id, IngestAttempt.user_id == user_id)
        .order_by(IngestAttempt.created_at.desc(), IngestAttempt.id.desc())
        .limit(ATTEMPTS_KEPT)
        .all()
    )


# ---------------------------------------------------------------------------
# Save first, then ask (polish S6)
# ---------------------------------------------------------------------------

CLASSIFY_WINDOW = timedelta(minutes=15)
_CHOICE_MAX = 200  # a category or bucket name, or an id


def ingest_choices(db: Session, household_id: str, txn: Transaction) -> dict:
    """What the Shortcut may ask about a purchase it has just added:
    ``needs_category`` (no rule matched), then, only when it does, the
    household's categories in the app picker's order (defaults first, then
    by name), and always the active buckets, the purchase's own first.
    ``*_names`` are the same lists as plain strings: Shortcuts' Choose from
    List takes a list of text as it is. Nothing else about the household is
    ever given to an ingest token."""
    out: dict = {"needs_category": txn.category_id is None}
    if out["needs_category"]:
        cats = (
            db.query(Category.id, Category.name)
            .filter(Category.household_id == household_id)
            .order_by(Category.is_default.desc(), Category.name, Category.id)
            .all()
        )
        out["categories"] = [{"id": c.id, "name": c.name} for c in cats]
        out["category_names"] = [c.name for c in cats]
    buckets = (
        db.query(Bucket.id, Bucket.name)
        .filter(Bucket.household_id == household_id, Bucket.status == BucketStatus.active)
        .order_by(Bucket.created_at, Bucket.id)
        .all()
    )
    buckets.sort(key=lambda b: b.id != txn.bucket_id)  # stable: the chosen one first
    out["buckets"] = [{"id": b.id, "name": b.name} for b in buckets]
    out["bucket_names"] = [b.name for b in buckets]
    return out


def classifiable(db: Session, token: PersonalApiToken, transaction_id: str) -> Transaction | None:
    """The purchase, if this token may classify it: an active transaction of
    the token's household that THIS token's ingest added (an attempts row
    says so: transactions carry no token) in the last 15 minutes. None for
    anything else, with no hint as to which check failed."""
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
            IngestAttempt.outcome.in_((CREATED, DUPLICATE)),
        )
        .first()
    )
    return txn if mine is not None else None


def _unknown(kind: str, choice: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Unknown {kind} '{safe_text(choice)}'")


def _pick(rows, choice: str):
    """The row whose id is ``choice``, else the one whose name is (trimmed,
    case-insensitive; the first in picker order if two share a name)."""
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
    category: str | None = None,
    bucket: str | None = None,
    remember: bool = False,
) -> Transaction:
    """Set the category and/or bucket of a purchase the token just added.

    ``category`` and ``bucket`` are an id or an exact name (Shortcuts'
    Choose from List returns the name); an unknown one, another household's
    or an archived bucket is HTTP 422 "Unknown category 'X'". The edit goes
    through :func:`app.services.transactions.update_transaction` with every
    other field as stored, so its rules hold (a Fixed cost stays bucket-less,
    nothing else may). ``remember`` with a category teaches the household's
    merchant rule (:func:`app.services.category_rules.learn_rule`, the one
    Settings uses): an existing rule for the merchant is re-pointed, never
    duplicated. Commits.
    """
    from app.schemas import SplitIn, TransactionUpdate
    from app.services.category_rules import learn_rule
    from app.services.transactions import update_transaction
    from app.validators import require_bucket, require_category

    hh = token.household_id
    category_id, bucket_id = txn.category_id, txn.bucket_id
    if category:
        if len(category) > _CHOICE_MAX:
            raise _unknown("category", category)
        cats = (
            db.query(Category.id, Category.name)
            .filter(Category.household_id == hh)
            .order_by(Category.is_default.desc(), Category.name, Category.id)
            .all()
        )
        found = _pick(cats, category)
        if found is None:
            raise _unknown("category", category)
        category_id = require_category(db, found.id, hh)
    if bucket:
        if len(bucket) > _CHOICE_MAX:
            raise _unknown("bucket", bucket)
        buckets = (
            db.query(Bucket.id, Bucket.name)
            .filter(Bucket.household_id == hh, Bucket.status == BucketStatus.active)
            .order_by(Bucket.created_at, Bucket.id)
            .all()
        )
        found = _pick(buckets, bucket)
        if found is None:
            raise _unknown("bucket", bucket)
        bucket_id = require_bucket(db, found.id, hh).id

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
    if remember and category and category_id:
        learn_rule(db, hh, txn.merchant, category_id, created_by=token.user_id)
    db.commit()
    db.refresh(txn)
    return txn

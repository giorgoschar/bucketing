"""Apple Pay ingest: turn an iOS Shortcut payload into an expense.

The Shortcut fires once per Wallet transaction but iOS is known to retry or
double-fire it, so every payload maps to a deterministic ``client_id``
(:func:`ingest_client_id`) and the existing unique
``(household_id, client_id)`` makes replays idempotent.
"""

import hashlib
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.clock import local_today, tz, utcnow
from app.core.money import quantize
from app.models import (
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    Household,
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
_GROUPING_MARKS = ("'", "\u2019")  # 1'234.56
_LETTERS = re.compile(r"[A-Za-z]+")
_DIGITS_AND_SEPARATORS = re.compile(r"[0-9.,]*[0-9][0-9.,]*")


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

    Returns ``(amount, detected currency or None)``; the amount is quantized
    like ``parse_amount``'s.
    """
    if not isinstance(raw, str):
        return parse_amount(raw), None
    if not raw.strip():
        return parse_amount(raw), None  # 400 "Amount is required."

    def bad() -> HTTPException:
        return HTTPException(
            status_code=400,
            detail=f"Amount must be a number like 12,50 (got: '{raw.strip()[:20]}')",
        )

    text = "".join(ch for ch in raw if not ch.isspace()).replace("\u2212", "-")
    found = {_SYMBOLS[ch] for ch in text if ch in _SYMBOLS}
    for ch in _SYMBOLS:
        text = text.replace(ch, "")
    for word in _LETTERS.findall(text):
        if len(word) != 3:
            raise bad()
        found.add(word.upper())
    text = _LETTERS.sub("", text)
    if len(found) > 1:
        raise bad()
    detected = next(iter(found), None)

    negative = text.startswith("-")
    if negative:
        text = text[1:]
    for mark in _GROUPING_MARKS:
        text = text.replace(mark, "")
    if not _DIGITS_AND_SEPARATORS.fullmatch(text):
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
    merchant = " ".join((merchant or "").split())
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

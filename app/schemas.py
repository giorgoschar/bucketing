"""
Pydantic input models shared by the HTML and JSON API routes.

Validation lives here so a transaction is checked identically whether it comes
from the web form or the API. Field validators reuse the helpers in
``app.validators`` (which raise ``HTTPException``) and re-raise as ``ValueError``
so pydantic collects them into a ``ValidationError`` — FastAPI turns that into a
422 for JSON bodies; the HTML route maps it to its own re-rendered error.
"""
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app import validators
from app.clock import local_today
from app.models import PayerMode, PaymentMethod, TransactionType
from app.money import quantize


def _checked(fn, *args, **kwargs):
    """Run a validators.* helper, converting its HTTPException to ValueError."""
    try:
        return fn(*args, **kwargs)
    except HTTPException as exc:
        raise ValueError(exc.detail) from None


def parse_payment_method(v: Any) -> str:
    """Normalise to a PaymentMethod value; blank means the default (card)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return PaymentMethod.card.value
    try:
        return PaymentMethod(str(v).strip()).value
    except ValueError:
        raise ValueError(
            f"Unknown payment method '{v}'. Allowed: {', '.join(m.value for m in PaymentMethod)}."
        ) from None


# Where "I took this from my stash" took the cash from: the payer's own
# stash, or the bank (an ATM). See app.services.cash.
TAKE_FROM_STASH = "stash"
TAKE_FROM_BANK = "bank"


def parse_take_from(v: Any) -> str:
    """Normalise a take source; blank means the payer's own stash."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return TAKE_FROM_STASH
    value = str(v).strip()
    if value not in (TAKE_FROM_STASH, TAKE_FROM_BANK):
        raise ValueError(
            f"Unknown cash source '{v}'. Allowed: {TAKE_FROM_STASH}, {TAKE_FROM_BANK}."
        )
    return value


# The payer dropdowns (expense wizard, edit form, bill forms, bulk assign) list
# the members plus this value for "Each paid their own share". It is never a
# user id; payer_choice() turns the submitted value into (paid_by, payer_mode).
OWN_SHARE_CHOICE = "__own_share__"

OWN_SHARE_TAKE = "Cash taken for an expense needs a single payer, not each their own share."
BUCKET_REQUIRED = "A bucket is required (only income can go without one)."


def payer_choice(value: Any) -> tuple[str | None, str]:
    """Map a payer dropdown value to ``(paid_by, payer_mode)``."""
    value = (str(value) if value is not None else "").strip()
    if value == OWN_SHARE_CHOICE:
        return None, PayerMode.own_share.value
    return value or None, PayerMode.single.value


def parse_payer_mode(v: Any) -> str:
    """Normalise to a PayerMode value; blank means the default (single)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return PayerMode.single.value
    try:
        return PayerMode(str(v).strip()).value
    except ValueError:
        raise ValueError(
            f"Unknown payer mode '{v}'. Allowed: {', '.join(m.value for m in PayerMode)}."
        ) from None


def own_share_problem(amount: Decimal, split_amounts) -> str | None:
    """Why an own-share expense of ``amount`` with these splits is invalid, if it is.

    Each member's split is what they paid, so the splits must account for the
    whole total (to the cent): anything left over would be paid by nobody.
    """
    split_amounts = list(split_amounts)
    if not split_amounts:
        return "Each paid their own share needs every member's share filled in."
    split_total = sum(split_amounts, Decimal(0))
    if abs(split_total - Decimal(str(amount))) > Decimal("0.01"):
        return (
            f"Each paid their own share: the shares ({float(split_total):.2f}) must "
            f"add up to the total ({float(amount):.2f})."
        )
    return None


def absorb_own_share_cent(amount, splits) -> None:
    """Make an own-share expense's splits add up to ``amount`` exactly.

    :func:`own_share_problem` lets the shares miss the total by a cent of
    rounding (100 paid 33.33 / 66.66). Left as it is, that cent was paid by
    nobody and showed up as an "Unassigned" row that no search could find, so
    it goes to the largest share (the first of equal ones). ``splits`` are
    anything with an ``amount`` (input splits or stored rows); changed in place.
    """
    splits = list(splits)
    if not splits:
        return
    gap = Decimal(str(amount)) - sum((Decimal(str(s.amount)) for s in splits), Decimal(0))
    if gap:
        largest = max(splits, key=lambda s: Decimal(str(s.amount)))
        largest.amount = Decimal(str(largest.amount)) + gap


# Upper bound of transactions.fuel_price_per_litre (NUMERIC(8,4)).
MAX_FUEL_PRICE = Decimal("9999.9999")
FUEL_PRICE_INVALID = "Price per litre must be a number greater than 0."


def parse_fuel_price(v: Any) -> Decimal | None:
    """A price per litre, rounded half up to 4 dp; blank means none.

    Accepts a decimal comma like the amount fields. Must come out above zero:
    the litres are amount / price.
    """
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        price = Decimal(str(v).strip().replace(",", "."))
    except Exception:
        raise ValueError(FUEL_PRICE_INVALID) from None
    if not price.is_finite():
        raise ValueError(FUEL_PRICE_INVALID)
    price = quantize(price, Decimal("0.0001"))
    if not (0 < price <= MAX_FUEL_PRICE):
        raise ValueError(FUEL_PRICE_INVALID)
    return price


def _clean_merchant(v: str | None) -> str | None:
    v = (v or "").strip()
    if len(v) > 200:
        raise ValueError("Merchant must be at most 200 characters.")
    return v or None


class SplitIn(BaseModel):
    user_id: str
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Decimal:
        return _checked(validators.parse_amount, v, field="Split amount")


class TransactionCreate(BaseModel):
    """Everything needed to create one transaction.

    ``payment_method`` is validated against ``PaymentMethod`` (default card).
    ``bucket_id`` may be left out (or blank) only for income.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    bucket_id: str | None = None
    amount: Decimal
    currency: str = "EUR"
    exchange_rate: Decimal = Decimal("1")
    type: TransactionType = TransactionType.expense
    paid_by: str | None = None
    category_id: str | None = None
    notes: str | None = None
    transaction_date: date | None = None  # blank/None means today
    exclude_from_forecast: bool = False
    exclude_from_settlement: bool = False
    splits: list[SplitIn] = []
    client_id: str | None = None
    payment_method: str = PaymentMethod.card.value
    merchant: str | None = None
    payer_mode: str | None = PayerMode.single.value
    # Cash expenses only: "I took this from my stash" (the service also
    # records the matching take into the payer's wallet, from ``take_from``:
    # their stash or the bank; see app.services.cash).
    took_cash: bool = False
    take_from: str | None = None
    # Fuel expenses only: the price per litre, in ``currency``. The litres are
    # always worked out by the server (app.services.fuel); a client value is
    # ignored, and the price is dropped unless the category is the fuel one.
    fuel_price_per_litre: Decimal | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Decimal:
        return _checked(validators.parse_amount, v, field="Amount")

    @field_validator("payment_method", mode="before")
    @classmethod
    def _payment_method(cls, v: Any) -> str:
        return parse_payment_method(v)

    @field_validator("payer_mode", mode="before")
    @classmethod
    def _payer_mode(cls, v: Any) -> str:
        return parse_payer_mode(v)

    @field_validator("merchant")
    @classmethod
    def _merchant(cls, v: str | None) -> str | None:
        return _clean_merchant(v)

    @field_validator("fuel_price_per_litre", mode="before")
    @classmethod
    def _fuel_price(cls, v: Any) -> Decimal | None:
        return parse_fuel_price(v)

    @field_validator("take_from", mode="before")
    @classmethod
    def _take_from(cls, v: Any) -> str:
        return parse_take_from(v)

    @field_validator("currency")
    @classmethod
    def _currency(cls, v: str) -> str:
        return _checked(validators.validate_currency, v)

    @field_validator("exchange_rate", mode="before")
    @classmethod
    def _rate(cls, v: Any) -> Decimal:
        try:
            rate = Decimal(str(v).strip().replace(",", "."))
        except Exception:
            raise ValueError("Exchange rate must be a number.") from None
        if not rate.is_finite() or not (0 < rate <= 1_000_000):
            raise ValueError("Exchange rate is out of range.")
        return rate

    @field_validator("transaction_date", mode="before")
    @classmethod
    def _date(cls, v: Any) -> date:
        if v is None or (isinstance(v, str) and not v.strip()):
            return local_today()
        if isinstance(v, str):
            try:
                return date.fromisoformat(v.strip())
            except ValueError:
                raise ValueError("Date must be a valid date (YYYY-MM-DD).") from None
        return v

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, v: Any) -> TransactionType:
        try:
            return TransactionType(v)
        except ValueError:
            raise ValueError(f"Unknown transaction type '{v}'.") from None

    @field_validator("bucket_id", "paid_by", "category_id", "notes", "client_id")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v or None

    @field_validator("client_id")
    @classmethod
    def _client_id_len(cls, v: str | None) -> str | None:
        if v and len(v) > 64:
            raise ValueError("client_id must be at most 64 characters.")
        return v

    @model_validator(mode="after")
    def _bucket_unless_income(self) -> "TransactionCreate":
        """Expenses and transfers belong to a bucket; income may have none."""
        if not self.bucket_id and self.type != TransactionType.income:
            raise ValueError(BUCKET_REQUIRED)
        return self

    @model_validator(mode="after")
    def _splits_within_total(self) -> "TransactionCreate":
        if self.splits:
            split_total = sum(s.amount for s in self.splits)
            if split_total > self.amount:
                raise ValueError(
                    f"Split amounts ({float(split_total):.2f}) exceed the "
                    f"transaction total ({float(self.amount):.2f})."
                )
        return self

    @model_validator(mode="after")
    def _cash_fields(self) -> "TransactionCreate":
        """Only a cash expense can have cash taken for it."""
        if self.took_cash and (self.payment_method != PaymentMethod.cash.value
                               or self.type != TransactionType.expense):
            raise ValueError("Only a cash expense can have cash taken for it.")
        return self

    @model_validator(mode="after")
    def _own_share(self) -> "TransactionCreate":
        """Own share: an expense whose splits are what each member paid.

        There is no single payer, so ``paid_by`` is dropped.
        """
        if self.payer_mode != PayerMode.own_share.value:
            return self
        if self.type != TransactionType.expense:
            raise ValueError("Each paid their own share is only for expenses.")
        # Each member's cash came out of their own wallet, so one take
        # cannot stand for all of it.
        if self.took_cash:
            raise ValueError(OWN_SHARE_TAKE)
        problem = own_share_problem(self.amount, (s.amount for s in self.splits))
        if problem:
            raise ValueError(problem)
        absorb_own_share_cent(self.amount, self.splits)
        self.paid_by = None
        return self


class TransactionUpdate(TransactionCreate):
    """Edit input: the same field checks as create (currency, rate > 0,
    amount, splits ≤ total, payment method, own-share splits), except a blank
    date keeps the existing one instead of meaning "today", and an omitted
    ``payer_mode`` (None) is resolved by the caller from the stored row.
    ``client_id``, ``took_cash`` and ``take_from`` are ignored (a take is
    linked at creation; edits keep an existing link in step), and an omitted
    ``fuel_price_per_litre`` (not sent at all, unlike an explicit null or
    blank) keeps the stored price."""

    transaction_date: date | None = None
    payer_mode: str | None = None

    @field_validator("payer_mode", mode="before")
    @classmethod
    def _payer_mode(cls, v: Any) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return parse_payer_mode(v)

    @field_validator("transaction_date", mode="before")
    @classmethod
    def _date(cls, v: Any) -> date | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            try:
                return date.fromisoformat(v.strip())
            except ValueError:
                raise ValueError("Date must be a valid date (YYYY-MM-DD).") from None
        return v

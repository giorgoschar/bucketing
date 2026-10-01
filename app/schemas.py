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
from app.models import PaymentMethod, TransactionType


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
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    bucket_id: str
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

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Decimal:
        return _checked(validators.parse_amount, v, field="Amount")

    @field_validator("payment_method", mode="before")
    @classmethod
    def _payment_method(cls, v: Any) -> str:
        return parse_payment_method(v)

    @field_validator("merchant")
    @classmethod
    def _merchant(cls, v: str | None) -> str | None:
        return _clean_merchant(v)

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

    @field_validator("paid_by", "category_id", "notes", "client_id")
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
    def _splits_within_total(self) -> "TransactionCreate":
        if self.splits:
            split_total = sum(s.amount for s in self.splits)
            if split_total > self.amount:
                raise ValueError(
                    f"Split amounts ({float(split_total):.2f}) exceed the "
                    f"transaction total ({float(self.amount):.2f})."
                )
        return self

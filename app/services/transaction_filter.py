"""One filter for the Activity feed and for bulk-by-filter (2c spec §5.1),
so "N match" in a bulk preview is exactly the list on screen.

Dates and amounts stay strings in the model and are parsed here, so a bad
value is a 400 with a message, in a query string and a bulk body alike (a
typed Pydantic field would be FastAPI's 422).
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models import (
    Bucket,
    Category,
    HouseholdMember,
    PaymentMethod,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.validators import parse_year_month

LIKE_ESCAPE = "\\"


class TransactionFilter(BaseModel):
    """Every field optional; blank strings mean "not set"."""

    q: str | None = None
    type: str | None = None
    category_id: str | None = None
    bucket_id: str | None = None
    no_bucket: bool = False
    paid_by: str | None = None
    missing_payer: bool = False
    payment_method: str | None = None
    recurring_bill_id: str | None = None
    fixed: bool = False
    from_date: str | None = None
    to_date: str | None = None
    min_amount: str | None = None
    max_amount: str | None = None
    year: int | None = None
    month: int | None = None

    def is_empty(self) -> bool:
        """True when no field narrows the query. ``month`` only narrows
        together with ``year`` (alone it is a 400), so it never counts."""
        return all(
            _blank(v) if not isinstance(v, bool) else not v
            for k, v in self.model_dump(include=set(TransactionFilter.model_fields)).items()
            if k != "month"
        )


class StrictTransactionFilter(TransactionFilter):
    """A bulk body's filter: an unknown key is a 422, never silently dropped,
    so a typo can't widen what a bulk change touches."""

    model_config = ConfigDict(extra="forbid")


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def maybe_number(value) -> Decimal | None:
    """The value as a Decimal if it reads as a finite number ("42,50" too)."""
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _like(text: str) -> str:
    """A contains-pattern that matches % and _ literally."""
    for ch in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(ch, LIKE_ESCAPE + ch)
    return f"%{text}%"


def _date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{label} must be a date like 2026-10-07."
        ) from None


# Amounts are Numeric(12, 4); anything beyond this is not a real amount, and a
# literal like 1e999999 would otherwise reach Postgres as a bind value.
MAX_AMOUNT = Decimal("1e12")
_FOUR_PLACES = Decimal("0.0001")


def _amount(value: str, label: str) -> Decimal:
    d = maybe_number(value)
    if d is None or d < 0:
        raise HTTPException(status_code=400, detail=f"{label} must be a number of 0 or more.")
    if d > MAX_AMOUNT:
        raise HTTPException(status_code=400, detail=f"{label} is too large.")
    return d.quantize(_FOUR_PLACES)  # a tiny literal (1e-999999) becomes 0.0000


def _exact_amount(text: str) -> Decimal | None:
    """The amount ``q`` might name, or None when it can't be a stored amount
    (too large, or finer than 4 decimals): the exact match is then skipped."""
    d = maybe_number(text)
    if d is None or abs(d) > MAX_AMOUNT:
        return None
    d = d.normalize()
    return d if d.as_tuple().exponent >= -4 else None


def apply_filter(q: Query, f: TransactionFilter, db: Session, household_id: str) -> Query:
    """``q`` narrowed by ``f``. The caller has already limited ``q`` to the
    household (and to active rows). 400 on a bad date, amount or enum value."""
    hh = household_id
    if not _blank(f.q):
        text = f.q.strip()
        term = _like(text)
        members = db.query(HouseholdMember.user_id).filter(HouseholdMember.household_id == hh)
        conditions = [
            Transaction.notes.ilike(term, escape=LIKE_ESCAPE),
            Transaction.merchant.ilike(term, escape=LIKE_ESCAPE),
            Transaction.category_id.in_(
                db.query(Category.id)
                .filter(Category.household_id == hh, Category.name.ilike(term, escape=LIKE_ESCAPE))
                .scalar_subquery()
            ),
            Transaction.bucket_id.in_(
                db.query(Bucket.id)
                .filter(Bucket.household_id == hh, Bucket.name.ilike(term, escape=LIKE_ESCAPE))
                .scalar_subquery()
            ),
            # Payer names: members of this household only.
            Transaction.paid_by.in_(
                db.query(User.id)
                .filter(
                    User.id.in_(members.scalar_subquery()),
                    User.display_name.ilike(term, escape=LIKE_ESCAPE),
                )
                .scalar_subquery()
            ),
        ]
        exact = _exact_amount(text)
        if exact is not None:
            conditions.append(Transaction.amount == exact)  # "42.50" finds the amount
        q = q.filter(or_(*conditions))

    if not _blank(f.type):
        try:
            q = q.filter(Transaction.type == TransactionType(f.type))
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown transaction type '{f.type}'"
            ) from None
    if not _blank(f.payment_method):
        try:
            PaymentMethod(f.payment_method)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown payment method '{f.payment_method}'"
            ) from None
        q = q.filter(Transaction.payment_method == f.payment_method)
    if not _blank(f.category_id):
        q = q.filter(Transaction.category_id == f.category_id)
    if not _blank(f.bucket_id):
        q = q.filter(Transaction.bucket_id == f.bucket_id)
    if f.no_bucket:
        q = q.filter(Transaction.bucket_id.is_(None))
    if not _blank(f.recurring_bill_id):
        q = q.filter(Transaction.recurring_bill_id == f.recurring_bill_id)
    if f.fixed:
        # Fixed costs: expenses linked to an item, with no bucket (spec §5).
        q = q.filter(
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.is_(None),
            Transaction.recurring_bill_id.isnot(None),
        )
    if not _blank(f.paid_by):
        q = q.filter(
            or_(
                Transaction.paid_by == f.paid_by,
                Transaction.id.in_(
                    db.query(TransactionSplit.transaction_id)
                    .filter(TransactionSplit.user_id == f.paid_by)
                    .scalar_subquery()
                ),
            )
        )
    if f.missing_payer:
        # Own-share expenses have no payer by design and are fully paid.
        q = q.filter(Transaction.missing_payer(), Transaction.type == TransactionType.expense)

    start = None if _blank(f.from_date) else _date(f.from_date, "From date")
    end = None if _blank(f.to_date) else _date(f.to_date, "To date")
    if start and end and end < start:
        raise HTTPException(status_code=400, detail="The to date is before the from date.")
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)

    lo = None if _blank(f.min_amount) else _amount(f.min_amount, "Min amount")
    hi = None if _blank(f.max_amount) else _amount(f.max_amount, "Max amount")
    if lo is not None and hi is not None and hi < lo:
        raise HTTPException(status_code=400, detail="Max amount is below min amount.")
    if lo is not None:
        q = q.filter(Transaction.amount >= lo)
    if hi is not None:
        q = q.filter(Transaction.amount <= hi)

    parse_year_month(f.year, f.month)
    if f.month is not None and f.year is None:
        # Alone, a month would narrow nothing (and select every row in bulk).
        raise HTTPException(status_code=400, detail="Pick a year for the month.")
    if f.year and f.month:
        nxt_y, nxt_m = (f.year + 1, 1) if f.month == 12 else (f.year, f.month + 1)
        q = q.filter(
            Transaction.transaction_date >= date(f.year, f.month, 1),
            Transaction.transaction_date < date(nxt_y, nxt_m, 1),
        )
    elif f.year:
        q = q.filter(
            Transaction.transaction_date >= date(f.year, 1, 1),
            Transaction.transaction_date < date(f.year + 1, 1, 1),
        )
    return q

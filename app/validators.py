"""
Shared input validation and cross-tenant ownership checks.

Routes previously trusted client-supplied foreign keys (bucket_id, category_id,
paid_by, split user_ids). Because those ids are opaque UUIDs but not scoped by
the query, a member of household A could attach their data to household B's
bucket, or split an expense onto a user outside their household. Everything that
accepts an id from a request should run it through here.
"""
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Bucket, Category, HouseholdMember, User

# Money limits — Numeric(12, 4) tops out below 100 million.
MAX_AMOUNT = Decimal("99999999")


def parse_amount(
    raw,
    *,
    field: str = "Amount",
    allow_blank: bool = False,
    allow_zero: bool = False,
) -> Decimal | None:
    """Parse a user-supplied money value into a Decimal, or raise HTTP 400.

    Returns None for a blank value when ``allow_blank`` is set. Uses Decimal
    rather than float so amounts round-trip exactly into Numeric columns.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if allow_blank:
            return None
        raise HTTPException(status_code=400, detail=f"{field} is required.")

    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be a number.")

    if not value.is_finite():
        raise HTTPException(status_code=400, detail=f"{field} must be a number.")
    if value < 0 or (value == 0 and not allow_zero):
        raise HTTPException(status_code=400, detail=f"{field} must be greater than zero.")
    if value > MAX_AMOUNT:
        raise HTTPException(status_code=400, detail=f"{field} is too large.")

    return value.quantize(Decimal("0.0001"))


def parse_year_month(year: int | None, month: int | None) -> tuple[int | None, int | None]:
    """Validate calendar inputs before they reach date(); month=13 used to 500."""
    if year is not None and not (1970 <= year <= 2200):
        raise HTTPException(status_code=400, detail="Invalid year.")
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="Invalid month.")
    return year, month


# ---------------------------------------------------------------------------
# Ownership checks
# ---------------------------------------------------------------------------

def require_bucket(db: Session, bucket_id: str | None, hh_id: str, *, optional: bool = False) -> Bucket | None:
    """Return the bucket, asserting it belongs to this household."""
    if not bucket_id:
        if optional:
            return None
        raise HTTPException(status_code=400, detail="A bucket is required.")
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Bucket not found.")
    return bucket


def require_category(db: Session, category_id: str | None, hh_id: str) -> str | None:
    """Return the category id, asserting it belongs to this household."""
    if not category_id:
        return None
    category = db.get(Category, category_id)
    if not category or category.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Category not found.")
    return category_id


def household_member_ids(db: Session, hh_id: str) -> set[str]:
    rows = db.query(HouseholdMember.user_id).filter_by(household_id=hh_id).all()
    return {r[0] for r in rows}


def require_member(db: Session, user_id: str | None, hh_id: str) -> str | None:
    """Return the user id, asserting they are a member of this household."""
    if not user_id:
        return None
    if user_id not in household_member_ids(db, hh_id):
        raise HTTPException(status_code=400, detail="That person is not a member of this household.")
    return user_id


def validate_split_users(user_ids, hh_id: str, db: Session) -> None:
    """Assert every user in a split belongs to this household."""
    members = household_member_ids(db, hh_id)
    unknown = [u for u in user_ids if u not in members]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Splits can only be assigned to members of this household.",
        )

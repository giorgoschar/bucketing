"""
Shared input validation and cross-tenant ownership checks.

Routes previously trusted client-supplied foreign keys (bucket_id, category_id,
paid_by, split user_ids). Because those ids are opaque UUIDs but not scoped by
the query, a member of household A could attach their data to household B's
bucket, or split an expense onto a user outside their household. Everything that
accepts an id from a request should run it through here.
"""

import re
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Bucket, BucketStatus, Category, HouseholdMember

# Money limits — Numeric(12, 4) tops out below 100 million.
MAX_AMOUNT = Decimal("99999999")

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def parse_color(raw, *, field: str = "Color") -> str:
    """Validate a ``#rrggbb`` colour and return it lowercased, or raise HTTP 400.

    Colours are interpolated into inline ``style`` attributes, so anything
    looser than a plain hex value is a CSS/HTML injection vector.
    """
    value = (raw or "").strip() if isinstance(raw, str) else ""
    if not _COLOR_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{field} must look like #rrggbb.")
    return value.lower()


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
        raise HTTPException(status_code=400, detail=f"{field} must be a number.") from None

    if not value.is_finite():
        raise HTTPException(status_code=400, detail=f"{field} must be a number.")
    if value < 0 or (value == 0 and not allow_zero):
        raise HTTPException(status_code=400, detail=f"{field} must be greater than zero.")
    if value > MAX_AMOUNT:
        raise HTTPException(status_code=400, detail=f"{field} is too large.")

    return value.quantize(Decimal("0.0001"))


def validate_currency(value: str) -> str:
    """Return the currency code if the app supports it, else raise HTTP 400."""
    from app.core.config import settings

    if value not in settings.currencies:
        raise HTTPException(status_code=400, detail=f"Unsupported currency '{value}'.")
    return value


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


def require_bucket(
    db: Session, bucket_id: str | None, hh_id: str, *, optional: bool = False
) -> Bucket | None:
    """Return the bucket, asserting it belongs to this household."""
    if not bucket_id:
        if optional:
            return None
        raise HTTPException(status_code=400, detail="A bucket is required.")
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Bucket not found.")
    return bucket


def require_income_bucket(
    db: Session,
    bucket_id: str | None,
    hh_id: str,
    *,
    not_found_status: int = 404,
) -> Bucket | None:
    """The optional bucket for an income entry: None when none was chosen,
    else an active bucket of this household with "Track income" on.

    Unknown or foreign buckets answer ``not_found_status`` (the HTML form has
    always said 400); a bucket that does not take income answers 400.
    """
    if not bucket_id:
        return None
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=not_found_status, detail="Bucket not found.")
    require_takes_income(bucket)
    return bucket


def require_takes_income(bucket: Bucket) -> None:
    """HTTP 400 unless income may be put in ``bucket``: it is active and has
    "Track income" on. Income anywhere else would be saved but never counted
    in In / Net (see app.services.insights)."""
    if not bucket.show_income or bucket.status != BucketStatus.active:
        raise HTTPException(
            status_code=400,
            detail="This bucket does not track income. Leave the bucket empty or "
            'turn on "Track income" for it.',
        )


def require_category(db: Session, category_id: str | None, hh_id: str) -> str | None:
    """Return the category id, asserting it belongs to this household."""
    if not category_id:
        return None
    category = db.get(Category, category_id)
    if not category or category.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Category not found.")
    return category_id


CATEGORY_LOCKED = "This is a built-in category: it cannot be renamed, recoloured or deleted."


def require_unlocked(category: Category) -> None:
    """HTTP 403 for a built-in category (``system_key`` set, e.g. Fuel): the
    app relies on it, so it cannot be renamed, recoloured, re-iconed, merged
    or deleted. Expenses and category rules may still use it."""
    if category.is_locked:
        raise HTTPException(status_code=403, detail=CATEGORY_LOCKED)


def household_member_ids(db: Session, hh_id: str) -> set[str]:
    rows = db.query(HouseholdMember.user_id).filter_by(household_id=hh_id).all()
    return {r[0] for r in rows}


def require_member(db: Session, user_id: str | None, hh_id: str) -> str | None:
    """Return the user id, asserting they are a member of this household."""
    if not user_id:
        return None
    if user_id not in household_member_ids(db, hh_id):
        raise HTTPException(
            status_code=400, detail="That person is not a member of this household."
        )
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


# ---------------------------------------------------------------------------
# Upload sniffing
# ---------------------------------------------------------------------------

# Receipt extension -> the kind of content it must actually contain.
RECEIPT_KIND_BY_EXT = {
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".png": "png",
    ".gif": "gif",
    ".webp": "webp",
    ".pdf": "pdf",
    ".heic": "heic",
    ".heif": "heic",
}

_HEIC_BRANDS = {b"heic", b"heix", b"mif1", b"heif", b"hevc"}


def sniff_upload(head: bytes) -> str | None:
    """Detect an upload's real type from its leading bytes, or None if unknown.

    The file extension and client Content-Type are attacker-controlled; this is
    what stops an HTML/script payload being stored (and later served) as
    ``receipt.jpg``.
    """
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return "heic"
    return None


def require_receipt_content(ext: str, content: bytes) -> None:
    """Raise 400 unless the bytes really are the type the extension claims."""
    if sniff_upload(content[:16]) != RECEIPT_KIND_BY_EXT.get(ext):
        raise HTTPException(status_code=400, detail="File content does not match its type.")


def check_split_sum(amounts, bill_amount) -> None:
    """HTTP 400 unless the shares add up to the bill amount (when it has one)."""
    total = sum(amounts)
    if bill_amount is not None and round(total, 4) != round(bill_amount, 4):
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({total:.2f}) must sum to the bill amount ({float(bill_amount):.2f})",
        )

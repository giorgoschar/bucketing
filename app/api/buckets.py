"""
API buckets routes — CRUD + balance + settle.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.money import quantize
from app.models import (
    Bucket,
    BucketKind,
    BucketStatus,
    BucketType,
    ItemDirection,
    RecurringBill,
    Transaction,
)
from app.services import (
    SettlementChanged,
    get_bucket_balance,
    get_bucket_settlement,
    get_bucket_settlement_history,
    get_household_settlement,
    get_household_settlement_history,
    get_member_balances,
    record_household_settlement,
    settlement_fingerprint,
)
from app.validators import parse_amount, parse_color, validate_split_users

router = APIRouter(prefix="/buckets", tags=["buckets"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class BucketIn(BaseModel):
    name: str
    type: str = "custom"
    color: str = "#6366f1"
    icon: str = "🪣"
    budget: Decimal | None = None
    description: str | None = None
    show_income: bool = True
    enable_settlement: bool = False
    # "monthly" or "event" (spec §4.1). Given, it sets the old type to match
    # (event <-> trip), so both apps keep reading the bucket the same way.
    kind: str | None = None
    # An event's dates. Left out of an update, the stored dates stay.
    start_date: date | None = None
    end_date: date | None = None


def _apply_dates(bucket: Bucket, body: BucketIn) -> None:
    if "start_date" in body.model_fields_set:
        bucket.start_date = body.start_date
    if "end_date" in body.model_fields_set:
        bucket.end_date = body.end_date
    if bucket.start_date and bucket.end_date and bucket.end_date < bucket.start_date:
        raise HTTPException(status_code=400, detail="The end date is before the start date.")


def _type_for(body: BucketIn) -> BucketType:
    try:
        bucket_type = BucketType(body.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown bucket type '{body.type}'") from None
    if body.kind is None:
        return bucket_type
    try:
        kind = BucketKind(body.kind)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown bucket kind '{body.kind}'") from None
    if kind == BucketKind.event:
        return BucketType.trip
    return BucketType.custom if bucket_type == BucketType.trip else bucket_type


def _bucket_dict(b: Bucket, balance: dict | None = None) -> dict:
    d = {
        "id": b.id,
        "household_id": b.household_id,
        "name": b.name,
        "type": b.type.value,
        "kind": b.kind,
        "start_date": b.start_date.isoformat() if b.start_date else None,
        "end_date": b.end_date.isoformat() if b.end_date else None,
        "color": b.color,
        "icon": b.icon,
        "status": b.status.value,
        "budget": quantize(b.budget) if b.budget is not None else None,
        "description": b.description,
        "show_income": b.show_income,
        "enable_settlement": b.enable_settlement,
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }
    if balance is not None:
        d["balance"] = balance
    return d


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
def list_buckets(
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id)
        .order_by(Bucket.status, Bucket.created_at)
        .all()
    )
    return [_bucket_dict(b, get_bucket_balance(db, b.id)) for b in buckets]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_bucket(
    body: BucketIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bucket = Bucket(
        household_id=hh_id,
        name=body.name.strip(),
        type=_type_for(body),
        color=parse_color(body.color),
        icon=body.icon,
        budget=body.budget,
        description=body.description,
        show_income=body.show_income,
        enable_settlement=body.enable_settlement,
    )
    _apply_dates(bucket, body)
    db.add(bucket)
    db.commit()
    db.refresh(bucket)
    return _bucket_dict(bucket, get_bucket_balance(db, bucket.id))


@router.get("/{bucket_id}")
def get_bucket(
    bucket_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    return _bucket_dict(bucket, get_bucket_balance(db, bucket.id))


@router.put("/{bucket_id}")
def update_bucket(
    bucket_id: str,
    body: BucketIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")

    new_type = _type_for(body)
    if new_type == BucketType.trip and bucket.type != BucketType.trip:
        # An event's budget is a total over its dates; a bill is a monthly
        # cost. Don't silently strand bills inside an event (ruling 15).
        has_bills = (
            db.query(RecurringBill.id)
            .filter(
                RecurringBill.bucket_id == bucket.id,
                RecurringBill.is_active.is_(True),
                RecurringBill.direction == ItemDirection.out.value,
            )
            .first()
        )
        if has_bills:
            raise HTTPException(
                status_code=409,
                detail="This bucket has active recurring bills, so it can't become an "
                "event. Move or stop those bills first.",
            )
    bucket.name = body.name.strip()
    bucket.type = new_type
    bucket.color = parse_color(body.color)
    bucket.icon = body.icon
    bucket.budget = body.budget
    bucket.description = body.description
    bucket.show_income = body.show_income
    bucket.enable_settlement = body.enable_settlement
    _apply_dates(bucket, body)
    db.commit()
    return _bucket_dict(bucket, get_bucket_balance(db, bucket.id))


@router.delete("/{bucket_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bucket(
    bucket_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    has_txns = db.query(Transaction.id).filter(Transaction.bucket_id == bucket_id).first()
    has_bills = db.query(RecurringBill.id).filter(RecurringBill.bucket_id == bucket_id).first()
    if has_txns or has_bills:
        raise HTTPException(
            status_code=409,
            detail="This bucket has transactions or recurring bills and cannot be deleted. Archive it instead.",
        )
    db.delete(bucket)
    db.commit()


@router.post("/{bucket_id}/archive", status_code=status.HTTP_200_OK)
def archive_bucket(
    bucket_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    bucket.status = BucketStatus.archived
    db.commit()
    return _bucket_dict(bucket)


@router.get("/{bucket_id}/settlement", status_code=status.HTTP_200_OK)
def get_settlement(
    bucket_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Outstanding balances plus the history of payments already recorded."""
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    if not bucket.enable_settlement:
        raise HTTPException(status_code=400, detail="Settlement is not enabled for this bucket")

    rows = get_bucket_settlement(db, bucket_id)
    return {
        "bucket_id": bucket_id,
        "settlements": rows,
        "fingerprint": settlement_fingerprint(rows),
        "history": get_bucket_settlement_history(db, bucket_id),
    }


class SettleIn(BaseModel):
    from_user_id: str | None = None
    to_user_id: str | None = None
    amount: Decimal | None = None
    note: str | None = None
    # settlement_fingerprint of the transfers the client displayed (the
    # "fingerprint" from GET .../settlement). When sent, a mismatch → 409, so
    # a retried/double submit cannot record the same payment twice.
    expected: str | None = None


@router.post("/{bucket_id}/settle", status_code=status.HTTP_200_OK)
def settle_bucket(
    bucket_id: str,
    body: SettleIn | None = None,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Record that a debt has been paid.

    Empty body clears everything outstanding in the bucket; supplying
    from/to (and optionally amount) records one possibly-partial payment.

    This endpoint previously only *returned* the computed instructions and
    recorded nothing, so balances never reset. Use GET /settlement for a
    read-only view.
    """
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    if not bucket.enable_settlement:
        raise HTTPException(status_code=400, detail="Settlement is not enabled for this bucket")

    body = body or SettleIn()
    if bool(body.from_user_id) != bool(body.to_user_id):
        raise HTTPException(status_code=400, detail="Both from_user_id and to_user_id are required")
    if body.from_user_id and body.from_user_id == body.to_user_id:
        raise HTTPException(status_code=400, detail="from_user_id and to_user_id must differ")
    if body.from_user_id:
        validate_split_users([body.from_user_id, body.to_user_id], hh_id, db)
    if body.amount is not None:
        parse_amount(body.amount, field="amount")

    try:
        created = record_household_settlement(
            db,
            hh_id,
            bucket_id=bucket_id,
            created_by=user.id,
            from_user_id=body.from_user_id,
            to_user_id=body.to_user_id,
            amount=body.amount,
            note=body.note,
            expected=body.expected,
        )
    except SettlementChanged as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()

    return {
        "bucket_id": bucket_id,
        "recorded": [
            {
                "from_user_id": s.from_user_id,
                "to_user_id": s.to_user_id,
                "amount": quantize(s.amount),
            }
            for s in created
        ],
        "settlements": get_bucket_settlement(db, bucket_id),
    }


# ---------------------------------------------------------------------------
# Household-wide settlement
#
# Lives on this router (rather than /buckets/{id}) because it nets every
# settlement-enabled bucket together — members square up once, not per bucket.
# ---------------------------------------------------------------------------

_household_router = APIRouter(prefix="/settlement", tags=["settlement"])


@_household_router.get("")
def household_settlement(
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Outstanding household balances, per-member positions, and payment history."""
    user, hh_id = auth
    rows = get_household_settlement(db, hh_id)
    return {
        "settlements": rows,
        "fingerprint": settlement_fingerprint(rows),
        "balances": get_member_balances(db, hh_id),
        "history": get_household_settlement_history(db, hh_id),
    }


@_household_router.post("/settle")
def settle_household(
    body: SettleIn | None = None,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Record a household-wide payment. Empty body clears everything outstanding."""
    user, hh_id = auth
    body = body or SettleIn()

    if bool(body.from_user_id) != bool(body.to_user_id):
        raise HTTPException(status_code=400, detail="Both from_user_id and to_user_id are required")
    if body.from_user_id and body.from_user_id == body.to_user_id:
        raise HTTPException(status_code=400, detail="from_user_id and to_user_id must differ")
    if body.from_user_id:
        validate_split_users([body.from_user_id, body.to_user_id], hh_id, db)
    if body.amount is not None:
        parse_amount(body.amount, field="amount")

    try:
        created = record_household_settlement(
            db,
            hh_id,
            created_by=user.id,
            from_user_id=body.from_user_id,
            to_user_id=body.to_user_id,
            amount=body.amount,
            note=body.note,
            expected=body.expected,
        )
    except SettlementChanged as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return {
        "recorded": [
            {
                "from_user_id": s.from_user_id,
                "to_user_id": s.to_user_id,
                "amount": quantize(s.amount),
            }
            for s in created
        ],
        "settlements": get_household_settlement(db, hh_id),
    }

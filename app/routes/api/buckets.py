"""
API buckets routes — CRUD + balance + settle.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.models import Bucket, BucketType, BucketStatus, Transaction, TransactionType, HouseholdMember, User
from app.services import (
    get_bucket_balance, get_bucket_settlement,
    get_bucket_settlement_history, record_bucket_settlement,
    get_household_settlement, get_household_settlement_history,
    get_member_balances, record_household_settlement,
)
from app.validators import parse_amount, validate_split_users

router = APIRouter(prefix="/buckets", tags=["buckets"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BucketIn(BaseModel):
    name:              str
    type:              str   = "custom"
    color:             str   = "#6366f1"
    icon:              str   = "🪣"
    budget:            float | None = None
    description:       str   | None = None
    show_income:       bool  = True
    enable_settlement: bool  = False


def _bucket_dict(b: Bucket, balance: dict | None = None) -> dict:
    d = {
        "id":               b.id,
        "household_id":     b.household_id,
        "name":             b.name,
        "type":             b.type.value,
        "color":            b.color,
        "icon":             b.icon,
        "status":           b.status.value,
        "budget":           float(b.budget) if b.budget is not None else None,
        "description":      b.description,
        "show_income":      b.show_income,
        "enable_settlement": b.enable_settlement,
        "created_at":       b.created_at.isoformat() if b.created_at else None,
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
        type=BucketType(body.type),
        color=body.color,
        icon=body.icon,
        budget=body.budget,
        description=body.description,
        show_income=body.show_income,
        enable_settlement=body.enable_settlement,
    )
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

    bucket.name              = body.name.strip()
    bucket.type              = BucketType(body.type)
    bucket.color             = body.color
    bucket.icon              = body.icon
    bucket.budget            = body.budget
    bucket.description       = body.description
    bucket.show_income       = body.show_income
    bucket.enable_settlement = body.enable_settlement
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

    return {
        "bucket_id":   bucket_id,
        "settlements": get_bucket_settlement(db, bucket_id),
        "history":     get_bucket_settlement_history(db, bucket_id),
    }


class SettleIn(BaseModel):
    from_user_id: str | None = None
    to_user_id:   str | None = None
    amount:       float | None = None
    note:         str | None = None


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

    created = record_bucket_settlement(
        db, bucket_id, hh_id,
        created_by=user.id,
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        amount=body.amount,
        note=body.note,
    )
    db.commit()

    return {
        "bucket_id": bucket_id,
        "recorded": [
            {"from_user_id": s.from_user_id, "to_user_id": s.to_user_id,
             "amount": float(s.amount)}
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
    return {
        "settlements": get_household_settlement(db, hh_id),
        "balances":    get_member_balances(db, hh_id),
        "history":     get_household_settlement_history(db, hh_id),
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

    created = record_household_settlement(
        db, hh_id,
        created_by=user.id,
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        amount=body.amount,
        note=body.note,
    )
    db.commit()
    return {
        "recorded": [
            {"from_user_id": s.from_user_id, "to_user_id": s.to_user_id,
             "amount": float(s.amount)}
            for s in created
        ],
        "settlements": get_household_settlement(db, hh_id),
    }

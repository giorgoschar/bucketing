"""
API buckets routes — CRUD + balance + settle.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.models import Bucket, BucketType, BucketStatus, Transaction, TransactionType, HouseholdMember, User
from app.services import get_bucket_balance, get_bucket_settlement

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


@router.post("/{bucket_id}/settle", status_code=status.HTTP_200_OK)
def settle_bucket(
    bucket_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Return settlement instructions (who owes whom). Does not create transactions."""
    user, hh_id = auth
    bucket = db.query(Bucket).filter_by(id=bucket_id, household_id=hh_id).first()
    if not bucket:
        raise HTTPException(status_code=404, detail="Bucket not found")
    if not bucket.enable_settlement:
        raise HTTPException(status_code=400, detail="Settlement is not enabled for this bucket")

    settlement = get_bucket_settlement(db, bucket_id)
    return {"bucket_id": bucket_id, "settlements": settlement}

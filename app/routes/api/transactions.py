"""
API transactions routes — full CRUD + receipt scan.
"""
import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api_auth import require_api_auth
from app.database import get_db
from app.models import (
    Transaction, TransactionSplit, TransactionType,
    Bucket, BucketStatus, Category, HouseholdMember,
)
from app.receipt_parser import parse_receipt_text, match_category
from app.config import settings
from app.validators import (
    parse_amount, parse_year_month, require_category, require_member, validate_split_users,
)

UPLOADS_DIR = "uploads"
MAX_RECEIPT_SIZE = 10 * 1024 * 1024
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SplitIn(BaseModel):
    user_id: str
    amount:  float


class TransactionIn(BaseModel):
    bucket_id:    str
    amount:       float
    currency:     str   = "EUR"
    exchange_rate: float = 1.0
    type:         str   = "expense"
    paid_by:      str | None = None
    category_id:  str | None = None
    notes:        str | None = None
    transaction_date: str   = ""   # ISO date; defaults to today
    exclude_from_forecast: bool = False
    exclude_from_settlement: bool = False
    splits:       list[SplitIn] = []


def _txn_dict(t: Transaction) -> dict:
    return {
        "id":             t.id,
        "bucket_id":      t.bucket_id,
        "household_id":   t.household_id,
        "amount":         float(t.amount),
        "currency":       t.currency,
        "exchange_rate":  float(t.exchange_rate or 1),
        "type":           t.type.value,
        "paid_by":        t.paid_by,
        "category_id":    t.category_id,
        "notes":          t.notes,
        "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
        "receipt_path":   t.receipt_path,
        "exclude_from_forecast": t.exclude_from_forecast,
        "exclude_from_settlement": t.exclude_from_settlement,
        "created_at":     t.created_at.isoformat() if t.created_at else None,
        "splits": [
            {"user_id": s.user_id, "amount": float(s.amount), "is_settled": s.is_settled}
            for s in (t.splits or [])
        ],
    }


def _assert_bucket_in_household(bucket_id: str, hh_id: str, db: Session):
    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Bucket not found")


def _validate_txn_refs(body: "TransactionIn", hh_id: str, db: Session) -> None:
    """Assert category/payer/split users all belong to the caller's household.

    These ids came straight from the request body, so a client could previously
    tag a transaction with another household's category or split it onto users
    outside the household.
    """
    require_category(db, body.category_id, hh_id)
    require_member(db, body.paid_by, hh_id)
    if body.splits:
        validate_split_users([s.user_id for s in body.splits], hh_id, db)
        for s in body.splits:
            parse_amount(s.amount, field="split amount")


def _parse_body_date(value: str) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="transaction_date must be an ISO date (YYYY-MM-DD)")


def _parse_body_type(value: str) -> TransactionType:
    try:
        return TransactionType(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown transaction type '{value}'")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_transactions(
    page:        int   = Query(1, ge=1),
    page_size:   int   = Query(50, ge=1, le=200),
    bucket_id:   str   = Query(default=""),
    category_id: str   = Query(default=""),
    type:        str   = Query(default=""),
    year:        int   = Query(default=None),
    month:       int   = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    q = db.query(Transaction).filter(Transaction.household_id == hh_id)

    if bucket_id:
        q = q.filter(Transaction.bucket_id == bucket_id)
    if category_id:
        q = q.filter(Transaction.category_id == category_id)
    if type:
        try:
            q = q.filter(Transaction.type == TransactionType(type))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown transaction type '{type}'")
    parse_year_month(year, month)
    if year and month:
        start = date(year, month, 1)
        end_m = month + 1 if month < 12 else 1
        end_y = year if month < 12 else year + 1
        end   = date(end_y, end_m, 1)
        q = q.filter(Transaction.transaction_date >= start, Transaction.transaction_date < end)
    elif year:
        q = q.filter(
            Transaction.transaction_date >= date(year, 1, 1),
            Transaction.transaction_date < date(year + 1, 1, 1),
        )

    total = q.count()
    items = (
        q.options(joinedload(Transaction.splits))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "items":     [_txn_dict(t) for t in items],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: TransactionIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    _assert_bucket_in_household(body.bucket_id, hh_id, db)
    _validate_txn_refs(body, hh_id, db)

    txn_date = _parse_body_date(body.transaction_date)

    txn = Transaction(
        bucket_id=body.bucket_id,
        household_id=hh_id,
        amount=parse_amount(body.amount, field="amount"),
        currency=body.currency,
        exchange_rate=body.exchange_rate,
        type=_parse_body_type(body.type),
        paid_by=body.paid_by or user.id,
        category_id=body.category_id or None,
        notes=body.notes,
        transaction_date=txn_date,
        exclude_from_forecast=body.exclude_from_forecast,
        exclude_from_settlement=body.exclude_from_settlement,
    )
    db.add(txn)
    db.flush()

    for s in body.splits:
        db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=s.amount))

    db.commit()
    db.refresh(txn)
    return _txn_dict(txn)


@router.get("/{txn_id}")
def get_transaction(
    txn_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    txn = db.query(Transaction).options(joinedload(Transaction.splits)).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _txn_dict(txn)


@router.put("/{txn_id}")
def update_transaction(
    txn_id: str,
    body: TransactionIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    txn = db.query(Transaction).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    _assert_bucket_in_household(body.bucket_id, hh_id, db)
    _validate_txn_refs(body, hh_id, db)

    txn.bucket_id    = body.bucket_id
    txn.amount       = parse_amount(body.amount, field="amount")
    txn.currency     = body.currency
    txn.exchange_rate = body.exchange_rate
    txn.type         = _parse_body_type(body.type)
    txn.paid_by      = body.paid_by or txn.paid_by
    txn.category_id  = body.category_id or None
    txn.notes        = body.notes
    txn.exclude_from_forecast = body.exclude_from_forecast
    txn.exclude_from_settlement = body.exclude_from_settlement
    if body.transaction_date:
        txn.transaction_date = _parse_body_date(body.transaction_date)

    # Replace splits
    for s in txn.splits:
        db.delete(s)
    db.flush()
    for s in body.splits:
        db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=s.amount))

    db.commit()
    db.refresh(txn)
    return _txn_dict(txn)


@router.delete("/{txn_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    txn_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    txn = db.query(Transaction).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Remove receipt file if present
    if txn.receipt_path:
        receipt_file = Path(UPLOADS_DIR) / txn.receipt_path
        if receipt_file.is_file():
            receipt_file.unlink(missing_ok=True)

    db.delete(txn)
    db.commit()


@router.post("/{txn_id}/receipt", status_code=status.HTTP_200_OK)
async def upload_receipt(
    txn_id: str,
    file: UploadFile = File(...),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Upload or replace a receipt image/PDF for a transaction."""
    user, hh_id = auth
    txn = db.query(Transaction).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await file.read(MAX_RECEIPT_SIZE + 1)
    if len(content) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # Delete old receipt
    if txn.receipt_path:
        old = Path(UPLOADS_DIR) / txn.receipt_path
        old.unlink(missing_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    Path(UPLOADS_DIR).mkdir(exist_ok=True)
    (Path(UPLOADS_DIR) / filename).write_bytes(content)

    txn.receipt_path = filename
    db.commit()
    return {"receipt_path": filename}


@router.post("/scan/parse")
async def scan_parse(
    body: dict,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Parse raw OCR text from a receipt and return structured fields."""
    user, hh_id = auth
    text = body.get("text", "")
    if not isinstance(text, str) or len(text) > 50_000:
        raise HTTPException(status_code=400, detail="Invalid text payload")

    parsed = parse_receipt_text(text)
    categories = db.query(Category).filter_by(household_id=hh_id).all()
    category_id = match_category(parsed["category_hint"], categories)

    return {
        "amount":         parsed["amount"],
        "currency":       parsed["currency"],
        "date":           parsed["date"],
        "merchant":       parsed["merchant"],
        "category_hint":  parsed["category_hint"],
        "category_id":    category_id,
    }

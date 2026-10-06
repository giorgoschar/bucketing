"""
API transactions routes — full CRUD + receipt scan.
"""
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session, joinedload

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.money import quantize
from app.models import (
    Category,
    PayerMode,
    Transaction,
    TransactionType,
)
from app.schemas import TransactionCreate, TransactionUpdate
from app.services import DeletedTransactionReplay, DuplicateTransaction
from app.services import create_transaction as create_transaction_service
from app.services import delete_transaction as delete_transaction_soft
from app.services import update_transaction as update_transaction_service
from app.services.receipt_parser import match_category, parse_receipt_text
from app.validators import (
    parse_year_month,
    require_bucket,
    require_receipt_content,
)

UPLOADS_DIR = "uploads"
MAX_RECEIPT_SIZE = 10 * 1024 * 1024
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".heic", ".heif"}

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

def _txn_dict(t: Transaction) -> dict:
    return {
        "id":             t.id,
        "bucket_id":      t.bucket_id,
        "household_id":   t.household_id,
        "amount":         quantize(t.amount),
        "currency":       t.currency,
        "exchange_rate":  float(t.exchange_rate or 1),
        "type":           t.type.value,
        "paid_by":        t.paid_by,
        "payer_mode":     t.payer_mode,
        "category_id":    t.category_id,
        "notes":          t.notes,
        "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
        "receipt_path":   t.receipt_path,
        "payment_method": t.payment_method,
        "merchant":       t.merchant,
        "fuel_price_per_litre": t.fuel_price_per_litre,
        "fuel_litres":    t.fuel_litres,
        "exclude_from_forecast": t.exclude_from_forecast,
        "exclude_from_settlement": t.exclude_from_settlement,
        "created_at":     t.created_at.isoformat() if t.created_at else None,
        "splits": [
            {"user_id": s.user_id, "amount": quantize(s.amount), "is_settled": s.is_settled}
            for s in (t.splits or [])
        ],
    }


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
    q = db.query(Transaction).filter(Transaction.active(), Transaction.household_id == hh_id)

    if bucket_id:
        q = q.filter(Transaction.bucket_id == bucket_id)
    if category_id:
        q = q.filter(Transaction.category_id == category_id)
    if type:
        try:
            q = q.filter(Transaction.type == TransactionType(type))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown transaction type '{type}'") from None
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
    body: TransactionCreate,
    response: Response,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    # Optional for income only; the schema and service enforce the rest.
    bucket = require_bucket(db, body.bucket_id, hh_id, optional=True)
    if body.payer_mode != PayerMode.own_share.value:
        body.paid_by = body.paid_by or user.id

    try:
        txn = create_transaction_service(
            db, household_id=hh_id, bucket=bucket, user=user, data=body,
        )
    except DeletedTransactionReplay:
        raise HTTPException(
            status_code=409,
            detail="This transaction was already submitted and has since been deleted.",
        ) from None
    except DuplicateTransaction as dup:
        # Idempotent replay: same body shape as a create, never a second row.
        response.status_code = status.HTTP_200_OK
        return _txn_dict(dup.existing)
    return _txn_dict(txn)


@router.get("/{txn_id}")
def get_transaction(
    txn_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    txn = db.query(Transaction).options(joinedload(Transaction.splits)).filter(Transaction.active()).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _txn_dict(txn)


@router.put("/{txn_id}")
def update_transaction(
    txn_id: str,
    body: TransactionUpdate,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Replace a transaction. Validated exactly like create (422 on bad input);
    a blank payer keeps the current one (and, with no ``payer_mode`` given, its
    mode), a blank date keeps the current date."""
    user, hh_id = auth
    txn = db.query(Transaction).filter(Transaction.active()).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    require_bucket(db, body.bucket_id, hh_id, optional=True)
    if body.payer_mode is None:
        # Naming a payer means a single payer; otherwise keep the stored mode.
        body.payer_mode = PayerMode.single.value if body.paid_by else txn.payer_mode
    if body.payer_mode == PayerMode.own_share.value:
        body.paid_by = None
    else:
        body.paid_by = body.paid_by or txn.paid_by
    update_transaction_service(db, txn, household_id=hh_id, user=user, data=body)
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
    txn = db.query(Transaction).filter(Transaction.active()).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Soft delete: the row and splits stay, the receipt moves to uploads/.trash.
    delete_transaction_soft(db, txn, UPLOADS_DIR)
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
    txn = db.query(Transaction).filter(Transaction.active()).filter_by(id=txn_id, household_id=hh_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    content = await file.read(MAX_RECEIPT_SIZE + 1)
    if len(content) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
    require_receipt_content(ext, content)

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

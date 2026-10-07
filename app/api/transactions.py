"""
API transactions routes — full CRUD + receipt scan.
"""

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.api.transaction_models import TransactionOut, TransactionPage
from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.money import quantize
from app.models import (
    CashMovement,
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
from app.services.money import base_amount_expr
from app.services.receipt_parser import match_category, parse_receipt_text
from app.services.transaction_filter import TransactionFilter, apply_filter
from app.validators import (
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
        "id": t.id,
        "bucket_id": t.bucket_id,
        "household_id": t.household_id,
        "amount": quantize(t.amount),
        "currency": t.currency,
        "exchange_rate": float(t.exchange_rate or 1),
        "type": t.type.value,
        "paid_by": t.paid_by,
        "payer_mode": t.payer_mode,
        "category_id": t.category_id,
        "notes": t.notes,
        "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
        "receipt_path": t.receipt_path,
        "payment_method": t.payment_method,
        "merchant": t.merchant,
        "fuel_price_per_litre": t.fuel_price_per_litre,
        "fuel_litres": t.fuel_litres,
        "exclude_from_forecast": t.exclude_from_forecast,
        "exclude_from_settlement": t.exclude_from_settlement,
        "recurring_bill_id": t.recurring_bill_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "splits": [
            {"user_id": s.user_id, "amount": quantize(s.amount), "is_settled": s.is_settled}
            for s in (t.splits or [])
        ],
    }


class FeedQuery(TransactionFilter):
    """The feed's query string: the shared filter plus paging."""

    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


def _takes(db: Session, ids: list[str]) -> set[str]:
    """Which of ``ids`` have an active linked cash take (one query)."""
    if not ids:
        return set()
    return {
        i
        for (i,) in db.query(CashMovement.transaction_id).filter(
            CashMovement.transaction_id.in_(ids), CashMovement.active()
        )
    }


def transaction_out(t: Transaction, has_take: bool) -> dict:
    d = _txn_dict(t)
    d["has_take"] = has_take
    d["missing_payer"] = (
        t.type == TransactionType.expense
        and (t.payer_mode or PayerMode.single.value) == PayerMode.single.value
        and t.paid_by is None
    )
    return d


def _day_totals(filtered, dates: list[date]) -> dict[str, Decimal]:
    """Net per date over the whole filtered set, not just this page's rows."""
    totals = {d.isoformat(): Decimal(0) for d in dates}
    if not dates:
        return totals
    signed = case(
        (Transaction.type == TransactionType.income, base_amount_expr()),
        else_=-base_amount_expr(),
    )
    rows = (
        filtered.filter(
            Transaction.type != TransactionType.transfer,
            Transaction.transaction_date.in_(dates),
        )
        .with_entities(Transaction.transaction_date, func.sum(signed))
        .group_by(Transaction.transaction_date)
        .all()
    )
    for day, total in rows:
        totals[day.isoformat()] = quantize(total)
    return totals


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=TransactionPage)
def list_transactions(
    f: Annotated[FeedQuery, Query()],
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """The Activity feed (2c spec §5.1): the shared TransactionFilter, 50 a
    page (max 200), newest first, with each shown day's net."""
    user, hh_id = auth
    filtered = apply_filter(
        db.query(Transaction).filter(Transaction.active(), Transaction.household_id == hh_id),
        f,
        db,
        hh_id,
    )
    total = filtered.count()
    items = (
        filtered.options(joinedload(Transaction.splits))
        .order_by(
            Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id
        )
        .offset((f.page - 1) * f.page_size)
        .limit(f.page_size)
        .all()
    )
    takes = _takes(db, [t.id for t in items])
    return {
        "total": total,
        "page": f.page,
        "page_size": f.page_size,
        "items": [transaction_out(t, t.id in takes) for t in items],
        "day_totals": _day_totals(filtered, sorted({t.transaction_date for t in items})),
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
            db,
            household_id=hh_id,
            bucket=bucket,
            user=user,
            data=body,
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


@router.get("/{txn_id}", response_model=TransactionOut)
def get_transaction(
    txn_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    txn = (
        db.query(Transaction)
        .options(joinedload(Transaction.splits))
        .filter(Transaction.active())
        .filter_by(id=txn_id, household_id=hh_id)
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction_out(txn, bool(_takes(db, [txn.id])))


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
    txn = (
        db.query(Transaction)
        .filter(Transaction.active())
        .filter_by(id=txn_id, household_id=hh_id)
        .first()
    )
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
    txn = (
        db.query(Transaction)
        .filter(Transaction.active())
        .filter_by(id=txn_id, household_id=hh_id)
        .first()
    )
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
    txn = (
        db.query(Transaction)
        .filter(Transaction.active())
        .filter_by(id=txn_id, household_id=hh_id)
        .first()
    )
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
        "amount": parsed["amount"],
        "currency": parsed["currency"],
        "date": parsed["date"],
        "merchant": parsed["merchant"],
        "category_hint": parsed["category_hint"],
        "category_id": category_id,
    }

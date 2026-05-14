"""
Transactions routes: add expense wizard + CRUD.
"""
import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import (
    Transaction, TransactionSplit, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.templates import templates
from app.receipt_parser import parse_receipt_text, match_category

router = APIRouter(prefix="/transactions")

UPLOADS_DIR = "uploads"


# ---------------------------------------------------------------------------
# Authenticated file download (replaces the old public /uploads static mount)
# ---------------------------------------------------------------------------

@router.get("/files/{filename}", response_class=FileResponse)
def serve_receipt(
    filename: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    # Security: verify that a transaction in this household owns this file
    txn = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == hh_id,
            Transaction.receipt_path == filename,
        )
        .first()
    )
    if not txn:
        raise HTTPException(status_code=404)

    file_path = Path(UPLOADS_DIR) / filename
    if not file_path.is_file():
        raise HTTPException(status_code=404)

    return FileResponse(str(file_path))


# ---------------------------------------------------------------------------
# Receipt scan — on-device OCR (Tesseract.js), server parses raw text
# ---------------------------------------------------------------------------

@router.get("/scan", response_class=HTMLResponse)
def scan_receipt_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)
    ctx.update({"request": request, "user": user})
    return templates.TemplateResponse("transactions/scan.html", ctx)


@router.post("/scan/parse", response_class=JSONResponse)
async def parse_scan(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    body = await request.json()
    text = body.get("text", "")
    if not isinstance(text, str) or len(text) > 50_000:
        raise HTTPException(status_code=400, detail="Invalid text payload")

    parsed = parse_receipt_text(text)

    # Map category hint to an actual category in this household
    categories = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .all()
    )
    category_id = match_category(parsed["category_hint"], categories)

    return {
        "amount": parsed["amount"],
        "currency": parsed["currency"],
        "date": parsed["date"],
        "merchant": parsed["merchant"],
        "category_hint": parsed["category_hint"],
        "category_id": category_id,
    }


def _get_context(db: Session, user, hh_id: str) -> dict:
    """Common template context for transaction forms."""
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=hh_id, status=BucketStatus.active)
        .all()
    )
    categories = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .order_by(Category.is_default.desc(), Category.name)
        .all()
    )
    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .all()
    )
    household = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]

    return {
        "buckets": buckets,
        "categories": categories,
        "members": members,
        "household": household,
        "households": households,
        "currencies": ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD", "SEK", "NOK", "DKK"],
        "today": date.today().isoformat(),
    }


# ---------------------------------------------------------------------------
# Add expense wizard
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
def new_transaction(
    request: Request,
    bucket_id: str = None,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)

    # If a bucket is pre-selected, respect its show_income setting
    show_income = True
    if bucket_id:
        pre_bucket = db.get(Bucket, bucket_id)
        if pre_bucket and pre_bucket.household_id == hh_id:
            show_income = pre_bucket.show_income

    ctx.update({
        "request": request,
        "user": user,
        "selected_bucket_id": bucket_id or "",
        "show_income": show_income,
        "step": 1,
    })
    return templates.TemplateResponse("transactions/new.html", ctx)


@router.post("", response_class=HTMLResponse)
async def create_transaction(
    request: Request,
    bucket_id: str = Form(...),
    transaction_date: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("EUR"),
    exchange_rate: float = Form(1.0),
    type: str = Form("expense"),
    category_id: str = Form(""),
    paid_by: str = Form(""),
    notes: str = Form(""),
    is_shared: str = Form("off"),
    receipt: UploadFile = File(None),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    bucket = db.get(Bucket, bucket_id)
    if not bucket or bucket.household_id != hh_id:
        raise HTTPException(status_code=400, detail="Invalid bucket")

    receipt_path = None
    if receipt and receipt.filename:
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        ext = os.path.splitext(receipt.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(UPLOADS_DIR, filename)
        content = await receipt.read()
        with open(filepath, "wb") as f:
            f.write(content)
        receipt_path = filepath

    txn = Transaction(
        bucket_id=bucket_id,
        household_id=hh_id,
        amount=amount,
        currency=currency,
        exchange_rate=exchange_rate,
        type=TransactionType(type),
        paid_by=paid_by or None,
        category_id=category_id or None,
        notes=notes.strip() or None,
        transaction_date=date.fromisoformat(transaction_date),
        receipt_path=receipt_path,
    )
    db.add(txn)
    db.flush()

    # Handle splits if shared
    if is_shared == "on":
        split_data = await _parse_splits(request, txn.id, amount, hh_id, db)
        for split in split_data:
            db.add(split)

    db.commit()

    # HTMX: if triggered from wizard, swap to success partial; else redirect
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/transaction_added.html",
            {"request": request, "transaction": txn, "bucket": bucket},
        )
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)


async def _parse_splits(request: Request, txn_id: str, total: float, hh_id: str, db: Session):
    form = await request.form()
    splits = []
    for key, value in form.items():
        if key.startswith("split_"):
            user_id = key[6:]
            try:
                share = float(value)
                if share > 0:
                    splits.append(TransactionSplit(
                        transaction_id=txn_id,
                        user_id=user_id,
                        amount=share,
                    ))
            except (ValueError, TypeError):
                pass
    return splits


# ---------------------------------------------------------------------------
# Edit / Delete
# ---------------------------------------------------------------------------

@router.get("/{txn_id}/edit", response_class=HTMLResponse)
def edit_transaction_page(
    txn_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    txn = db.get(Transaction, txn_id)
    if not txn or txn.household_id != hh_id:
        raise HTTPException(status_code=404)

    ctx = _get_context(db, user, hh_id)
    ctx.update({
        "request": request,
        "user": user,
        "txn": txn,
    })
    return templates.TemplateResponse("transactions/edit.html", ctx)


@router.post("/{txn_id}/edit", response_class=HTMLResponse)
async def edit_transaction(
    txn_id: str,
    request: Request,
    bucket_id: str = Form(...),
    transaction_date: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("EUR"),
    exchange_rate: float = Form(1.0),
    type: str = Form("expense"),
    category_id: str = Form(""),
    paid_by: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    txn = db.get(Transaction, txn_id)
    if not txn or txn.household_id != hh_id:
        raise HTTPException(status_code=404)

    txn.bucket_id = bucket_id
    txn.transaction_date = date.fromisoformat(transaction_date)
    txn.amount = amount
    txn.currency = currency
    txn.exchange_rate = exchange_rate
    txn.type = TransactionType(type)
    txn.paid_by = paid_by or None
    txn.category_id = category_id or None
    txn.notes = notes.strip() or None
    db.commit()

    return RedirectResponse(f"/buckets/{txn.bucket_id}", status_code=302)


@router.post("/{txn_id}/delete", response_class=HTMLResponse)
def delete_transaction(
    txn_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    txn = db.get(Transaction, txn_id)
    if not txn or txn.household_id != hh_id:
        raise HTTPException(status_code=404)

    bucket_id = txn.bucket_id
    db.delete(txn)
    db.commit()

    if request.headers.get("HX-Request"):
        return HTMLResponse("")  # HTMX removes the row
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)

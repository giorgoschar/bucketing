"""
Transactions routes: add expense wizard + CRUD.
"""
import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth import require_auth, require_csrf
from app.category_rules import learn_rule
from app.clock import local_today
from app.config import settings
from app.database import get_db
from app.models import (
    Bucket,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.schemas import TransactionCreate, _clean_merchant, parse_payment_method
from app.services import (
    DeletedTransactionReplay,
    DuplicateTransaction,
)
from app.services import create_transaction as create_transaction_service
from app.services import delete_transaction as delete_transaction_soft
from app.services import full_ctx as _full_ctx
from app.templates import templates
from app.validators import (
    parse_amount,
    require_bucket,
    require_category,
    require_member,
    validate_currency,
    validate_split_users,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", dependencies=[Depends(require_csrf)])

UPLOADS_DIR = "uploads"
MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".heic", ".heif"}


def _maybe_number(value: str):
    """Return the value as a Decimal if it looks like a number, else None."""
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(value.strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        return None


def _parse_txn_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Date must be a valid date (YYYY-MM-DD).") from None


def _parse_txn_type(value: str) -> TransactionType:
    try:
        return TransactionType(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown transaction type '{value}'.") from None


def _parse_rate(value) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Exchange rate must be a number.") from None
    if not (0 < rate <= 1_000_000):
        raise HTTPException(status_code=400, detail="Exchange rate is out of range.")
    return rate


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
            Transaction.active(),
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


def _get_context(db: Session, user, hh_id: str) -> dict:
    """Common template context for transaction forms."""
    ctx = _full_ctx(db, user, hh_id)
    ctx["currencies"] = settings.currencies
    ctx["today"] = local_today().isoformat()
    return ctx


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
    amount: str = Form(...),
    currency: str = Form("EUR"),
    exchange_rate: str = Form("1"),
    type: str = Form("expense"),
    category_id: str = Form(""),
    paid_by: str = Form(""),
    notes: str = Form(""),
    is_shared: str = Form("off"),
    merchant: str = Form(""),
    payment_method: str = Form("card"),
    remember_rule: str = Form(""),
    client_id: str = Form(""),
    receipt: UploadFile = File(None),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    bucket = require_bucket(db, bucket_id, hh_id)
    shared = is_shared == "on"

    splits = await _parse_split_fields(request) if shared else []
    try:
        data = TransactionCreate(
            bucket_id=bucket_id,
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            type=type,
            paid_by=paid_by,
            category_id=category_id,
            notes=notes,
            transaction_date=transaction_date,
            splits=splits,
            client_id=client_id,
            payment_method=payment_method,
            merchant=merchant,
        )
    except ValidationError as exc:
        # Keep the form's user-facing error rendering (HTTPException handler).
        raise HTTPException(status_code=400, detail=_first_error(exc)) from None

    try:
        # Sync DB + upload I/O: keep it off the event loop.
        txn = await run_in_threadpool(
            create_transaction_service,
            db, household_id=hh_id, bucket=bucket, user=user,
            data=data, receipt=receipt, is_shared=shared,
        )
    except DeletedTransactionReplay:
        # Do not silently resurrect or duplicate a deleted expense.
        raise HTTPException(
            status_code=409,
            detail="This expense was already submitted and has since been deleted.",
        ) from None
    except DuplicateTransaction as dup:
        # Offline replay after a lost response: answer as if it just succeeded.
        txn = dup.existing
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "partials/transaction_added.html",
                {"request": request, "transaction": txn, "bucket": bucket},
            )
        return RedirectResponse(f"/buckets/{txn.bucket_id}", status_code=302)

    # Teach the categorisation rule from a scan: correcting a merchant's
    # category once makes it stick for next time.
    if remember_rule == "on" and txn.category_id:
        try:
            learn_rule(db, hh_id, merchant or notes, txn.category_id,
                       created_by=user.id)
            db.commit()
        except Exception:
            # A convenience rule must never fail an expense that is already saved.
            db.rollback()
            logger.warning("Could not learn categorisation rule", exc_info=True)

    # HTMX: if triggered from wizard, swap to success partial; else redirect
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/transaction_added.html",
            {"request": request, "transaction": txn, "bucket": bucket},
        )
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)


def _first_error(exc: ValidationError) -> str:
    msg = exc.errors()[0]["msg"]
    return msg.removeprefix("Value error, ")


async def _parse_split_fields(request: Request) -> list[dict]:
    """Collect split_{user_id} form fields as SplitIn-shaped dicts.

    Blank and zero shares are skipped. Household membership and the
    "splits must not exceed the total" rule are enforced by the shared
    TransactionCreate model / create_transaction service.
    """
    form = await request.form()
    parsed: list[dict] = []
    for key, value in form.items():
        if not key.startswith("split_") or not str(value).strip():
            continue
        share = parse_amount(value, field="Split amount", allow_blank=True)
        if share and share > 0:
            parsed.append({"user_id": key[6:], "amount": share})
    return parsed


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
    if not txn or txn.household_id != hh_id or txn.deleted_at is not None:
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
    exclude_from_forecast: str = Form(""),
    exclude_from_settlement: str = Form(""),
    payment_method: str = Form("card"),
    merchant: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    txn = db.get(Transaction, txn_id)
    if not txn or txn.household_id != hh_id or txn.deleted_at is not None:
        raise HTTPException(status_code=404)

    # The target bucket was previously assigned straight from the form, so a
    # member could move a transaction into any household's bucket by guessing
    # or leaking an id.
    require_bucket(db, bucket_id, hh_id)

    txn.bucket_id = bucket_id
    txn.transaction_date = _parse_txn_date(transaction_date)
    txn.amount = parse_amount(amount, field="Amount")
    txn.currency = validate_currency(currency)
    txn.exchange_rate = _parse_rate(exchange_rate)
    txn.type = _parse_txn_type(type)
    txn.paid_by = require_member(db, paid_by, hh_id)
    txn.category_id = require_category(db, category_id, hh_id)
    txn.notes = notes.strip() or None
    try:
        txn.payment_method = parse_payment_method(payment_method)
        txn.merchant = _clean_merchant(merchant)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    txn.exclude_from_forecast = (exclude_from_forecast == "on")
    txn.exclude_from_settlement = (exclude_from_settlement == "on")

    # Replace splits
    db.query(TransactionSplit).filter_by(transaction_id=txn.id).delete(synchronize_session=False)
    form_data = await request.form()
    splits: list[tuple[str, object]] = []
    for key, value in form_data.items():
        if key.startswith("split_") and str(value).strip():
            split_amount = parse_amount(value, field="Split amount", allow_blank=True)
            if split_amount and split_amount > 0:
                splits.append((key[6:], split_amount))
    if splits:
        validate_split_users([uid for uid, _ in splits], hh_id, db)
        for uid, split_amount in splits:
            db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=split_amount))

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
    if not txn or txn.household_id != hh_id or txn.deleted_at is not None:
        raise HTTPException(status_code=404)

    bucket_id = txn.bucket_id
    delete_transaction_soft(db, txn, UPLOADS_DIR)
    db.commit()

    if request.headers.get("HX-Request"):
        return HTMLResponse("")  # HTMX removes the row
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)


# ---------------------------------------------------------------------------
# Duplicate transaction
# ---------------------------------------------------------------------------

@router.post("/{txn_id}/duplicate", response_class=HTMLResponse)
def duplicate_transaction(
    txn_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    src = db.get(Transaction, txn_id)
    if not src or src.household_id != hh_id or src.deleted_at is not None:
        raise HTTPException(status_code=404)

    new_txn = Transaction(
        bucket_id=src.bucket_id,
        household_id=src.household_id,
        amount=src.amount,
        currency=src.currency,
        exchange_rate=src.exchange_rate,
        type=src.type,
        paid_by=src.paid_by,
        category_id=src.category_id,
        notes=src.notes,
        payment_method=src.payment_method,
        merchant=src.merchant,
        transaction_date=local_today(),
        exclude_from_forecast=src.exclude_from_forecast,
        exclude_from_settlement=src.exclude_from_settlement,
    )
    db.add(new_txn)
    db.commit()

    if request.headers.get("HX-Request"):
        bucket = db.get(Bucket, new_txn.bucket_id)
        return templates.TemplateResponse(
            "partials/transaction_added.html",
            {"request": request, "transaction": new_txn, "bucket": bucket},
        )
    return RedirectResponse(f"/buckets/{src.bucket_id}", status_code=302)


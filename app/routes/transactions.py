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
from app.core.clock import local_today
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Bucket,
    Category,
    PayerMode,
    Transaction,
    TransactionSplit,
)
from app.schemas import TransactionCreate, TransactionUpdate, payer_choice
from app.services import (
    DeletedTransactionReplay,
    DuplicateTransaction,
    after_save_url,
    last_payment_method,
)
from app.services import create_transaction as create_transaction_service
from app.services import delete_transaction as delete_transaction_soft
from app.services import full_ctx as _full_ctx
from app.services import update_transaction as update_transaction_service
from app.services.cash import has_linked_take
from app.services.category_rules import learn_rule
from app.templates import templates
from app.validators import (
    parse_amount,
    require_bucket,
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


def _edit_context(db: Session, user, hh_id: str, txn: Transaction) -> dict:
    """The form context for editing ``txn``. Its bucket is listed even when
    archived: with only active buckets no option was selected, so the browser
    picked the first one and saving silently moved (or, for income, detached)
    the row, or failed for an expense."""
    ctx = _get_context(db, user, hh_id)
    if txn.bucket is not None and txn.bucket not in ctx["buckets"]:
        ctx["buckets"] = [*ctx["buckets"], txn.bucket]
    # "I took this from my stash": the take follows the expense's edits.
    ctx["linked_take"] = has_linked_take(db, txn.id)
    return ctx


# ---------------------------------------------------------------------------
# Add expense wizard
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
def new_transaction(
    request: Request,
    bucket_id: str = None,
    amount: str = "",
    category_id: str = "",
    notes: str = "",
    merchant: str = "",
    currency: str = "",
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)

    # Optional prefill from links (e.g. stock "Mark bought"). Invalid values
    # are dropped rather than rejected; nothing here is saved until submit.
    try:
        amt = parse_amount(amount, allow_blank=True)
    except HTTPException:
        amt = None
    cat = db.get(Category, category_id) if category_id else None
    prefill = {
        "amount": f"{amt:.2f}" if amt is not None else "",
        "category_id": cat.id if cat is not None and cat.household_id == hh_id else "",
        "notes": notes.strip()[:500],
        "merchant": merchant.strip()[:200],
    }
    if currency.strip().upper() in settings.currencies:
        prefill["currency"] = currency.strip().upper()

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
        "prefill": prefill,
        # Paid the way they paid last time: most expenses repeat the method.
        "default_payment_method": last_payment_method(db, hh_id, user.id),
        "show_income": show_income,
        "step": 1,
    })
    return templates.TemplateResponse("transactions/new.html", ctx)


@router.post("", response_class=HTMLResponse)
async def create_transaction(
    request: Request,
    bucket_id: str = Form(""),
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
    took_cash: str = Form(""),
    take_from: str = Form(""),
    fuel_price_per_litre: str = Form(""),
    remember_rule: str = Form(""),
    client_id: str = Form(""),
    receipt: UploadFile = File(None),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    # Only income may be bucket-less (the schema and service enforce it).
    bucket = require_bucket(db, bucket_id, hh_id, optional=True)
    shared = is_shared == "on"
    # "Each paid their own share" arrives as a value of the payer dropdown.
    payer, payer_mode = payer_choice(paid_by)
    own_share = payer_mode == PayerMode.own_share.value

    # Own share is meaningless without the shares, so read them even if the
    # shared toggle was switched off.
    splits = await _parse_split_fields(request) if shared or own_share else []
    try:
        data = TransactionCreate(
            bucket_id=bucket_id,
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            type=type,
            paid_by=payer,
            payer_mode=payer_mode,
            category_id=category_id,
            notes=notes,
            transaction_date=transaction_date,
            splits=splits,
            client_id=client_id,
            payment_method=payment_method,
            merchant=merchant,
            # "I took this from my stash": only for cash (the hidden input
            # still posts "on" if the box was ticked before switching to card).
            took_cash=(took_cash == "on" and payment_method == "cash"),
            take_from=take_from,
            # Kept only for the fuel category; litres are computed server-side.
            fuel_price_per_litre=fuel_price_per_litre,
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
        return RedirectResponse(after_save_url(txn.bucket_id), status_code=302)

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
    return RedirectResponse(after_save_url(txn.bucket_id), status_code=302)


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

    ctx = _edit_context(db, user, hh_id, txn)
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
    bucket_id: str = Form(""),
    transaction_date: str = Form(...),
    amount: str = Form(...),
    currency: str = Form("EUR"),
    exchange_rate: str = Form("1"),
    type: str = Form("expense"),
    category_id: str = Form(""),
    paid_by: str = Form(""),
    notes: str = Form(""),
    exclude_from_forecast: str = Form(""),
    exclude_from_settlement: str = Form(""),
    payment_method: str = Form("card"),
    merchant: str = Form(""),
    is_shared: str = Form(""),
    fuel_price_per_litre: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    txn = db.get(Transaction, txn_id)
    if not txn or txn.household_id != hh_id or txn.deleted_at is not None:
        raise HTTPException(status_code=404)

    # The target bucket was previously assigned straight from the form, so a
    # member could move a transaction into any household's bucket by guessing
    # or leaking an id. Blank is allowed for income only (checked below).
    require_bucket(db, bucket_id, hh_id, optional=True)

    # Same field validation as create (TransactionCreate): currency, rate > 0,
    # Decimal amounts, splits <= total, payment method, own-share splits.
    payer, payer_mode = payer_choice(paid_by)
    # The shared toggle: "on" splits blank shares equally, "off" means no split
    # (its hidden inputs still post their old values, so they are not read),
    # absent (a form from before the toggle was posted) keeps the old reading.
    shared = {"on": True, "off": False}.get(is_shared)
    own_share = payer_mode == PayerMode.own_share.value
    splits = await _parse_split_fields(request) if shared is not False or own_share else []
    try:
        data = TransactionUpdate(
            bucket_id=bucket_id,
            amount=amount,
            currency=currency,
            exchange_rate=exchange_rate,
            type=type,
            paid_by=payer,
            payer_mode=payer_mode,
            category_id=category_id,
            notes=notes,
            transaction_date=_parse_txn_date(transaction_date),
            splits=splits,
            payment_method=payment_method,
            merchant=merchant,
            # Always passed, so a blank field clears the price (an omitted one
            # would keep it, see TransactionUpdate).
            fuel_price_per_litre=fuel_price_per_litre,
            exclude_from_forecast=(exclude_from_forecast == "on"),
            exclude_from_settlement=(exclude_from_settlement == "on"),
        )
    except ValidationError as exc:
        ctx = _edit_context(db, user, hh_id, txn)
        ctx.update({"request": request, "user": user, "txn": txn, "error": _first_error(exc)})
        return templates.TemplateResponse("transactions/edit.html", ctx, status_code=400)

    update_transaction_service(db, txn, household_id=hh_id, user=user, data=data,
                               is_shared=shared)
    db.commit()

    return RedirectResponse(after_save_url(txn.bucket_id), status_code=302)


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
    return RedirectResponse(after_save_url(bucket_id), status_code=302)


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
        payer_mode=src.payer_mode,
        category_id=src.category_id,
        notes=src.notes,
        payment_method=src.payment_method,
        merchant=src.merchant,
        fuel_price_per_litre=src.fuel_price_per_litre,
        fuel_litres=src.fuel_litres,
        transaction_date=local_today(),
        exclude_from_forecast=src.exclude_from_forecast,
        exclude_from_settlement=src.exclude_from_settlement,
    )
    db.add(new_txn)
    db.flush()
    # An own-share expense is defined by its splits (who paid what), so the
    # copy needs them too; a single-payer copy stays unsplit as before.
    if src.payer_mode == PayerMode.own_share.value:
        for s in src.splits:
            db.add(TransactionSplit(transaction_id=new_txn.id, user_id=s.user_id, amount=s.amount))
    db.commit()

    if request.headers.get("HX-Request"):
        bucket = db.get(Bucket, new_txn.bucket_id) if new_txn.bucket_id else None
        return templates.TemplateResponse(
            "partials/transaction_added.html",
            {"request": request, "transaction": new_txn, "bucket": bucket},
        )
    return RedirectResponse(after_save_url(src.bucket_id), status_code=302)


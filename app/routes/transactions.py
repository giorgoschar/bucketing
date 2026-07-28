"""
Transactions routes: add expense wizard + CRUD.
"""
import csv
import io
import os
import re
import uuid
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Form, Query, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.auth import require_auth, require_csrf
from app.models import (
    Transaction, TransactionSplit, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.templates import templates
from app.receipt_parser import parse_receipt_text, match_category, _extract_category_hint
from app.category_rules import learn_rule, resolve_category
from app.config import settings
from app.services import full_ctx as _full_ctx
from app.services import find_duplicate_candidates, find_household_duplicates
from app.validators import (
    parse_amount, parse_year_month, require_bucket, require_category,
    require_member, validate_split_users,
)

router = APIRouter(prefix="/transactions", dependencies=[Depends(require_csrf)])

UPLOADS_DIR = "uploads"
MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}


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
        raise HTTPException(status_code=400, detail="Date must be a valid date (YYYY-MM-DD).")


def _parse_txn_type(value: str) -> TransactionType:
    try:
        return TransactionType(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown transaction type '{value}'.")


def _validate_currency(value: str) -> str:
    if value not in settings.currencies:
        raise HTTPException(status_code=400, detail=f"Unsupported currency '{value}'.")
    return value


def _parse_rate(value) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Exchange rate must be a number.")
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

    # Household rules take precedence over the built-in keyword guess.
    category_id = resolve_category(
        db, hh_id,
        merchant=parsed["merchant"],
        hint=parsed["category_hint"],
        raw_text=text,
    )
    db.commit()  # persists match_count bookkeeping

    return {
        "amount": parsed["amount"],
        "currency": parsed["currency"],
        "date": parsed["date"],
        "merchant": parsed["merchant"],
        "category_hint": parsed["category_hint"],
        "category_id": category_id,
    }


# ---------------------------------------------------------------------------
# QR-code → AADE lookup
# ---------------------------------------------------------------------------

# SSRF guard values come from settings so the host/path can be overridden via
# env vars without a redeploy (e.g. if AADE changes their URL).
_AADE_HOST = settings.aade_host
_AADE_PATH_PREFIX = settings.aade_path_prefix


class _AADEParser(HTMLParser):
    """Extract label→value pairs from AADE receipt verification table."""

    def __init__(self):
        super().__init__()
        self.rows: dict[str, str] = {}
        self._in_td = False
        self._cells: list[str] = []
        self._current: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cells = []
        elif tag == "td":
            self._in_td = True
            self._current = []

    def handle_endtag(self, tag):
        if tag == "td":
            self._in_td = False
            self._cells.append("".join(self._current).strip())
        elif tag == "tr" and len(self._cells) == 2:
            self.rows[self._cells[0].strip()] = self._cells[1].strip()

    def handle_data(self, data):
        if self._in_td:
            self._current.append(data)


def _parse_aade_html(html: str) -> dict:
    """Parse AADE HTML and return structured receipt fields."""
    parser = _AADEParser()
    parser.feed(html)
    rows = parser.rows

    amount = None
    raw_amount = rows.get("Συνολική αξία", "")
    m = re.search(r"[\d.,]+", raw_amount.replace(",", "."))
    if m:
        try:
            amount = float(m.group().replace(",", "."))
        except ValueError:
            pass

    date_str = None
    raw_date = rows.get("Ημερομηνία, ώρα", "")
    dm = re.match(r"(\d{4}-\d{2}-\d{2})", raw_date)
    if dm:
        date_str = dm.group(1)

    merchant = rows.get("Επωνυμία") or None
    address = rows.get("Διεύθυνση") or ""

    # Category from merchant name + address
    combined = f"{merchant or ''} {address}"
    category_hint = _extract_category_hint(combined)

    return {
        "amount": amount,
        "currency": "EUR",
        "date": date_str,
        "merchant": merchant,
        "category_hint": category_hint,
    }


@router.post("/scan/qr", response_class=JSONResponse)
async def scan_qr(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """
    Fetch receipt data from the AADE portal using the QR code URL.
    The URL is validated to only allow the official AADE host — no SSRF risk.
    """
    user, hh_id = auth

    body = await request.json()
    url = body.get("url", "")
    if not isinstance(url, str) or len(url) > 500:
        raise HTTPException(status_code=400, detail="Invalid URL")

    # SSRF guard — whitelist only the known AADE host and path
    try:
        parsed_url = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != _AADE_HOST
        or not parsed_url.path.startswith(_AADE_PATH_PREFIX)
    ):
        raise HTTPException(status_code=400, detail="URL not allowed")

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=settings.aade_timeout_seconds,
        ) as client:
            resp = await client.get(url, headers={"Accept-Language": "el"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="AADE portal timed out")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach AADE portal")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"AADE returned {resp.status_code}")

    receipt = _parse_aade_html(resp.text)

    category_id = resolve_category(
        db, hh_id,
        merchant=receipt["merchant"],
        hint=receipt["category_hint"],
    )
    db.commit()

    return {
        "amount": receipt["amount"],
        "currency": receipt["currency"],
        "date": receipt["date"],
        "merchant": receipt["merchant"],
        "category_hint": receipt["category_hint"],
        "category_id": category_id,
    }


def _get_context(db: Session, user, hh_id: str) -> dict:
    """Common template context for transaction forms."""
    ctx = _full_ctx(db, user, hh_id)
    ctx["currencies"] = settings.currencies
    ctx["today"] = date.today().isoformat()
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
    amount: float = Form(...),
    currency: str = Form("EUR"),
    exchange_rate: float = Form(1.0),
    type: str = Form("expense"),
    category_id: str = Form(""),
    paid_by: str = Form(""),
    notes: str = Form(""),
    is_shared: str = Form("off"),
    merchant: str = Form(""),
    remember_rule: str = Form(""),
    client_id: str = Form(""),
    receipt: UploadFile = File(None),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    bucket = require_bucket(db, bucket_id, hh_id)

    # Idempotency for offline replays: a queued expense may be retried after
    # its response was lost, and must not become a second transaction.
    if client_id.strip():
        existing = (
            db.query(Transaction)
            .filter(
                Transaction.household_id == hh_id,
                Transaction.client_id == client_id.strip(),
            )
            .first()
        )
        if existing:
            if request.headers.get("HX-Request"):
                return templates.TemplateResponse(
                    "partials/transaction_added.html",
                    {"request": request, "transaction": existing, "bucket": bucket},
                )
            return RedirectResponse(f"/buckets/{existing.bucket_id}", status_code=302)

    txn_amount   = parse_amount(amount, field="Amount")
    txn_date     = _parse_txn_date(transaction_date)
    txn_currency = _validate_currency(currency)
    txn_type     = _parse_txn_type(type)
    txn_rate     = _parse_rate(exchange_rate)
    txn_paid_by  = require_member(db, paid_by, hh_id)
    txn_category = require_category(db, category_id, hh_id)

    # A shared expense with no payer is unusable: settle-up would charge the
    # shares to members with nobody credited for fronting the money, so the
    # household appeared to owe an outsider. The submitter is the only sensible
    # default, and the wizard now preselects them — this covers offline replays
    # and API clients that omit the field.
    if txn_type == TransactionType.expense and not txn_paid_by and is_shared == "on":
        txn_paid_by = user.id

    receipt_path = None
    if receipt and receipt.filename:
        ext = os.path.splitext(receipt.filename)[1].lower()
        if ext not in ALLOWED_RECEIPT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_RECEIPT_EXTENSIONS)}",
            )
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        content = await receipt.read()
        if len(content) > MAX_RECEIPT_SIZE:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(UPLOADS_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        receipt_path = filename

    txn = Transaction(
        bucket_id=bucket_id,
        household_id=hh_id,
        amount=txn_amount,
        currency=txn_currency,
        exchange_rate=txn_rate,
        type=txn_type,
        paid_by=txn_paid_by,
        category_id=txn_category,
        notes=notes.strip() or None,
        transaction_date=txn_date,
        receipt_path=receipt_path,
        client_id=client_id.strip() or None,
    )
    try:
        db.add(txn)
        db.flush()

        # Handle splits if shared
        if is_shared == "on":
            split_data = await _parse_splits(request, txn.id, txn_amount, hh_id, db)
            for split in split_data:
                db.add(split)

        # Teach the categorisation rule from a scan: correcting a merchant's
        # category once makes it stick for next time.
        if remember_rule == "on" and txn_category:
            learn_rule(db, hh_id, merchant or notes, txn_category,
                       created_by=user.id)

        db.commit()
    except Exception:
        db.rollback()
        if receipt_path:
            try:
                os.remove(os.path.join(UPLOADS_DIR, receipt_path))
            except OSError:
                pass
        raise

    # HTMX: if triggered from wizard, swap to success partial; else redirect
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/transaction_added.html",
            {"request": request, "transaction": txn, "bucket": bucket},
        )
    return RedirectResponse(f"/buckets/{bucket_id}", status_code=302)


async def _parse_splits(request: Request, txn_id: str, total, hh_id: str, db: Session):
    """Build TransactionSplit rows from split_{user_id} form fields.

    Every user id is checked against the household — splits used to accept any
    user id at all, letting a member attach shares to people outside the
    household (and corrupting the settlement maths for everyone).
    """
    form = await request.form()
    parsed: list[tuple[str, object]] = []
    for key, value in form.items():
        if not key.startswith("split_") or not str(value).strip():
            continue
        share = parse_amount(value, field="Split amount", allow_blank=True)
        if share and share > 0:
            parsed.append((key[6:], share))

    if not parsed:
        return []

    validate_split_users([uid for uid, _ in parsed], hh_id, db)

    split_total = sum(amount for _, amount in parsed)
    if total is not None and round(float(split_total), 4) > round(float(total), 4):
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({float(split_total):.2f}) exceed the transaction total ({float(total):.2f}).",
        )

    return [
        TransactionSplit(transaction_id=txn_id, user_id=uid, amount=amount)
        for uid, amount in parsed
    ]


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
    exclude_from_forecast: str = Form(""),
    exclude_from_settlement: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    txn = db.get(Transaction, txn_id)
    if not txn or txn.household_id != hh_id:
        raise HTTPException(status_code=404)

    # The target bucket was previously assigned straight from the form, so a
    # member could move a transaction into any household's bucket by guessing
    # or leaking an id.
    require_bucket(db, bucket_id, hh_id)

    txn.bucket_id = bucket_id
    txn.transaction_date = _parse_txn_date(transaction_date)
    txn.amount = parse_amount(amount, field="Amount")
    txn.currency = _validate_currency(currency)
    txn.exchange_rate = _parse_rate(exchange_rate)
    txn.type = _parse_txn_type(type)
    txn.paid_by = require_member(db, paid_by, hh_id)
    txn.category_id = require_category(db, category_id, hh_id)
    txn.notes = notes.strip() or None
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
    if not txn or txn.household_id != hh_id:
        raise HTTPException(status_code=404)

    bucket_id = txn.bucket_id
    db.delete(txn)
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
    if not src or src.household_id != hh_id:
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
        transaction_date=date.today(),
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


# ---------------------------------------------------------------------------
# Transaction search (cross-bucket)
# ---------------------------------------------------------------------------

SEARCH_PAGE_SIZE = 25

@router.get("/search", response_class=HTMLResponse)
def search_transactions(
    request: Request,
    q: str = Query(""),
    category_id: str = Query(""),
    type: str = Query(""),
    from_date: str = Query(""),
    to_date: str = Query(""),
    bucket_id: str = Query(""),
    min_amount: str = Query(""),
    max_amount: str = Query(""),
    paid_by: str = Query(""),
    missing_payer: str = Query(""),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)

    # Settle-up links here to show exactly which expenses it had to skip.
    want_missing_payer = missing_payer in ("1", "on", "true")

    has_filter = any([q.strip(), category_id, type, from_date, to_date, bucket_id,
                      min_amount.strip(), max_amount.strip(), paid_by,
                      want_missing_payer])

    if has_filter:
        query = db.query(Transaction).filter(Transaction.household_id == hh_id)

        if q.strip():
            # Free text used to match notes only, so a scanned receipt whose
            # merchant landed in the category or bucket name was unfindable —
            # and a bare number could not be searched at all.
            term = f"%{q.strip()}%"
            conditions = [
                Transaction.notes.ilike(term),
                Transaction.category_id.in_(
                    db.query(Category.id).filter(
                        Category.household_id == hh_id, Category.name.ilike(term)
                    ).scalar_subquery()
                ),
                Transaction.bucket_id.in_(
                    db.query(Bucket.id).filter(
                        Bucket.household_id == hh_id, Bucket.name.ilike(term)
                    ).scalar_subquery()
                ),
                Transaction.paid_by.in_(
                    db.query(User.id).filter(User.display_name.ilike(term)).scalar_subquery()
                ),
            ]
            # A numeric term also matches the amount exactly, so "42.50" works.
            exact = _maybe_number(q)
            if exact is not None:
                conditions.append(Transaction.amount == exact)
            query = query.filter(or_(*conditions))

        lo = parse_amount(min_amount, field="Min amount", allow_blank=True, allow_zero=True)
        if lo is not None:
            query = query.filter(Transaction.amount >= lo)
        hi = parse_amount(max_amount, field="Max amount", allow_blank=True, allow_zero=True)
        if hi is not None:
            query = query.filter(Transaction.amount <= hi)

        if paid_by:
            # Match the payer or anyone carrying a split on the transaction.
            query = query.filter(
                or_(
                    Transaction.paid_by == paid_by,
                    Transaction.id.in_(
                        db.query(TransactionSplit.transaction_id)
                        .filter(TransactionSplit.user_id == paid_by)
                        .scalar_subquery()
                    ),
                )
            )

        if category_id:
            query = query.filter(Transaction.category_id == category_id)
        if type:
            try:
                query = query.filter(Transaction.type == TransactionType(type))
            except ValueError:
                pass
        if from_date:
            try:
                query = query.filter(Transaction.transaction_date >= date.fromisoformat(from_date))
            except ValueError:
                pass
        if to_date:
            try:
                query = query.filter(Transaction.transaction_date <= date.fromisoformat(to_date))
            except ValueError:
                pass
        if bucket_id:
            query = query.filter(Transaction.bucket_id == bucket_id)
        if want_missing_payer:
            query = query.filter(
                Transaction.paid_by.is_(None),
                Transaction.type == TransactionType.expense,
            )

        total = query.count()
        total_pages = max(1, -(-total // SEARCH_PAGE_SIZE))
        page = min(page, total_pages)
        transactions = (
            query
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .offset((page - 1) * SEARCH_PAGE_SIZE)
            .limit(SEARCH_PAGE_SIZE)
            .all()
        )
    else:
        transactions = []
        total = None
        total_pages = 1
        page = 1

    ctx.update({
        "request": request,
        "user": user,
        "transactions": transactions,
        "q": q,
        "category_id": category_id,
        "selected_type": type,
        "from_date": from_date,
        "to_date": to_date,
        "selected_bucket_id": bucket_id,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "selected_paid_by": paid_by,
        "missing_payer": want_missing_payer,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "transaction_types": [t.value for t in TransactionType],
    })

    return templates.TemplateResponse("transactions/list.html", ctx)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection.

    Excel/Sheets execute a cell starting with = + - @ (or a leading tab/CR), so
    an expense note like `=HYPERLINK("http://evil","click")` becomes a live
    formula in whoever opens the export. Prefixing with an apostrophe keeps the
    text visible while forcing it to be read as a literal.
    """
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@router.get("/export", response_class=StreamingResponse)
def export_transactions(
    year: int = Query(None),
    month: int = Query(None),
    bucket_id: str = Query(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    parse_year_month(year, month)

    query = (
        db.query(Transaction)
        .filter(Transaction.household_id == hh_id)
        .options(
            joinedload(Transaction.bucket),
            joinedload(Transaction.category),
            joinedload(Transaction.paid_by_user),
        )
    )
    if bucket_id:
        require_bucket(db, bucket_id, hh_id)
        query = query.filter(Transaction.bucket_id == bucket_id)
    if year:
        # Half-open range avoids the old end-of-month arithmetic, which used
        # day 28 for February and so dropped Feb 29 in every leap year.
        if month:
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        else:
            start, end = date(year, 1, 1), date(year + 1, 1, 1)
        query = query.filter(
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )

    # Materialise rows now, not inside the generator. FastAPI closes the
    # get_db() session before the streaming body is consumed, so touching
    # txn.bucket lazily at that point raised DetachedInstanceError.
    rows = [
        [
            txn.transaction_date.isoformat(),
            _csv_safe(txn.bucket.name if txn.bucket else ""),
            _csv_safe(txn.category.name if txn.category else ""),
            txn.type.value,
            float(txn.amount),
            txn.currency,
            _csv_safe(txn.paid_by_user.display_name if txn.paid_by_user else ""),
            _csv_safe(txn.notes or ""),
        ]
        for txn in query.order_by(Transaction.transaction_date.desc()).all()
    ]

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Bucket", "Category", "Type", "Amount", "Currency", "Paid By", "Notes"])
        yield buf.getvalue()
        for row in rows:
            buf = io.StringIO()
            csv.writer(buf).writerow(row)
            yield buf.getvalue()

    filename = f"transactions_{year or 'all'}{'_' + str(month) if month else ''}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

@router.get("/check-duplicate", response_class=JSONResponse)
def check_duplicate(
    amount: str = Query(""),
    transaction_date: str = Query(""),
    bucket_id: str = Query(""),
    exclude_id: str = Query(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Live check used by the add-expense form. Advisory only — never blocks."""
    user, hh_id = auth

    value = parse_amount(amount, field="Amount", allow_blank=True)
    if value is None or not transaction_date.strip():
        return {"duplicates": []}

    try:
        when = date.fromisoformat(transaction_date.strip())
    except ValueError:
        return {"duplicates": []}

    matches = find_duplicate_candidates(
        db, hh_id,
        amount=value,
        transaction_date=when,
        bucket_id=bucket_id or None,
        exclude_id=exclude_id or None,
    )
    return {
        "duplicates": [
            {
                "id":       t.id,
                "amount":   float(t.amount),
                "currency": t.currency,
                "date":     t.transaction_date.isoformat(),
                "notes":    t.notes,
                "bucket":   t.bucket.name if t.bucket else None,
                "paid_by":  t.paid_by_user.display_name if t.paid_by_user else None,
                "same_bucket": bool(bucket_id) and t.bucket_id == bucket_id,
            }
            for t in matches
        ]
    }


@router.get("/duplicates", response_class=HTMLResponse)
def duplicates_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Review possible duplicates across recent history."""
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)
    ctx.update({
        "request": request,
        "user": user,
        "groups": find_household_duplicates(db, hh_id),
    })
    return templates.TemplateResponse("transactions/duplicates.html", ctx)

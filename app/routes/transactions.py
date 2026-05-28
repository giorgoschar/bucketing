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
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth, require_csrf
from app.models import (
    Transaction, TransactionSplit, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.templates import templates
from app.receipt_parser import parse_receipt_text, match_category, _extract_category_hint
from app.config import settings
from app.services import full_ctx as _full_ctx

router = APIRouter(prefix="/transactions", dependencies=[Depends(require_csrf)])

UPLOADS_DIR = "uploads"
MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}


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

    categories = db.query(Category).filter_by(household_id=hh_id).all()
    category_id = match_category(receipt["category_hint"], categories)

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
    try:
        db.add(txn)
        db.flush()

        # Handle splits if shared
        if is_shared == "on":
            split_data = await _parse_splits(request, txn.id, amount, hh_id, db)
            for split in split_data:
                db.add(split)

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
    exclude_from_forecast: str = Form(""),
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
    txn.exclude_from_forecast = (exclude_from_forecast == "on")

    # Replace splits
    db.query(TransactionSplit).filter_by(transaction_id=txn.id).delete()
    form_data = await request.form()
    for key, value in form_data.items():
        if key.startswith("split_") and value.strip():
            uid = key[6:]
            try:
                split_amount = float(value)
            except ValueError:
                continue
            if split_amount > 0:
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
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)

    has_filter = any([q.strip(), category_id, type, from_date, to_date, bucket_id])

    if has_filter:
        query = db.query(Transaction).filter(Transaction.household_id == hh_id)

        if q.strip():
            query = query.filter(Transaction.notes.ilike(f"%{q.strip()}%"))
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
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "transaction_types": [t.value for t in TransactionType],
    })

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("transactions/search_results.html", ctx)
    return templates.TemplateResponse("transactions/list.html", ctx)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@router.get("/export", response_class=StreamingResponse)
def export_transactions(
    year: int = Query(None),
    month: int = Query(None),
    bucket_id: str = Query(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    query = db.query(Transaction).filter(Transaction.household_id == hh_id)
    if bucket_id:
        query = query.filter(Transaction.bucket_id == bucket_id)
    if year:
        query = query.filter(
            Transaction.transaction_date >= date(year, month or 1, 1),
            Transaction.transaction_date <= date(year, month or 12, 31) if not month else
                date(year, month, 28 if month == 2 else (30 if month in (4,6,9,11) else 31)),
        )
    transactions = query.order_by(Transaction.transaction_date.desc()).all()

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Bucket", "Category", "Type", "Amount", "Currency", "Paid By", "Notes"])
        yield buf.getvalue()
        for txn in transactions:
            buf = io.StringIO()
            writer = csv.writer(buf)
            bucket_name = txn.bucket.name if txn.bucket else ""
            category_name = txn.category.name if txn.category else ""
            paid_by_name = txn.paid_by_user.display_name if txn.paid_by_user else ""
            writer.writerow([
                txn.transaction_date.isoformat(),
                bucket_name,
                category_name,
                txn.type.value,
                float(txn.amount),
                txn.currency,
                paid_by_name,
                txn.notes or "",
            ])
            yield buf.getvalue()

    filename = f"transactions_{year or 'all'}{'_' + str(month) if month else ''}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

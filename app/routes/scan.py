"""
Transactions: receipt scan (OCR text parsing, AADE QR lookup).
"""
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
)
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.category_rules import resolve_category
from app.config import settings
from app.database import get_db
from app.receipt_parser import _extract_category_hint, parse_receipt_text
from app.routes.transactions import _get_context
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", dependencies=[Depends(require_csrf)])


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
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL") from None

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
        raise HTTPException(status_code=504, detail="AADE portal timed out") from None
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach AADE portal") from None

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

"""
Transactions: receipt scan (OCR text parsing, AADE QR lookup).
"""
import asyncio
import html as html_lib
import ipaddress
import logging
import re
import socket
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


# ---------------------------------------------------------------------------
# QR-code → AADE myDATA receipt page (mydatapi.aade.gr)
# ---------------------------------------------------------------------------
#
# Newer receipts are issued through e-invoicing providers. Their QR code links
# either straight to AADE's myDATA page or to the provider's own receipt page,
# which carries a link to the AADE page. Providers are many, so only the AADE
# page is parsed: a provider page is fetched just to find that link.

# The AADE link inside a provider page, after HTML unescaping. The host match
# is exact (the path follows), so a look-alike host can't be smuggled in.
_MYDATA_LINK_RE = re.compile(
    r"https://" + re.escape(settings.mydata_qr_host) + re.escape(settings.mydata_qr_path)
    + r"\?q=[A-Za-z0-9%+/=._~-]+"
)


class _InputValues(HTMLParser):
    """id → value of every <input> on the page (the AADE page renders the
    receipt fields as readonly inputs)."""

    def __init__(self):
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            a = dict(attrs)
            if a.get("id"):
                self.values[a["id"]] = (a.get("value") or "").strip()


def _parse_gr_number(raw: str) -> float | None:
    """'1.214,00' / '14,00' / '14.00' / '1,214.50' → float. The last separator
    is the decimal one when 1-2 digits follow it; any other is a thousands
    separator."""
    m = re.search(r"\d[\d.,]*", raw or "")
    if not m:
        return None
    s = m.group().rstrip(".,")
    last = max(s.rfind(","), s.rfind("."))
    if last != -1 and len(s) - last - 1 in (1, 2):
        s = re.sub(r"[.,]", "", s[:last]) + "." + s[last + 1:]
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_mydata_qr_html(html: str) -> dict:
    """Parse AADE's myDATA receipt page. It carries the total, the issue date
    and the issuer's tax number; the issuer name is often left blank."""
    parser = _InputValues()
    parser.feed(html)
    v = parser.values

    date_str = None
    dm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v.get("tdate", ""))
    if dm:
        d, mth, y = dm.groups()
        date_str = f"{y}-{int(mth):02d}-{int(d):02d}"

    merchant = v.get("bname") or None
    return {
        "amount": _parse_gr_number(v.get("tamount", "")),
        "currency": "EUR",
        "date": date_str,
        "merchant": merchant,
        "category_hint": _extract_category_hint(f"{merchant or ''} {v.get('bactivity', '')}"),
    }


async def _fetch_aade(url: str, source: str) -> str:
    """GET an allowlisted AADE URL (no redirects)."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=settings.aade_timeout_seconds,
        ) as client:
            resp = await client.get(url, headers={"Accept-Language": "el"})
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"{source} timed out") from None
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail=f"Could not reach {source}") from None

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"{source} returned {resp.status_code}")
    return resp.text


async def _resolve(host: str):
    return await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)


async def _check_public_host(host: str) -> str:
    """SSRF guard for provider pages: resolve ``host`` and return an address to
    connect to, refusing it unless every address it resolves to is public
    (so no loopback, private, link-local/metadata or CGNAT range)."""
    try:
        infos = await _resolve(host)
    except (socket.gaierror, UnicodeError):
        raise HTTPException(status_code=400, detail="Could not find that receipt site") from None
    ips = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if not ips or not all(ip.is_global for ip in ips):
        raise HTTPException(status_code=400, detail="URL not allowed")
    return str(ips[0])


async def _fetch_public_page(url: str) -> str:
    """GET a provider's receipt page, hardened against SSRF: https on 443 only,
    no redirects, connecting to the vetted public address itself (so a second
    DNS answer can't point elsewhere) while TLS still verifies the hostname,
    and the body capped at ``receipt_page_max_bytes``."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    ip = await _check_public_host(host)
    ip_host = f"[{ip}]" if ":" in ip else ip
    target = parsed._replace(netloc=ip_host).geturl()

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=settings.aade_timeout_seconds,
        ) as client:
            async with client.stream(
                "GET", target,
                headers={"Host": host, "Accept-Language": "el"},
                extensions={"sni_hostname": host},
            ) as resp:
                if resp.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"{host} returned {resp.status_code}")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > settings.receipt_page_max_bytes:
                        raise HTTPException(status_code=502, detail="Receipt page is too large")
                return body.decode(resp.encoding or "utf-8", errors="replace")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"{host} timed out") from None
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail=f"Could not reach {host}") from None


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


@router.post("/scan/qr", response_class=JSONResponse)
async def scan_qr(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """
    Read a receipt from the URL in its QR code: the AADE cash-register lookup,
    AADE's myDATA page, or an e-invoicing provider's page that links to the
    myDATA page. Only AADE pages are parsed; provider pages are fetched through
    an SSRF-hardened client just to find the AADE link.
    """
    user, hh_id = auth

    body = await request.json()
    url = body.get("url", "")
    if not isinstance(url, str) or len(url) > 500:
        raise HTTPException(status_code=400, detail="Invalid URL")

    try:
        parsed_url = urlparse(url.strip())
        port = parsed_url.port
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL") from None

    host = (parsed_url.hostname or "").lower()
    if (
        parsed_url.scheme != "https"
        or not host
        or parsed_url.username is not None
        or port not in (None, 443)
        or _is_ip_literal(host)
    ):
        raise HTTPException(status_code=400, detail="URL not allowed")
    url = parsed_url.geturl()

    if host == _AADE_HOST and parsed_url.path.startswith(_AADE_PATH_PREFIX):
        receipt = _parse_aade_html(await _fetch_aade(url, "AADE portal"))
    else:
        if not (host == settings.mydata_qr_host and parsed_url.path == settings.mydata_qr_path):
            page = await _fetch_public_page(url)
            link = _MYDATA_LINK_RE.search(html_lib.unescape(page))
            if not link:
                raise HTTPException(
                    status_code=400,
                    detail="This receipt page has no AADE link. Upload a photo instead.",
                )
            url = link.group(0)
        receipt = _parse_mydata_qr_html(await _fetch_aade(url, "AADE myDATA"))
        if receipt["amount"] is None:
            raise HTTPException(status_code=502, detail="Could not read the receipt from AADE")

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

"""QR scan through AADE's myDATA receipt page (mydatapi.aade.gr), reached
either directly from the QR code or via the "AADE" link on an e-invoicing
provider's receipt page (e.g. einvoice.impact.gr)."""
import asyncio
import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.routes import scan
from app.routes.scan import _check_public_host, _parse_gr_number, _parse_mydata_qr_html

MYDATA_URL = ("https://mydatapi.aade.gr/myDATA/TimologioQR/QRInfo"
              "?q=Dsffq2BZQ%2b3laQtRzCNe3vmS0HYj995F10ah4OM5V%2fC7S0U%3d")
PROVIDER_URL = "https://einvoice.impact.gr/p/EL800865360/7A38951C/71A647D6"

# Mirrors the AADE page: values live in readonly inputs keyed by id.
MYDATA_HTML = """<html><body><table>
<tr><td>Είδος παραστατικού</td><td><input id="dtype" value="ΑΠΥ (Απόδειξη Παροχής Υπηρεσιών)"></td></tr>
<tr><td>Ημερομηνία Έκδοσης</td><td><input type="text" id="tdate" name="tdate" readonly="" value="05/10/2026"></td></tr>
<tr><td>Συνολική αξία</td><td><input type="text" id="tamount" value="1.214,00" readonly=""></td></tr>
<tr><td>Επωνυμία εκδότη</td><td><input id="bname" value="AGK ATHENS PARKING ΙΚΕ"></td></tr>
<tr><td>ΑΦΜ εκδότη</td><td><input id="vatnumber" value="800865360"></td></tr>
<tr><td>Επάγγελμα</td><td><input id="bactivity" value=""></td></tr>
</table></body></html>"""

# A provider page with the AADE button (href is HTML-escaped as on the real page).
PROVIDER_HTML = f"""<html><body><h1>Receipt</h1>
<fluent-anchor id="erpQrBtn" href="{MYDATA_URL.replace('&', '&amp;')}">AADE</fluent-anchor>
</body></html>"""


class _FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response, self._exc = response, exc
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self.urls.append(url)
        if self._exc:
            raise self._exc
        return self._response


def _patch_aade(response=None, exc=None):
    fake = _FakeAsyncClient(response, exc)
    return patch("app.routes.scan.httpx.AsyncClient", lambda **kw: fake), fake


def _scan(client, authed, url):
    return client.post("/transactions/scan/qr", headers=authed.headers, json={"url": url})


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("raw,expected", [
    ("14,00", 14.0), ("1.214,00", 1214.0), (" 2,71 ", 2.71),
    ("14.00", 14.0), ("1,214.50", 1214.5), ("abc", None), ("", None),
])
def test_parse_gr_number(raw, expected):
    assert _parse_gr_number(raw) == expected


def test_parse_mydata_qr_html():
    r = _parse_mydata_qr_html(MYDATA_HTML)
    assert r["amount"] == 1214.0
    assert r["date"] == "2026-10-05"
    assert r["merchant"] == "AGK ATHENS PARKING ΙΚΕ"
    assert r["currency"] == "EUR"


def test_parse_mydata_qr_html_without_issuer_name():
    r = _parse_mydata_qr_html(MYDATA_HTML.replace("AGK ATHENS PARKING ΙΚΕ", ""))
    assert r["merchant"] is None and r["amount"] == 1214.0


# ---------------------------------------------------------------- routes

def test_direct_mydata_qr(client, authed):
    p, fake = _patch_aade(httpx.Response(200, text=MYDATA_HTML))
    with p, patch.object(scan, "_fetch_public_page", AsyncMock()) as public:
        r = _scan(client, authed, MYDATA_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 1214.0 and body["date"] == "2026-10-05"
    assert body["merchant"] == "AGK ATHENS PARKING ΙΚΕ"
    assert fake.urls == [MYDATA_URL]
    public.assert_not_called()          # AADE's own host needs no public-page fetch


def test_provider_page_is_followed_to_aade(client, authed):
    p, fake = _patch_aade(httpx.Response(200, text=MYDATA_HTML))
    with p, patch.object(scan, "_fetch_public_page", AsyncMock(return_value=PROVIDER_HTML)) as public:
        r = _scan(client, authed, PROVIDER_URL)
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 1214.0
    public.assert_awaited_once_with(PROVIDER_URL)
    assert fake.urls == [MYDATA_URL]    # the unescaped AADE link, nothing else


def test_provider_page_without_aade_link(client, authed):
    with patch.object(scan, "_fetch_public_page", AsyncMock(return_value="<html>hi</html>")):
        r = _scan(client, authed, PROVIDER_URL)
    assert r.status_code == 400
    assert "AADE" in r.json()["detail"]


def test_provider_page_link_to_a_lookalike_host_is_ignored(client, authed):
    evil = PROVIDER_HTML.replace("mydatapi.aade.gr", "mydatapi.aade.gr.evil.com")
    with patch.object(scan, "_fetch_public_page", AsyncMock(return_value=evil)), \
            patch("app.routes.scan.httpx.AsyncClient") as ac:
        r = _scan(client, authed, PROVIDER_URL)
    assert r.status_code == 400
    ac.assert_not_called()


def test_aade_page_without_a_total_is_a_502(client, authed):
    p, _ = _patch_aade(httpx.Response(200, text="<html>Σφάλμα</html>"))
    with p:
        r = _scan(client, authed, MYDATA_URL)
    assert r.status_code == 502


@pytest.mark.parametrize("url", [
    "http://einvoice.impact.gr/p/x",              # not https
    "https://user@einvoice.impact.gr/p/x",        # credentials
    "https://einvoice.impact.gr:8443/p/x",        # odd port
    "https://127.0.0.1/p/x",                      # IP literal
    "https://[::1]/p/x",
    "javascript:alert(1)",
    "not a url",
])
def test_unsafe_urls_rejected_without_fetching(client, authed, url):
    with patch("app.routes.scan.httpx.AsyncClient") as ac, \
            patch.object(scan, "_resolve", AsyncMock()) as resolve:
        r = _scan(client, authed, url)
    assert r.status_code == 400
    ac.assert_not_called()
    resolve.assert_not_called()


# ---------------------------------------------------------------- SSRF guard

def _addrinfo(*ips):
    return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
            for ip in ips]


@pytest.mark.parametrize("ips", [
    ("127.0.0.1",), ("10.0.0.5",), ("192.168.1.10",), ("169.254.169.254",),
    ("100.64.0.1",), ("::1",), ("fd00::1",), ("93.184.216.34", "10.0.0.1"),
])
def test_check_public_host_rejects_non_public_addresses(ips):
    with patch.object(scan, "_resolve", AsyncMock(return_value=_addrinfo(*ips))):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_check_public_host("receipts.example.com"))
    assert exc.value.status_code == 400


def test_check_public_host_returns_a_public_ip():
    with patch.object(scan, "_resolve", AsyncMock(return_value=_addrinfo("93.184.216.34"))):
        assert asyncio.run(_check_public_host("receipts.example.com")) == "93.184.216.34"


def test_check_public_host_unresolvable():
    with patch.object(scan, "_resolve", AsyncMock(side_effect=socket.gaierror("nope"))):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_check_public_host("nope.invalid"))
    assert exc.value.status_code == 400

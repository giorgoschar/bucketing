"""Phase 2b composer APIs: POST /api/v1/transactions/scan/qr (B1) and
GET /api/v1/transactions/check-duplicate (B2)."""

from unittest.mock import patch

import httpx
import pyotp
import pytest

from tests.conftest import PASSWORD
from tests.test_api import api  # noqa: F401  (fixture)

AADE_URL = "https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc"
AADE_HTML = """<table>
<tr><td>Επωνυμία</td><td>Test Taverna</td></tr>
<tr><td>Συνολική αξία</td><td>12,50</td></tr>
<tr><td>Ημερομηνία, ώρα</td><td>2026-03-04 12:30</td></tr>
</table>"""


class _FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response, self._exc = response, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        if self._exc:
            raise self._exc
        return self._response


def _patch_httpx(response=None, exc=None):
    return patch("app.routes.scan.httpx.AsyncClient", lambda **kw: _FakeAsyncClient(response, exc))


def _bearer(client, hh):
    """Bearer headers for a second household's owner (own TOTP secret, so no code reuse)."""
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(hh.secret).now()},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------- B1 /scan/qr


def test_api_scan_qr_reads_the_receipt_with_a_bearer_token(client, api):  # noqa: F811
    headers, _ = api
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        r = client.post("/api/v1/transactions/scan/qr", headers=headers, json={"url": AADE_URL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 12.5 and body["currency"] == "EUR"
    assert body["date"] == "2026-03-04" and body["merchant"] == "Test Taverna"
    assert set(body) == {"amount", "currency", "date", "merchant", "category_hint", "category_id"}


def test_api_scan_qr_gives_the_same_payload_as_the_html_route(client, authed):
    # Same household and session for both: require_api_auth falls back to the cookie.
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        api_r = client.post(
            "/api/v1/transactions/scan/qr", headers=authed.headers, json={"url": AADE_URL}
        )
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        web_r = client.post("/transactions/scan/qr", headers=authed.headers, json={"url": AADE_URL})
    assert api_r.status_code == web_r.status_code == 200
    assert api_r.json() == web_r.json()


def test_api_scan_qr_needs_auth(client):
    r = client.post("/api/v1/transactions/scan/qr", json={"url": AADE_URL})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "url",
    [
        "http://www1.aade.gr/tameiakes/myweb/q1.php?x=1",
        "https://10.0.0.1/tameiakes/myweb/q1.php",
        "https://www1.aade.gr:8080/tameiakes/myweb/q1.php",
        "x" * 501,
    ],
)
def test_api_scan_qr_refuses_disallowed_urls_without_fetching(client, api, url):  # noqa: F811
    headers, _ = api
    with patch("app.routes.scan.httpx.AsyncClient") as ac:
        r = client.post("/api/v1/transactions/scan/qr", headers=headers, json={"url": url})
    assert r.status_code == 400
    ac.assert_not_called()


def test_api_scan_qr_upstream_failure_is_a_502_with_the_message(client, api):  # noqa: F811
    headers, _ = api
    with _patch_httpx(exc=httpx.ConnectError("down")):
        r = client.post("/api/v1/transactions/scan/qr", headers=headers, json={"url": AADE_URL})
    assert r.status_code == 502
    assert r.json()["detail"] == "Could not reach AADE portal"

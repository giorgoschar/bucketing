"""Phase 2b composer APIs: POST /api/v1/transactions/scan/qr (B1) and
GET /api/v1/transactions/check-duplicate (B2)."""

from datetime import timedelta
from unittest.mock import patch

import httpx
import pyotp
import pytest

from app.core.clock import local_today
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


# ---------------------------------------------------------------- B2 /check-duplicate


def _expense(client, headers, hh, amount="42.50", when=None, merchant="Taverna"):
    r = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "amount": amount,
            "bucket_id": hh.bucket_id,
            "merchant": merchant,
            "transaction_date": (when or local_today()).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _check(client, headers, **params):
    return client.get("/api/v1/transactions/check-duplicate", headers=headers, params=params)


def test_check_duplicate_finds_a_same_amount_expense_within_three_days(client, api):  # noqa: F811
    headers, hh = api
    txn = _expense(client, headers, hh, when=local_today() - timedelta(days=3))
    r = _check(
        client,
        headers,
        amount="42.50",
        transaction_date=local_today().isoformat(),
        bucket_id=hh.bucket_id,
    )
    assert r.status_code == 200, r.text  # not a 404 from GET /{txn_id}
    [d] = r.json()["duplicates"]
    assert d["id"] == txn["id"] and d["amount"] == 42.5 and d["merchant"] == "Taverna"
    assert d["same_bucket"] is True and d["date"] == (local_today() - timedelta(days=3)).isoformat()
    assert set(d) == {
        "id",
        "amount",
        "currency",
        "date",
        "notes",
        "merchant",
        "bucket",
        "paid_by",
        "same_bucket",
    }


def test_check_duplicate_ignores_four_days_away_and_the_excluded_id(client, api):  # noqa: F811
    headers, hh = api
    _expense(client, headers, hh, when=local_today() - timedelta(days=4))
    near = _expense(client, headers, hh)
    today = local_today().isoformat()
    assert [
        d["id"]
        for d in _check(client, headers, amount="42.50", transaction_date=today).json()[
            "duplicates"
        ]
    ] == [near["id"]]
    assert _check(
        client, headers, amount="42.50", transaction_date=today, exclude_id=near["id"]
    ).json() == {"duplicates": []}


@pytest.mark.parametrize(
    "params",
    [
        {"amount": "", "transaction_date": ""},
        {"amount": "abc", "transaction_date": "2026-10-07"},
        {"amount": "10", "transaction_date": "nonsense"},
        {},
    ],
)
def test_check_duplicate_blank_or_invalid_input_is_an_empty_list(client, api, params):  # noqa: F811
    headers, _ = api
    r = _check(client, headers, **params)
    assert r.status_code == 200 and r.json() == {"duplicates": []}


def test_check_duplicate_is_household_scoped(client, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    _expense(client, _bearer(client, other), other)
    r = _check(client, headers, amount="42.50", transaction_date=local_today().isoformat())
    assert r.json() == {"duplicates": []}


def test_check_duplicate_needs_auth(client):
    r = client.get(
        "/api/v1/transactions/check-duplicate",
        params={"amount": "1", "transaction_date": "2026-10-07"},
    )
    assert r.status_code == 401


def test_html_check_duplicate_also_returns_empty_for_a_malformed_amount(client, authed):
    r = client.get("/transactions/check-duplicate?amount=abc&transaction_date=2026-10-07")
    assert r.status_code == 200 and r.json() == {"duplicates": []}

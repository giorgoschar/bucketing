"""Routes that had no direct tests: income, invites, switcher, member
management, leave-household and the AADE QR scan."""

from datetime import timedelta
from unittest.mock import patch

import httpx
import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import (
    Household,
    HouseholdMember,
    Invitation,
    MemberRole,
    Transaction,
    TransactionType,
    User,
)
from tests.conftest import PASSWORD, form_csrf
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user, _web_login

# ---------------------------------------------------------------- /income (HTML)


def test_income_form_renders(client, authed):
    r = client.get("/income/new", params={"bucket_id": authed.bucket_id})
    assert r.status_code == 200


def test_income_form_ignores_foreign_bucket(client, db, authed, make_household):
    other = make_household(name="Other", username="someone")
    r = client.get("/income/new", params={"bucket_id": other.bucket_id})
    assert r.status_code == 200
    assert other.bucket_id not in r.text


def _income_form(authed, **over):
    data = {
        "bucket_id": authed.bucket_id,
        "transaction_date": local_today().isoformat(),
        "amount": "250.50",
        "currency": "EUR",
        "received_by": authed.user_id,
        "notes": " salary ",
    }
    data.update(over)
    return data


def test_income_create_saves_and_redirects(client, db, authed):
    r = client.post("/income", headers=authed.headers, data=_income_form(authed))
    assert r.status_code == 302 and r.headers["location"] == f"/buckets/{authed.bucket_id}"
    t = db.query(Transaction).one()
    assert t.type == TransactionType.income
    assert float(t.amount) == 250.5 and t.notes == "salary"
    assert t.paid_by == authed.user_id and t.household_id == authed.household_id


@pytest.mark.parametrize(
    "over",
    [
        {"bucket_id": "nope"},
        {"currency": "XXX"},
        {"transaction_date": "31/12/2026"},
    ],
)
def test_income_create_rejects_bad_input(client, db, authed, over):
    r = client.post("/income", headers=authed.headers, data=_income_form(authed, **over))
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_income_create_rejects_foreign_bucket(client, db, authed, make_household):
    other = make_household(name="Other", username="someone")
    r = client.post(
        "/income", headers=authed.headers, data=_income_form(authed, bucket_id=other.bucket_id)
    )
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_income_create_requires_csrf(client, db, authed):
    r = client.post("/income", data=_income_form(authed))
    assert r.status_code == 403
    assert db.query(Transaction).count() == 0


# ---------------------------------------------------------------- /income (API)


def test_api_income_create(client, db, api):
    headers, hh = api
    r = client.post(
        "/api/v1/income",
        headers=headers,
        json={"bucket_id": hh.bucket_id, "amount": 100, "notes": "gift"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "income" and body["amount"] == 100.0
    assert body["paid_by"] == hh.user_id
    assert body["transaction_date"] == local_today().isoformat()
    assert db.query(Transaction).filter_by(type=TransactionType.income).count() == 1


def test_api_income_unknown_bucket_is_404(client, db, api):
    headers, _ = api
    r = client.post("/api/v1/income", headers=headers, json={"bucket_id": "nope", "amount": 1})
    assert r.status_code == 404
    assert db.query(Transaction).count() == 0


def test_api_income_foreign_bucket_is_404(client, db, api, make_household):
    headers, _ = api
    other = make_household(name="Other", username="someone")
    r = client.post(
        "/api/v1/income", headers=headers, json={"bucket_id": other.bucket_id, "amount": 1}
    )
    assert r.status_code == 404


def test_api_income_requires_auth(client, api):
    _, hh = api
    r = client.post("/api/v1/income", json={"bucket_id": hh.bucket_id, "amount": 1})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------- /join/{token}


def _invite(db, hh, **kw):
    inv = Invitation(household_id=hh.household_id, created_by=hh.user_id, **kw)
    db.add(inv)
    db.commit()
    return inv


def _join_data(client, token, **over):
    data = {
        "display_name": "Newbie",
        "username": "Newbie",
        "email": "New@Example.com",
        "password": PASSWORD,
        **form_csrf(client, f"/join/{token}"),
    }
    data.update(over)
    return data


def test_join_page_valid(client, db, make_household):
    inv = _invite(db, make_household(name="Casa"))
    r = client.get(f"/join/{inv.token}")
    assert r.status_code == 200 and "Casa" in r.text


def test_join_page_unknown_used_and_expired(client, db, make_household):
    hh = make_household()
    assert client.get("/join/nope").status_code == 200
    used = _invite(db, hh, used_at=utcnow_naive())
    expired = _invite(db, hh, expires_at=utcnow_naive() - timedelta(days=1))
    for inv in (used, expired):
        r = client.get(f"/join/{inv.token}")
        assert r.status_code == 200
        assert "_csrf_token" not in r.text  # no join form


def test_join_creates_member_and_consumes_invite(client, db, make_household):
    hh = make_household()
    inv = _invite(db, hh)
    r = client.post(f"/join/{inv.token}", data=_join_data(client, inv.token))
    assert r.status_code == 302 and r.headers["location"] == "/settings/2fa/enroll"
    user = db.query(User).filter_by(username="newbie").one()
    assert user.email == "new@example.com"
    m = db.query(HouseholdMember).filter_by(user_id=user.id).one()
    assert m.household_id == hh.household_id and m.role == MemberRole.member
    db.refresh(inv)
    assert inv.used_at is not None and inv.used_by == user.id


def test_join_cannot_reuse_invite(client, db, make_household):
    inv = _invite(db, make_household())
    data = _join_data(client, inv.token)
    assert client.post(f"/join/{inv.token}", data=data).status_code == 302
    r = client.post(f"/join/{inv.token}", data={**data, "username": "second", "email": "s@x.com"})
    assert r.status_code == 400


def test_join_expired_invite_rejected(client, db, make_household):
    hh = make_household()
    inv = _invite(db, hh, expires_at=utcnow_naive() - timedelta(hours=1))
    live = _invite(db, hh)
    r = client.post(f"/join/{inv.token}", data=_join_data(client, live.token))
    assert r.status_code == 400
    assert db.query(User).count() == 1


@pytest.mark.parametrize(
    "over,msg",
    [
        ({"password": "short"}, "12 characters"),
        ({"email": "owner@example.com"}, "email"),
        ({"username": "OWNER", "email": "other@x.com"}, "Username"),
    ],
)
def test_join_validation_errors(client, db, make_household, over, msg):
    hh = make_household(username="owner")
    inv = _invite(db, hh)
    r = client.post(f"/join/{inv.token}", data=_join_data(client, inv.token, **over))
    assert r.status_code == 200 and msg in r.text
    assert db.query(User).count() == 1
    db.refresh(inv)
    assert inv.used_at is None


# ---------------------------------------------------------------- /household/switch


def _second_household(db, user_id, name="Second"):
    hh = Household(name=name, default_currency="EUR")
    db.add(hh)
    db.flush()
    db.add(HouseholdMember(household_id=hh.id, user_id=user_id, role=MemberRole.owner))
    db.commit()
    return hh


def test_switch_to_own_household(client, db, authed):
    other = _second_household(db, authed.user_id)
    r = client.post("/household/switch", headers=authed.headers, data={"household_id": other.id})
    assert r.status_code == 302 and r.headers["location"] == "/dashboard"
    assert "session=" in r.headers.get("set-cookie", "")
    page = client.get("/dashboard")
    assert page.status_code == 200 and "Second" in page.text


def test_switch_to_foreign_household_forbidden(client, db, authed, make_household):
    other = make_household(name="Stranger", username="stranger")
    r = client.post(
        "/household/switch", headers=authed.headers, data={"household_id": other.household_id}
    )
    assert r.status_code == 403


# ---------------------------------------------------------------- member management


@pytest.fixture()
def pair(app, db, make_household):
    """Owner (web client) plus a plain member in the same household."""
    owner = make_household(name="Shared", username="owner")
    member, secret = _add_member_user(db, owner.household_id)
    c = _web_login(app, "owner", owner.secret)
    c.headers_csrf = {"X-CSRF-Token": c.cookies.get("csrf_token")}
    return c, owner, member, secret


def _role(db, hh_id, user_id):
    db.expire_all()
    m = db.query(HouseholdMember).filter_by(household_id=hh_id, user_id=user_id).first()
    return m.role if m else None


def test_remove_member_keeps_their_data(db, pair):
    c, owner, member, _ = pair
    db.add(
        Transaction(
            bucket_id=owner.bucket_id,
            household_id=owner.household_id,
            amount=5,
            currency="EUR",
            exchange_rate=1,
            type=TransactionType.expense,
            transaction_date=local_today(),
            paid_by=member.id,
        )
    )
    db.commit()
    r = c.post(f"/settings/remove-member/{member.id}", headers=c.headers_csrf)
    assert r.status_code == 302 and r.headers["location"] == "/settings"
    assert _role(db, owner.household_id, member.id) is None
    assert db.get(User, member.id) is not None
    assert db.query(Transaction).filter_by(paid_by=member.id).count() == 1


def test_remove_member_guards(db, pair, make_household):
    c, owner, member, _ = pair
    h = c.headers_csrf
    assert c.post(f"/settings/remove-member/{owner.user_id}", headers=h).status_code == 400
    assert c.post("/settings/remove-member/ghost", headers=h).status_code == 404
    stranger = make_household(name="Elsewhere", username="stranger")
    assert c.post(f"/settings/remove-member/{stranger.user_id}", headers=h).status_code == 404
    assert _role(db, stranger.household_id, stranger.user_id) == MemberRole.owner


def test_remove_member_cannot_remove_other_owner(db, pair):
    c, owner, member, _ = pair
    db.query(HouseholdMember).filter_by(user_id=member.id).one().role = MemberRole.owner
    db.commit()
    assert c.post(f"/settings/remove-member/{member.id}", headers=c.headers_csrf).status_code == 400
    assert _role(db, owner.household_id, member.id) == MemberRole.owner


def test_member_cannot_remove_or_transfer(app, db, pair):
    _, owner, member, secret = pair
    mc = _web_login(app, "member", secret)
    h = {"X-CSRF-Token": mc.cookies.get("csrf_token")}
    assert mc.post(f"/settings/remove-member/{owner.user_id}", headers=h).status_code == 403
    assert mc.post(f"/settings/transfer-ownership/{member.id}", headers=h).status_code == 403
    assert _role(db, owner.household_id, owner.user_id) == MemberRole.owner


def test_transfer_ownership(db, pair):
    c, owner, member, _ = pair
    r = c.post(f"/settings/transfer-ownership/{member.id}", headers=c.headers_csrf)
    assert r.status_code == 302 and r.headers["location"] == "/settings"
    assert _role(db, owner.household_id, member.id) == MemberRole.owner
    assert _role(db, owner.household_id, owner.user_id) == MemberRole.member


def test_transfer_ownership_guards(db, pair, make_household):
    c, owner, _, _ = pair
    h = c.headers_csrf
    assert c.post(f"/settings/transfer-ownership/{owner.user_id}", headers=h).status_code == 400
    stranger = make_household(name="Elsewhere", username="stranger")
    assert c.post(f"/settings/transfer-ownership/{stranger.user_id}", headers=h).status_code == 404
    assert _role(db, owner.household_id, owner.user_id) == MemberRole.owner


# ---------------------------------------------------------------- leave household


def test_owner_cannot_leave_while_members_remain(db, pair):
    c, owner, _, _ = pair
    r = c.post("/settings/leave-household", headers=c.headers_csrf, data={})
    assert r.status_code == 200 and "owner" in r.text.lower()
    assert _role(db, owner.household_id, owner.user_id) == MemberRole.owner


def test_member_leaves_and_household_survives(app, db, pair):
    _, owner, member, secret = pair
    mc = _web_login(app, "member", secret)
    r = mc.post(
        "/settings/leave-household", headers={"X-CSRF-Token": mc.cookies.get("csrf_token")}, data={}
    )
    assert r.status_code == 302 and r.headers["location"] == "/setup"
    assert _role(db, owner.household_id, member.id) is None
    assert db.get(Household, owner.household_id).archived_at is None


def test_leave_switches_to_remaining_household(client, db, authed):
    other = _second_household(db, authed.user_id)
    r = client.post(
        "/settings/leave-household",
        headers=authed.headers,
        data={"confirm_name": db.get(Household, authed.household_id).name},
    )
    assert r.status_code == 302 and r.headers["location"] == "/settings"
    assert _role(db, other.id, authed.user_id) == MemberRole.owner


# ---------------------------------------------------------------- /transactions/scan/qr

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


def _scan(client, authed, url=AADE_URL):
    return client.post("/transactions/scan/qr", headers=authed.headers, json={"url": url})


def test_scan_qr_parses_receipt(client, authed):
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        r = _scan(client, authed)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 12.5 and body["date"] == "2026-03-04"
    assert body["merchant"] == "Test Taverna" and body["currency"] == "EUR"


# Other https hosts are provider pages, fetched through the SSRF guard to find
# the AADE link (tests/test_scan_qr_mydata.py).
@pytest.mark.parametrize(
    "url",
    [
        "http://www1.aade.gr/tameiakes/myweb/q1.php?x=1",
        "https://10.0.0.1/tameiakes/myweb/q1.php",
        "https://www1.aade.gr:8080/tameiakes/myweb/q1.php",
        "x" * 501,
    ],
)
def test_scan_qr_blocks_disallowed_urls_without_fetching(client, authed, url):
    with patch("app.routes.scan.httpx.AsyncClient") as ac:
        r = _scan(client, authed, url)
    assert r.status_code == 400
    ac.assert_not_called()


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"exc": httpx.ReadTimeout("slow")}, 504),
        ({"exc": httpx.ConnectError("down")}, 502),
        ({"response": httpx.Response(500, text="boom")}, 502),
    ],
)
def test_scan_qr_upstream_failures(client, authed, kwargs, status):
    with _patch_httpx(**kwargs):
        assert _scan(client, authed).status_code == status


def test_scan_qr_requires_auth(client):
    r = client.post("/transactions/scan/qr", json={"url": AADE_URL})
    assert r.status_code in (302, 401, 403)

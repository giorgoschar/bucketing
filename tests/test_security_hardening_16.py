"""Task 1.6: push allowlist, owner-only invites, upload sniffing, login CSRF, invite URL."""
import io
import re
from datetime import date, datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.models import Invitation, PushSubscription, Transaction, TransactionType, User
from tests.conftest import PASSWORD
from tests.test_household_settlement import _add_member

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64


# ---------------------------------------------------------------------------
# Push endpoint allowlist
# ---------------------------------------------------------------------------

def _sub(client, authed, endpoint):
    return client.post(
        "/push/subscribe",
        json={"endpoint": endpoint, "keys": {"p256dh": "k", "auth": "a"}},
        headers=authed.headers,
    )


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/abc",
    "https://wns2-par02p.notify.windows.com/w/?token=abc",
    "https://api.push.apple.com/3/device/abc",
])
def test_push_allows_known_services(client, authed, endpoint):
    assert _sub(client, authed, endpoint).status_code == 200


@pytest.mark.parametrize("endpoint", [
    "https://evil.example.com/push",
    "http://fcm.googleapis.com/fcm/send/abc",
    "https://fcm.googleapis.com.evil.com/x",
    "https://evilnotify.windows.com/x",
    "https://127.0.0.1/x",
    "https://user@evil.com/fcm.googleapis.com",
])
def test_push_rejects_other_hosts(client, authed, endpoint):
    assert _sub(client, authed, endpoint).status_code == 400


def test_push_never_deletes_another_users_subscription(client, db, authed, make_household):
    endpoint = "https://fcm.googleapis.com/fcm/send/shared"
    other = make_household(name="Other", username="pushother")
    db.add(PushSubscription(user_id=other.user_id, household_id=other.household_id,
                            endpoint=endpoint, p256dh="x", auth="y"))
    db.commit()

    r = _sub(client, authed, endpoint)

    assert r.status_code == 409
    db.expire_all()
    rows = db.query(PushSubscription).filter_by(endpoint=endpoint).all()
    assert [row.user_id for row in rows] == [other.user_id]


# ---------------------------------------------------------------------------
# Invites are owner-only
# ---------------------------------------------------------------------------

def test_member_cannot_create_html_invite(client, db, authed, login):
    member = _add_member(db, authed.household_id, "plainmember")
    db.commit()
    client.post("/logout", headers=authed.headers)
    headers = login(member.username, member.totp_secret)
    r = client.post("/settings/invite", headers=headers)
    assert r.status_code == 403
    assert db.query(Invitation).count() == 0


def test_owner_can_create_html_invite(client, authed):
    r = client.post("/settings/invite", headers={**authed.headers, "HX-Request": "true"})
    assert r.status_code == 200


def test_member_cannot_create_api_invite(client, db, authed):
    member = _add_member(db, authed.household_id, "apimember")
    db.commit()
    r = client.post("/api/v1/auth/login", json={"username": member.username, "password": PASSWORD})
    pending = r.json()["pending_token"]
    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": pending, "code": pyotp.TOTP(member.totp_secret).now()})
    token = r.json()["access_token"]
    r = client.post("/api/v1/settings/household/invite",
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_invite_link_uses_app_base_url_not_host_header(client, authed, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "app_base_url", "https://expenses.example.org/")
    r = client.post("/settings/invite",
                    headers={**authed.headers, "HX-Request": "true", "Host": "evil.test"})
    assert r.status_code == 200
    assert "https://expenses.example.org/join/" in r.text
    assert "evil.test" not in r.text


def test_production_requires_app_base_url():
    from app.config import Settings

    with pytest.raises(RuntimeError, match="APP_BASE_URL"):
        Settings(debug=False, app_secret_key="x" * 40, app_base_url=None, _env_file=None)
    Settings(debug=False, app_secret_key="x" * 40, app_base_url="https://a.example", _env_file=None)


# ---------------------------------------------------------------------------
# Upload sniffing
# ---------------------------------------------------------------------------

def test_sniff_upload_kinds():
    from app.validators import sniff_upload

    assert sniff_upload(b"\xff\xd8\xff\xe0" + b"0" * 12) == "jpg"
    assert sniff_upload(PNG[:16]) == "png"
    assert sniff_upload(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert sniff_upload(PDF[:16]) == "pdf"
    assert sniff_upload(HEIC[:16]) == "heic"
    assert sniff_upload(b"\x00\x00\x00\x18ftypisom" + b"0" * 4) is None
    assert sniff_upload(b"<html><script>") is None
    assert sniff_upload(b"") is None


def _html_upload(client, authed, name, content):
    return client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "expense",
    }, files={"receipt": (name, io.BytesIO(content), "image/jpeg")}, headers=authed.headers)


def test_html_upload_rejects_pdf_named_jpg(client, authed):
    assert _html_upload(client, authed, "r.jpg", PDF).status_code == 400


def test_html_upload_rejects_garbage_named_png(client, authed):
    assert _html_upload(client, authed, "r.png", b"<script>alert(1)</script>").status_code == 400


def test_html_upload_accepts_real_png(client, authed):
    assert _html_upload(client, authed, "r.png", PNG).status_code == 302


@pytest.fixture()
def api_txn(db, authed):
    from app.api_auth import create_access_token

    txn = Transaction(bucket_id=authed.bucket_id, household_id=authed.household_id, amount=5,
                      currency="EUR", exchange_rate=1, type=TransactionType.expense,
                      transaction_date=date.today(), paid_by=authed.user_id)
    db.add(txn)
    db.commit()
    user = db.get(User, authed.user_id)
    token = create_access_token(user.id, authed.household_id, user.session_version)
    return txn.id, {"Authorization": f"Bearer {token}"}


def test_api_upload_rejects_pdf_named_jpg(client, api_txn):
    txn_id, headers = api_txn
    r = client.post(f"/api/v1/transactions/{txn_id}/receipt",
                    files={"file": ("r.jpg", io.BytesIO(PDF), "image/jpeg")}, headers=headers)
    assert r.status_code == 400


def test_api_upload_accepts_real_files(client, api_txn):
    txn_id, headers = api_txn
    for name, body in (("r.png", PNG), ("r.pdf", PDF), ("r.heic", HEIC)):
        r = client.post(f"/api/v1/transactions/{txn_id}/receipt",
                        files={"file": (name, io.BytesIO(body), "application/octet-stream")},
                        headers=headers)
        assert r.status_code == 200, (name, r.text)


# ---------------------------------------------------------------------------
# Login CSRF (pre-session token)
# ---------------------------------------------------------------------------

def _token(html):
    m = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    assert m, "no _csrf_token field rendered"
    return m.group(1)


def _password_step(client, hh):
    r = client.post("/login", data={"username": hh.username, "password": PASSWORD,
                                    "_csrf_token": _token(client.get("/login").text)})
    assert r.status_code == 302


def test_login_without_token_is_forbidden(client, make_household):
    hh = make_household()
    r = client.post("/login", data={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 403


def test_login_with_garbage_token_is_forbidden(client, make_household):
    hh = make_household()
    r = client.post("/login", data={"username": hh.username, "password": PASSWORD,
                                    "_csrf_token": "nope"})
    assert r.status_code == 403


def test_login_with_token_works(client, make_household):
    hh = make_household()
    _password_step(client, hh)


def test_login_accepts_header_token(client, make_household):
    hh = make_household()
    token = _token(client.get("/login").text)
    r = client.post("/login", data={"username": hh.username, "password": PASSWORD},
                    headers={"X-CSRF-Token": token})
    assert r.status_code == 302


def test_expired_pre_session_token_is_rejected(client, make_household, monkeypatch):
    import app.auth as auth

    hh = make_household()
    token = _token(client.get("/login").text)
    real = auth._pre_csrf_serializer.loads
    monkeypatch.setattr(auth._pre_csrf_serializer, "loads",
                        lambda t, max_age=None: real(t, max_age=-1))
    r = client.post("/login", data={"username": hh.username, "password": PASSWORD,
                                    "_csrf_token": token})
    assert r.status_code == 403


def test_user_csrf_token_is_not_a_pre_session_token(client, make_household):
    """A signed double-submit token for a user must not unlock the login form."""
    from app.auth import generate_csrf_token

    hh = make_household()
    r = client.post("/login", data={"username": hh.username, "password": PASSWORD,
                                    "_csrf_token": generate_csrf_token(hh.user_id)})
    assert r.status_code == 403


def test_verify_totp_requires_token(client, make_household):
    hh = make_household()
    _password_step(client, hh)
    code = pyotp.TOTP(hh.secret).now()
    assert client.post("/login/verify", data={"code": code}).status_code == 403
    r = client.post("/login/verify", data={
        "code": code, "_csrf_token": _token(client.get("/login/verify").text)})
    assert r.status_code == 302


def test_backup_verify_requires_token(client, make_household):
    hh = make_household()
    _password_step(client, hh)
    r = client.post("/login/verify/backup", data={"backup_code": "AAAA1111"})
    assert r.status_code == 403
    r = client.post("/login/verify/backup", data={
        "backup_code": "AAAA1111",
        "_csrf_token": _token(client.get("/login/verify/backup").text)})
    assert r.status_code != 403


def test_setup_requires_token(client):
    data = {"household_name": "Home", "display_name": "Ann", "username": "ann",
            "email": "ann@example.com", "password": "a-very-long-password"}
    assert client.post("/setup", data=data).status_code == 403
    r = client.post("/setup", data={**data, "_csrf_token": _token(client.get("/setup").text)})
    assert r.status_code == 302


def test_enroll_requires_token(client, db):
    client.post("/setup", data={
        "household_name": "Home", "display_name": "Ann", "username": "ann",
        "email": "ann@example.com", "password": "a-very-long-password",
        "_csrf_token": _token(client.get("/setup").text)})
    page = client.get("/settings/2fa/enroll")
    secret = db.query(User).filter_by(username="ann").one().totp_secret
    code = pyotp.TOTP(secret).now()
    assert client.post("/settings/2fa/enroll", data={"code": code}).status_code == 403
    r = client.post("/settings/2fa/enroll", data={"code": code, "_csrf_token": _token(page.text)})
    assert r.status_code == 200


def test_join_requires_token(client, db, authed):
    db.add(Invitation(household_id=authed.household_id, token="tok123", created_by=authed.user_id,
                      expires_at=datetime.utcnow() + timedelta(days=1)))
    db.commit()
    anon = TestClient(client.app, follow_redirects=False)
    data = {"display_name": "New", "username": "newbie", "email": "n@example.com",
            "password": "a-very-long-password"}
    assert anon.post("/join/tok123", data=data).status_code == 403
    r = anon.post("/join/tok123",
                  data={**data, "_csrf_token": _token(anon.get("/join/tok123").text)})
    assert r.status_code == 302


def test_api_login_unaffected_by_csrf(client, make_household):
    hh = make_household()
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 200


def test_authenticated_double_submit_unchanged(client, authed):
    assert client.post("/buckets", data={"name": "x", "type": "custom"}).status_code == 403
    assert client.post("/buckets", data={"name": "x", "type": "custom"},
                       headers=authed.headers).status_code in (200, 302)

"""Final fix wave (F1): security regressions found in the branch review."""
import time
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient

from app.models import User
from tests.conftest import PASSWORD, form_csrf
from tests.test_household_settlement import _add_member


def _next_totp(secret):
    return pyotp.TOTP(secret).at(time.time() + 30)


def _login_client(app, username, secret):
    """A second browser, logged in through the real password + TOTP flow."""
    c = TestClient(app, follow_redirects=False)
    r = c.post("/login", data={"username": username, "password": PASSWORD,
                               **form_csrf(c, "/login")})
    assert r.status_code == 302
    r = c.post("/login/verify", data={"code": pyotp.TOTP(secret).now(),
                                      **form_csrf(c, "/login/verify")})
    assert r.status_code == 302, r.text
    return c


# ---------------------------------------------------------------------------
# C2: an invalidated session cookie must not reach 2FA enrollment
# ---------------------------------------------------------------------------

def _member_with_reset_2fa(app, client, db, authed):
    bob = _add_member(db, authed.household_id, "bob")
    db.commit()
    bob_secret = bob.totp_secret  # plaintext in the fixture
    bob_client = _login_client(app, "bob", bob_secret)
    assert bob_client.get("/dashboard").status_code == 200
    r = client.post(f"/settings/2fa/reset/{bob.id}", headers=authed.headers,
                    data={"owner_code": _next_totp(authed.secret)})
    assert r.status_code == 302, r.text
    return bob, bob_client


def test_stale_cookie_after_owner_reset_cannot_view_enroll(app, client, db, authed):
    bob, bob_client = _member_with_reset_2fa(app, client, db, authed)
    r = bob_client.get("/settings/2fa/enroll")
    assert r.status_code == 302
    assert r.headers["location"] == "/login"
    db.expire_all()
    assert db.get(User, bob.id).totp_secret is None


def test_stale_cookie_after_owner_reset_cannot_enroll(app, client, db, authed):
    bob, bob_client = _member_with_reset_2fa(app, client, db, authed)
    # Even with a pending secret already on the row (e.g. Bob's real browser
    # started enrolling), the old cookie must not confirm it.
    attacker_secret = pyotp.random_base32()
    u = db.get(User, bob.id)
    u.set_totp_secret(attacker_secret)
    db.commit()
    r = bob_client.post("/settings/2fa/enroll",
                        data={"code": pyotp.TOTP(attacker_secret).now(),
                              "_csrf_token": "x"},
                        headers={"X-CSRF-Token": bob_client.cookies.get("csrf_token", "")})
    assert r.status_code == 302
    assert r.headers["location"] == "/login"
    assert "session=" not in r.headers.get("set-cookie", "").replace("session=;", "")
    db.expire_all()
    assert db.get(User, bob.id).totp_enabled is False


def test_member_can_re_enroll_after_owner_reset(app, client, db, authed):
    """After a reset, Bob logs in again and his first new code is accepted
    (last_totp_step from the old secret must not block it)."""
    bob, _ = _member_with_reset_2fa(app, client, db, authed)
    db.expire_all()
    assert db.get(User, bob.id).last_totp_step is None
    fresh = TestClient(app, follow_redirects=False)
    r = fresh.post("/login", data={"username": "bob", "password": PASSWORD,
                                   **form_csrf(fresh, "/login")})
    assert r.headers["location"] == "/settings/2fa/enroll"
    assert fresh.get("/settings/2fa/enroll").status_code == 200
    db.expire_all()
    new_secret = db.get(User, bob.id).get_totp_secret()
    r = fresh.post("/settings/2fa/enroll", data={"code": pyotp.TOTP(new_secret).now(),
                                                 **form_csrf(fresh, "/settings/2fa/enroll")})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(User, bob.id).totp_enabled is True


def test_self_disable_then_re_enroll_in_same_browser(client, db, authed):
    """The legit browser holds a stale session cookie next to the new pending
    cookie; the pending path must still work, and the first code of the new
    secret must be accepted even though the disable claimed a later step."""
    r = client.post("/settings/2fa/disable", headers=authed.headers, data={
        "current_password": PASSWORD, "code": _next_totp(authed.secret)})
    assert r.status_code == 302
    assert r.headers["location"] == "/settings/2fa/enroll"
    db.expire_all()
    assert db.get(User, authed.user_id).last_totp_step is None

    r = client.get("/settings/2fa/enroll")
    assert r.status_code == 200
    db.expire_all()
    new_secret = db.get(User, authed.user_id).get_totp_secret()
    r = client.post("/settings/2fa/enroll", data={"code": pyotp.TOTP(new_secret).now(),
                                                  **form_csrf(client, "/settings/2fa/enroll")})
    assert r.status_code == 200, r.text
    assert "session=" in r.headers.get("set-cookie", "")
    db.expire_all()
    assert db.get(User, authed.user_id).totp_enabled is True
    assert client.get("/dashboard").status_code == 200


# ---------------------------------------------------------------------------
# A11: current-password checks count towards the account lockout
# ---------------------------------------------------------------------------

def _almost_locked(db, user_id):
    from app.auth import LOCKOUT_THRESHOLD

    u = db.get(User, user_id)
    u.failed_logins = LOCKOUT_THRESHOLD - 1
    db.commit()


def _assert_locked(db, user_id):
    db.expire_all()
    assert db.get(User, user_id).locked_until is not None


def test_html_password_change_wrong_password_locks(client, db, authed):
    _almost_locked(db, authed.user_id)
    r = client.post("/settings/profile/password", headers=authed.headers, data={
        "current_password": "wrong-password-xx", "new_password": "another-long-password"})
    assert r.status_code == 200
    _assert_locked(db, authed.user_id)
    before = db.get(User, authed.user_id).password_hash
    # Locked: even the right password is refused now.
    r = client.post("/settings/profile/password", headers=authed.headers, data={
        "current_password": PASSWORD, "new_password": "another-long-password"})
    assert r.status_code == 200
    assert "locked" in r.text.lower()
    db.expire_all()
    assert db.get(User, authed.user_id).password_hash == before


def test_html_2fa_disable_wrong_password_locks(client, db, authed):
    _almost_locked(db, authed.user_id)
    r = client.post("/settings/2fa/disable", headers=authed.headers, data={
        "current_password": "wrong-password-xx", "code": _next_totp(authed.secret)})
    assert r.status_code == 200
    _assert_locked(db, authed.user_id)
    r = client.post("/settings/2fa/disable", headers=authed.headers, data={
        "current_password": PASSWORD, "code": pyotp.TOTP(authed.secret).at(time.time() + 60)})
    assert r.status_code == 200
    assert "locked" in r.text.lower()
    db.expire_all()
    assert db.get(User, authed.user_id).totp_enabled is True


def test_html_2fa_disable_wrong_code_counts(client, db, authed):
    _almost_locked(db, authed.user_id)
    r = client.post("/settings/2fa/disable", headers=authed.headers, data={
        "current_password": PASSWORD, "code": "000000"})
    assert r.status_code == 200
    _assert_locked(db, authed.user_id)


def test_api_password_change_wrong_password_locks(client, db, make_household):
    hh = make_household()
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": r.json()["pending_token"],
                          "code": pyotp.TOTP(hh.secret).now()})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    _almost_locked(db, hh.user_id)
    r = client.post("/api/v1/settings/profile/password", headers=headers, json={
        "current_password": "wrong-password-xx", "new_password": "another-long-password"})
    assert r.status_code == 400
    _assert_locked(db, hh.user_id)
    r = client.post("/api/v1/settings/profile/password", headers=headers, json={
        "current_password": PASSWORD, "new_password": "another-long-password"})
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# A5 / A9: production guard — encryption key and placeholder secrets
# ---------------------------------------------------------------------------

def _prod(**kw):
    from app.core.config import Settings

    base = {"debug": False, "app_secret_key": "a1" * 32,
            "app_base_url": "https://a.example", "_env_file": None}
    base.update(kw)
    return Settings(**base)


def test_malformed_field_encryption_key_is_a_startup_error():
    from cryptography.fernet import Fernet

    with pytest.raises(RuntimeError, match="FIELD_ENCRYPTION_KEY"):
        _prod(field_encryption_key="not-a-fernet-key")
    _prod(field_encryption_key=Fernet.generate_key().decode())
    _prod(field_encryption_key=None)


def test_placeholder_app_secret_key_is_rejected_in_production():
    with pytest.raises(RuntimeError, match="placeholder"):
        _prod(app_secret_key="change-me-in-production-use-a-long-random-string")
    with pytest.raises(RuntimeError, match="placeholder"):
        _prod(app_secret_key="CHANGE-ME-please-this-is-long-enough-for-32")


def test_ingest_url_uses_app_base_url(client, authed, monkeypatch):
    """Behind the proxy request.base_url is http://; the Shortcut needs https."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_base_url", "https://expenses.example.org/")
    text = client.get("/settings/automations").text
    assert "https://expenses.example.org/api/v1/ingest/apple-pay" in text
    assert "http://testserver/api/v1/ingest" not in text


def test_token_page_is_kept_out_of_htmx_history(client, authed):
    """hx-boost would push /settings/automations/tokens (refresh -> 405) and
    snapshot the page, plaintext pat_ token included, into localStorage."""
    import re

    r = client.post("/settings/automations/tokens", headers=authed.headers,
                    data={"name": "Phone"})
    assert "pat_" in r.text
    assert 'hx-history="false"' in r.text
    form = re.search(r'<form[^>]*action="/settings/automations/tokens"[^>]*>', r.text)
    assert form and 'hx-push-url="false"' in form.group(0)


def test_env_example_is_production_safe():
    text = (Path(__file__).resolve().parent.parent / ".env.example").read_text()
    assert "\nDEBUG=false" in text
    assert "\nDEBUG=true" not in text

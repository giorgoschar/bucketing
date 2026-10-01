"""Final fix wave (F1): security regressions found in the branch review."""
import time

import pyotp
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

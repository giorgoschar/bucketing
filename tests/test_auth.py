"""Authentication, 2FA enrollment and session handling."""
import json

import pyotp
import pytest

from app.models import User
from tests.conftest import PASSWORD


def test_first_run_redirects_to_setup(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["location"] == "/setup"


def test_setup_creates_owner_and_requires_2fa(client, db):
    r = client.post("/setup", data={
        "household_name": "Home", "display_name": "Ann", "username": "ann",
        "email": "ann@example.com", "password": "a-very-long-password",
    })
    assert r.status_code == 302
    assert r.headers["location"] == "/settings/2fa/enroll"
    assert db.query(User).filter_by(username="ann").one().totp_enabled is False


def test_setup_rejects_short_password(client, db):
    r = client.post("/setup", data={
        "household_name": "Home", "display_name": "Ann", "username": "ann",
        "email": "ann@example.com", "password": "short",
    })
    assert r.status_code == 200
    assert "at least 12 characters" in r.text
    assert db.query(User).count() == 0


def test_login_with_wrong_password_fails(client, make_household):
    hh = make_household()
    r = client.post("/login", data={"username": hh.username, "password": "wrong-password"})
    assert r.status_code == 200
    assert "Invalid username or password" in r.text


def test_login_with_unknown_user_gives_same_message(client, make_household):
    """No user enumeration through differing responses."""
    make_household()
    r = client.post("/login", data={"username": "nobody", "password": "whatever-long"})
    assert r.status_code == 200
    assert "Invalid username or password" in r.text


def test_login_by_email_works(client, make_household):
    hh = make_household()
    r = client.post("/login", data={"username": f"{hh.username}@example.com",
                                    "password": PASSWORD})
    assert r.status_code == 302
    assert r.headers["location"] == "/login/verify"


def test_password_alone_does_not_grant_access(client, make_household):
    hh = make_household()
    client.post("/login", data={"username": hh.username, "password": PASSWORD})
    r = client.get("/dashboard")
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


def test_wrong_totp_code_is_rejected(client, make_household):
    hh = make_household()
    client.post("/login", data={"username": hh.username, "password": PASSWORD})
    r = client.post("/login/verify", data={"code": "000000"})
    assert r.status_code == 200
    assert "Invalid code" in r.text


def test_full_login_reaches_dashboard(client, authed):
    assert client.get("/dashboard").status_code == 200


# ---------------------------------------------------------------------------
# TOTP enrollment
# ---------------------------------------------------------------------------

def test_enroll_secret_is_not_taken_from_the_request(client, db):
    """The server holds the pending secret; a client-supplied one is ignored."""
    client.post("/setup", data={
        "household_name": "Home", "display_name": "Ann", "username": "ann",
        "email": "ann@example.com", "password": "a-very-long-password",
    })
    client.get("/settings/2fa/enroll")
    server_secret = db.query(User).filter_by(username="ann").one().totp_secret
    assert server_secret

    attacker_secret = pyotp.random_base32()
    assert attacker_secret != server_secret

    # A code for the attacker's secret must not enroll.
    r = client.post("/settings/2fa/enroll", data={
        "secret": attacker_secret, "code": pyotp.TOTP(attacker_secret).now(),
    })
    db.expire_all()
    user = db.query(User).filter_by(username="ann").one()
    assert user.totp_enabled is False
    assert user.totp_secret == server_secret

    # The server's own secret does enroll.
    r = client.post("/settings/2fa/enroll", data={"code": pyotp.TOTP(server_secret).now()})
    assert r.status_code == 200
    db.expire_all()
    user = db.query(User).filter_by(username="ann").one()
    assert user.totp_enabled is True
    assert user.totp_secret == server_secret


def test_enroll_page_reuses_pending_secret(client, db):
    """Reloading the QR page must not invalidate an already-scanned code."""
    client.post("/setup", data={
        "household_name": "Home", "display_name": "Ann", "username": "ann",
        "email": "ann@example.com", "password": "a-very-long-password",
    })
    client.get("/settings/2fa/enroll")
    first = db.query(User).filter_by(username="ann").one().totp_secret
    client.get("/settings/2fa/enroll")
    db.expire_all()
    assert db.query(User).filter_by(username="ann").one().totp_secret == first


def test_enrolled_user_cannot_re_enroll(client, db, authed):
    """Re-enrollment would let a stolen session swap in an attacker's secret."""
    before = db.get(User, authed.user_id).totp_secret
    new_secret = pyotp.random_base32()

    r = client.post("/settings/2fa/enroll",
                    data={"secret": new_secret, "code": pyotp.TOTP(new_secret).now()},
                    headers=authed.headers)

    assert r.status_code == 302
    assert r.headers["location"] == "/settings"
    db.expire_all()
    assert db.get(User, authed.user_id).totp_secret == before


def test_backup_code_logs_in_and_is_consumed(client, db, make_household):
    import bcrypt

    hh = make_household()
    user = db.get(User, hh.user_id)
    codes = ["AAAA1111", "BBBB2222"]
    user.totp_backup_codes = json.dumps(
        [bcrypt.hashpw(c.encode(), bcrypt.gensalt()).decode() for c in codes]
    )
    db.commit()

    client.post("/login", data={"username": hh.username, "password": PASSWORD})
    r = client.post("/login/verify/backup", data={"backup_code": "AAAA1111"})
    assert r.status_code == 302
    assert client.get("/dashboard").status_code == 200

    db.expire_all()
    remaining = json.loads(db.get(User, hh.user_id).totp_backup_codes)
    assert len(remaining) == 1


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def test_password_change_keeps_current_session(client, db, authed):
    """Bumping session_version must not log out the device that changed it."""
    r = client.post("/settings/profile/password", data={
        "current_password": PASSWORD, "new_password": "another-long-password",
    }, headers=authed.headers)
    assert r.status_code == 302
    assert "pw_changed" in r.headers["location"]
    assert client.get("/dashboard").status_code == 200


def test_password_change_rejects_wrong_current(client, authed):
    r = client.post("/settings/profile/password", data={
        "current_password": "not-the-password", "new_password": "another-long-password",
    }, headers=authed.headers)
    assert r.status_code == 200
    assert "incorrect" in r.text.lower()


def test_password_change_invalidates_other_sessions(app, client, db, authed):
    from fastapi.testclient import TestClient

    other = TestClient(app, follow_redirects=False)
    other.post("/login", data={"username": authed.username, "password": PASSWORD})
    other.post("/login/verify", data={"code": pyotp.TOTP(authed.secret).now()})
    assert other.get("/dashboard").status_code == 200

    client.post("/settings/profile/password", data={
        "current_password": PASSWORD, "new_password": "another-long-password",
    }, headers=authed.headers)

    assert other.get("/dashboard").status_code == 302


def test_state_changing_request_requires_csrf(client, authed):
    r = client.post("/buckets", data={"name": "No CSRF", "type": "custom"})
    assert r.status_code == 403


def test_logout_clears_session(client, authed):
    client.post("/logout", headers=authed.headers)
    assert client.get("/dashboard").status_code == 302

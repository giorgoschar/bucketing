"""2d §7.5: /api/v1/settings/security. 2FA set up, turned on and off from the
new app; the HTML routes behave as before (tests/test_auth.py)."""

import time

import pyotp

from app.auth import COOKIE_NAME, _serializer
from app.core.config import settings
from app.models import User
from tests.conftest import PASSWORD
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/settings/security"


def _later(secret, n=1):
    """login() spent the current step; a later one is still inside valid_window."""
    return pyotp.TOTP(secret).at(time.time() + 30 * n)


def test_get_reports_the_state(client, db, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    body = client.get(URL).json()
    assert body == {
        "totp_enabled": True,
        "backup_codes_remaining": 0,
        "passkey_available": bool(settings.new_app_enabled and settings.oidc_enabled),
        "passkey_linked": False,
        "password_session": True,
    }


def test_bearer_counts_as_a_password_session(client, api):  # noqa: F811
    headers, _ = api
    assert client.get(URL, headers=headers).json()["password_session"] is True


def test_a_passkey_session_is_not_a_password_session(client, db, make_household):
    hh = make_household()
    user = db.get(User, hh.user_id)
    user.oidc_subject = "sub-1"
    db.commit()
    # The payload set_session(..., amr="oidc") writes, sent as a raw Cookie header
    # (the test client's jar would need the cookie's domain).
    cookie = _serializer.dumps(
        {
            "user_id": hh.user_id,
            "hh_id": hh.household_id,
            "sv": 0,
            "state": "authenticated",
            "amr": "oidc",
            "iat": int(time.time()),
        }
    )
    body = client.get(URL, headers={"Cookie": f"{COOKIE_NAME}={cookie}"}).json()
    assert (body["password_session"], body["passkey_linked"]) == (False, True)


def test_disable_needs_password_and_code(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = client.post(
        f"{URL}/totp/disable",
        headers=headers,
        json={"current_password": "wrong", "code": _later(hh.secret)},
    )
    assert (r.status_code, r.json()["detail"]) == (400, "Incorrect password.")
    r = client.post(
        f"{URL}/totp/disable",
        headers=headers,
        json={"current_password": PASSWORD, "code": "000000"},
    )
    assert (r.status_code, r.json()["detail"]) == (400, "Invalid authenticator code.")
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.totp_enabled and user.failed_logins == 2


def test_disable_keeps_the_caller_signed_in_for_setup(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = client.post(
        f"{URL}/totp/disable",
        headers=headers,
        json={"current_password": PASSWORD, "code": _later(hh.secret)},
    )
    assert r.status_code == 204, r.text
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert (user.totp_enabled, user.totp_secret, user.totp_backup_codes) == (False, None, None)
    # The reissued cookie reaches the security endpoints...
    assert client.get(URL).json()["totp_enabled"] is False
    # ...and nothing else until 2FA is back (2FA is mandatory for password sign-in).
    assert client.get("/api/v1/auth/me").status_code == 403

    csrf = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    setup = client.post(f"{URL}/totp/setup", headers=csrf)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert client.post(f"{URL}/totp/setup", headers=csrf).json()["secret"] == secret  # reused

    bad = client.post(f"{URL}/totp/enable", headers=csrf, json={"code": "000000"})
    assert (bad.status_code, bad.json()["detail"]) == (400, "Invalid code. Please try again.")
    ok = client.post(f"{URL}/totp/enable", headers=csrf, json={"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200, ok.text
    codes = ok.json()["backup_codes"]
    assert len(codes) == 8 and len(set(codes)) == 8
    assert client.get(URL).json()["backup_codes_remaining"] == 8
    assert client.get("/api/v1/auth/me").status_code == 200


def test_setup_and_enable_are_409_when_on(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    assert client.post(f"{URL}/totp/setup", headers=headers).status_code == 409
    assert (
        client.post(f"{URL}/totp/enable", headers=headers, json={"code": "123456"}).status_code
        == 409
    )


def test_setup_is_rate_limited(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    codes = [client.post(f"{URL}/totp/setup", headers=headers).status_code for _ in range(11)]
    assert codes[:10] == [409] * 10 and codes[10] == 429


def test_disable_when_locked_is_429(client, db, make_household, login):
    from datetime import timedelta

    from app.core.clock import utcnow_naive

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.locked_until = utcnow_naive() + timedelta(minutes=10)
    db.commit()
    r = client.post(
        f"{URL}/totp/disable",
        headers=headers,
        json={"current_password": PASSWORD, "code": _later(hh.secret)},
    )
    assert r.status_code == 429


def test_profile_name_must_be_1_to_100(client, api):  # noqa: F811
    headers, _ = api
    for name in ("", "   ", "x" * 101):
        r = client.put(
            "/api/v1/settings/profile",
            headers=headers,
            json={"display_name": name, "avatar_color": "#6366f1"},
        )
        assert r.status_code == 400, name

"""Sign-in alerts: every household member hears about sign-ins and about a
correct password followed by a wrong 2FA code."""
import pyotp
import pytest

from app.login_alerts import describe_device
from app.models import Notification
from tests.conftest import PASSWORD, form_csrf
from tests.test_isolation import _add_member_user, _api_login

IPHONE_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")


def _alerts(db, user_id):
    db.expire_all()
    return db.query(Notification).filter_by(user_id=user_id).order_by(Notification.created_at).all()


def _password_step(client, username):
    r = client.post("/login", data={"username": username, "password": PASSWORD,
                                    **form_csrf(client, "/login")})
    assert r.status_code == 302


def test_web_sign_in_alerts_every_member(client, db, make_household):
    hh = make_household(username="owner")
    member, _ = _add_member_user(db, hh.household_id, username="flatmate")

    _password_step(client, "owner")
    r = client.post("/login/verify", headers={"User-Agent": IPHONE_SAFARI},
                    data={"code": pyotp.TOTP(hh.secret).now(), **form_csrf(client, "/login/verify")})
    assert r.status_code == 302 and r.headers["location"] == "/dashboard"

    for uid in (hh.user_id, member.id):
        [alert] = _alerts(db, uid)
        assert alert.title == "New sign-in: Owner"
        assert "Safari on iPhone" in alert.body and "IP " in alert.body
        assert alert.household_id == hh.household_id


def test_wrong_2fa_code_after_correct_password_alerts_once_per_hour(client, db, make_household):
    hh = make_household(username="owner")
    member, _ = _add_member_user(db, hh.household_id, username="flatmate")

    _password_step(client, "owner")
    for _ in range(3):
        r = client.post("/login/verify", data={"code": "000000", **form_csrf(client, "/login/verify")})
        assert r.status_code == 200

    for uid in (hh.user_id, member.id):
        [alert] = _alerts(db, uid)
        assert alert.title == "Wrong 2FA code for Owner"
        assert "correct password" in alert.body


def test_wrong_password_alone_does_not_alert(client, db, make_household):
    hh = make_household(username="owner")
    client.post("/login", data={"username": "owner", "password": "wrong-password-123",
                                **form_csrf(client, "/login")})
    assert _alerts(db, hh.user_id) == []


def test_backup_code_sign_in_says_so(client, db, make_household):
    import json

    import bcrypt

    from app.models import User

    hh = make_household(username="owner")
    user = db.get(User, hh.user_id)
    user.totp_backup_codes = json.dumps([bcrypt.hashpw(b"ABCDE12345", bcrypt.gensalt()).decode()])
    db.commit()

    _password_step(client, "owner")
    r = client.post("/login/verify/backup", data={"backup_code": "ABCDE12345",
                                                  **form_csrf(client, "/login/verify/backup")})
    assert r.status_code == 302

    [alert] = _alerts(db, hh.user_id)
    assert "using a backup code (0 left)" in alert.body


def test_api_sign_in_and_failed_code_alert(client, db, make_household):
    hh = make_household(username="owner")

    _api_login(client, "owner", hh.secret)
    [alert] = _alerts(db, hh.user_id)
    assert alert.title == "New sign-in: Owner" and "the mobile app" in alert.body

    r = client.post("/api/v1/auth/login", json={"username": "owner", "password": PASSWORD})
    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": r.json()["pending_token"], "code": "000000"})
    assert r.status_code == 401
    assert _alerts(db, hh.user_id)[-1].title == "Wrong 2FA code for Owner"


def test_alert_failure_never_blocks_sign_in(client, db, make_household, monkeypatch):
    hh = make_household(username="owner")

    def boom(*a, **k):
        raise RuntimeError("push service down")

    monkeypatch.setattr("app.notification_service.send_push_for_notification", boom)
    _password_step(client, "owner")
    r = client.post("/login/verify", data={"code": pyotp.TOTP(hh.secret).now(),
                                           **form_csrf(client, "/login/verify")})
    assert r.status_code == 302 and r.headers["location"] == "/dashboard"
    assert client.get("/dashboard").status_code == 200


@pytest.mark.parametrize("ua, expected", [
    (IPHONE_SAFARI, "Safari on iPhone"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/130.0 Safari/537.36", "Chrome on Mac"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/130.0 Safari/537.36 Edg/130.0", "Edge on Windows"),
    ("python-httpx/0.28.1", "unknown device"),
    (None, "unknown device"),
])
def test_describe_device(ua, expected):
    assert describe_device(ua) == expected

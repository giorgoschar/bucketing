from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models import Household, HouseholdMember, User


@pytest.fixture(autouse=True)
def _oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "new_app_enabled", True)
    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example.test")
    monkeypatch.setattr(settings, "oidc_client_id", "cid")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")


@pytest.fixture(autouse=True)
def _live_oidc_transactions(client, monkeypatch):
    """These tests drive the callback with a canned state ("s"). Real states are random
    and bound to a transaction started by /login or /link, so: make every state "s",
    and start a (prompted) transaction before a callback that has none pending."""
    from starlette.responses import RedirectResponse

    monkeypatch.setattr("app.web_app.secrets.token_urlsafe", lambda n=32: "s")
    started = {"live": False}
    real_get, real_post = client.get, client.post

    def get(url, *a, **kw):
        if url.startswith("/app/auth/login"):
            started["live"] = True
        elif url.startswith("/app/auth/callback"):
            if not started["live"] and "state=s" in url:
                stub = AsyncMock()
                stub.authorize_redirect.return_value = RedirectResponse("https://id.example.test/a")
                with patch("app.web_app.oidc_client", return_value=stub):
                    real_get("/app/auth/login")
            started["live"] = False
        return real_get(url, *a, **kw)

    def post(url, *a, **kw):
        if url.startswith("/app/auth/link"):
            started["live"] = True
        return real_post(url, *a, **kw)

    monkeypatch.setattr(client, "get", get)
    monkeypatch.setattr(client, "post", post)


def _member(db, email="g@x.t", sub="s1"):
    u = User(username="g", email=email, display_name="G", password_hash="x", oidc_subject=sub)
    h = Household(name="Home")
    db.add_all([u, h])
    db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=u.id, role="owner"))
    db.commit()
    return u, h


def _fake_client(userinfo=None, exc=None):
    c = AsyncMock()
    if exc:
        c.authorize_access_token.side_effect = exc
    else:
        c.authorize_access_token.return_value = {"userinfo": userinfo}
    return c


def test_callback_signs_in_and_redirects_home(client, db):
    u, h = _member(db)
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app/"
    assert client.get("/api/v1/auth/me").json()["id"] == u.id


def test_passkey_sign_in_alerts_every_member(client, db):
    from app.models import Notification

    u, h = _member(db)
    other = User(username="flatmate", email="f@x.t", display_name="F", password_hash="x")
    db.add(other)
    db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=other.id, role="member"))
    db.commit()
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/"
    db.expire_all()
    for uid in (u.id, other.id):
        [alert] = db.query(Notification).filter_by(user_id=uid).all()
        assert alert.title == "New sign-in: G" and "using a passkey" in alert.body
        # The password was never used: the fix is unlinking the passkey.
        assert "unlink the passkey in Settings" in alert.body
        assert "change the password" not in alert.body


def test_callback_unknown_sub_with_matching_verified_email_is_not_linked(client, db):
    u, _ = _member(db, sub=None)
    fake = _fake_client({"sub": "s9", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=not_linked"
    assert client.get("/api/v1/auth/me").status_code == 401
    db.refresh(u)
    assert u.oidc_subject is None


def test_callback_unknown_user_gets_error_and_no_session(client, db):
    fake = _fake_client({"sub": "s1", "email": "nobody@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=not_linked"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_callback_bad_state_is_handled(client, db):
    from authlib.integrations.base_client.errors import MismatchingStateError

    fake = _fake_client(exc=MismatchingStateError())
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=forged", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app/?auth_error=state"


def test_callback_provider_error_param(client):
    r = client.get("/app/auth/callback?error=access_denied", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=denied"


def test_user_without_household_is_refused(client, db):
    u = User(username="g", email="g@x.t", display_name="G", password_hash="x", oidc_subject="s1")
    db.add(u)
    db.commit()
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=no_household"


def test_login_redirects_to_provider(client):
    fake = AsyncMock()
    from starlette.responses import RedirectResponse

    fake.authorize_redirect.return_value = RedirectResponse("https://id.example.test/authorize?x=1")
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://id.example.test/")
    redirect_uri = fake.authorize_redirect.call_args.args[1]
    assert str(redirect_uri).endswith("/app/auth/callback")
    # No trusted-device cookie: a fresh passkey ceremony (quiet sign-in: test_session_rolling).
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_logout_clears_session(client, db):
    u, h = _member(db)
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    csrf = client.cookies.get("csrf_token")
    r = client.post("/app/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_flag_off_hides_everything(client, monkeypatch):
    monkeypatch.setattr(settings, "new_app_enabled", False)
    assert client.get("/app/auth/login", follow_redirects=False).status_code == 404


def test_callback_bad_id_token_is_handled(client):
    from joserfc.errors import InvalidClaimError

    fake = _fake_client(exc=InvalidClaimError("iss"))
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=token"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_callback_provider_unreachable_is_handled(client):
    import httpx

    fake = _fake_client(exc=httpx.ConnectError("down"))
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=provider"
    assert client.get("/api/v1/auth/me").status_code == 401


# --- linking a passkey from a signed-in password + 2FA session -------------


def _redirecting_client(userinfo=None):
    from starlette.responses import RedirectResponse

    c = _fake_client(userinfo)
    c.authorize_redirect.return_value = RedirectResponse("https://id.example.test/authorize?x=1")
    return c


def _link_form(hh, step=1, password=None, code=None):
    """Form for POST /app/auth/link. login() already spent the current TOTP step, so use a later one."""
    import time

    import pyotp

    from tests.conftest import PASSWORD

    return {
        "password": PASSWORD if password is None else password,
        "totp_code": code or pyotp.TOTP(hh.secret).at(time.time() + 30 * step),
    }


def _start_link(client, hh, headers, fake, **form):
    with patch("app.web_app.oidc_client", return_value=fake):
        return client.post(
            "/app/auth/link", data=_link_form(hh, **form), headers=headers, follow_redirects=False
        )


def test_link_flow_links_subject_and_keeps_session(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub", "email": "whatever@x.t"})
    r = _start_link(client, hh, headers, fake)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://id.example.test/")
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"
    assert "oidc_tx" in client.cookies
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?linked=1"
    # Linking is not a sign-in, but a new way into the account: the household hears of it.
    from app.models import Notification

    db.expire_all()
    [alert] = [
        n
        for n in db.query(Notification).filter_by(user_id=hh.user_id)
        if n.title.startswith("Passkey linked")
    ]
    assert alert.body.startswith(f"A passkey was linked to {hh.username.title()}'s account · ")
    assert alert.body.endswith("If this wasn't them, unlink it in Settings.")
    assert not any(
        n.title.startswith("New sign-in") and "passkey" in n.body
        for n in db.query(Notification).filter_by(user_id=hh.user_id)
    )
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject == "new-sub"
    assert client.get("/api/v1/auth/me").json()["id"] == hh.user_id


def test_link_is_post_only(client, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    assert client.get("/app/auth/link", follow_redirects=False).status_code == 405


def test_link_post_without_csrf_is_rejected(client, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    fake = _redirecting_client()
    r = _start_link(client, hh, {}, fake)
    assert r.status_code == 403
    fake.authorize_redirect.assert_not_called()


def test_link_wrong_password_is_refused_and_counted(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client()
    r = _start_link(client, hh, headers, fake, password="nope")
    assert r.headers["location"] == "/settings?passkey_error=1"
    fake.authorize_redirect.assert_not_called()
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.failed_logins == 1


def test_link_wrong_totp_is_refused_and_counted(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client()
    r = _start_link(client, hh, headers, fake, code="000000")
    assert r.headers["location"] == "/settings?passkey_error=1"
    fake.authorize_redirect.assert_not_called()
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.failed_logins == 1


def test_link_conflict_reports_subject_conflict(client, db, make_household, login):
    db.add(
        User(username="o", email="o@x.t", display_name="O", password_hash="x", oidc_subject="taken")
    )
    db.commit()
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "taken"})
    _start_link(client, hh, headers, fake)
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=subject_conflict"


def test_link_without_session_requires_login(client):
    fake = _redirecting_client()
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.post("/app/auth/link", follow_redirects=False)
    # No session: require_csrf demands a pre-session token, so the request never reaches the handler.
    assert r.status_code == 403
    fake.authorize_redirect.assert_not_called()


def test_link_with_oidc_session_requires_login(client, db):
    _member(db)
    fake = _fake_client({"sub": "s1"})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    fake = _redirecting_client()
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.post(
            "/app/auth/link",
            data={"password": "x", "totp_code": "000000"},
            headers=headers,
            follow_redirects=False,
        )
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    fake.authorize_redirect.assert_not_called()


def test_link_for_user_without_totp_requires_login(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.totp_enabled = False
    db.commit()
    fake = _redirecting_client()
    r = _start_link(client, hh, headers, fake)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    fake.authorize_redirect.assert_not_called()


def test_link_callback_after_logout_requires_login(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub"})
    _start_link(client, hh, headers, fake)
    with patch("app.web_app.oidc_client", return_value=fake):
        client.post("/app/auth/logout", headers=headers)
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject is None


def test_link_callback_after_ten_minutes_requires_login(
    client, db, make_household, login, monkeypatch
):
    import time as _time
    import types

    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub"})
    _start_link(client, hh, headers, fake)
    real = _time.time()
    # Only web_app's clock moves; the oidc_tx cookie's own 600s signature age stays untouched.
    monkeypatch.setattr("app.web_app.time", types.SimpleNamespace(time=lambda: real + 601))
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject is None


@pytest.mark.parametrize("failure", ["error_param", "jose"])
def test_abandoned_link_does_not_turn_later_sign_in_into_a_link(
    client, db, make_household, login, failure
):
    from joserfc.errors import InvalidClaimError

    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client()
    _start_link(client, hh, headers, fake)
    if failure == "error_param":
        r = client.get("/app/auth/callback?error=access_denied", follow_redirects=False)
        assert r.headers["location"] == "/app/?auth_error=denied"
    else:
        bad = _fake_client(exc=InvalidClaimError("iss"))
        with patch("app.web_app.oidc_client", return_value=bad):
            r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
        assert r.headers["location"] == "/app/?auth_error=token"
    # Same browser: a fresh /login then a callback with an unknown sub must not link.
    fresh = _redirecting_client({"sub": "attacker-sub"})
    with patch("app.web_app.oidc_client", return_value=fresh):
        client.get("/app/auth/login", follow_redirects=False)
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=not_linked"
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject is None


def test_login_clears_pending_link_state(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "attacker-sub"})
    _start_link(client, hh, headers, fake)
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/login", follow_redirects=False)
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=not_linked"


def test_unlink_clears_subject(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    r = client.post("/app/auth/unlink", headers=headers, follow_redirects=False)
    assert r.headers["location"] == "/settings?passkey=unlinked"
    db.refresh(user)
    assert user.oidc_subject is None


def test_unlink_signs_out_passkey_sessions_but_not_the_unlinker(
    client, db, make_household, login, app
):
    from starlette.testclient import TestClient

    from app.auth import set_session

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    other = TestClient(app, follow_redirects=False)
    from fastapi.responses import Response

    carrier = Response()
    set_session(carrier, user.id, hh.household_id, user.session_version, amr="oidc")
    for cookie in carrier.headers.getlist("set-cookie"):
        name, _, rest = cookie.partition("=")
        other.cookies.set(name, rest.split(";")[0])
    assert other.get("/api/v1/auth/me").status_code == 200

    r = client.post("/app/auth/unlink", headers=headers, follow_redirects=False)
    assert r.headers["location"] == "/settings?passkey=unlinked"
    assert other.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 200


def test_unlink_keeps_shortcut_ingest_tokens(client, db, make_household, login, app):
    from starlette.testclient import TestClient

    from app.models import PersonalApiToken
    from tests.test_personal_tokens import _day2day, _ingest_status, _issue

    hh = make_household()
    _day2day(db, hh.bucket_id)
    record, raw = _issue(db, hh.user_id, hh.household_id)
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    other = TestClient(app, follow_redirects=False)
    for name, value in client.cookies.items():
        other.cookies.set(name, value)
    assert other.get("/api/v1/auth/me").status_code == 200

    r = client.post("/app/auth/unlink", headers=headers, follow_redirects=False)
    assert r.headers["location"] == "/settings?passkey=unlinked"
    assert other.get("/api/v1/auth/me").status_code == 401
    db.expire_all()
    assert db.get(PersonalApiToken, record.id).revoked_at is None
    assert _ingest_status(client, raw) == 201


def test_unlink_without_csrf_is_rejected(client, db, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    r = client.post("/app/auth/unlink", follow_redirects=False)
    assert r.status_code == 403
    db.refresh(user)
    assert user.oidc_subject == "s1"


def test_unlink_with_oidc_session_requires_login(client, db):
    _member(db)
    fake = _fake_client({"sub": "s1"})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    r = client.post("/app/auth/unlink", headers=headers, follow_redirects=False)
    # Back to Settings, where the unlink form lives, not into the new app.
    assert r.headers["location"] == "/settings?passkey_error=1"
    user = db.query(User).filter_by(oidc_subject="s1").first()
    assert user is not None


def test_settings_page_shows_link_then_linked(client, db, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    assert "/app/auth/link" in client.get("/settings").text
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    page = client.get("/settings").text
    assert "Passkey linked" in page and "/app/auth/link" not in page


def test_settings_page_hides_link_when_flag_off(client, make_household, login, monkeypatch):
    hh = make_household()
    login(hh.username, hh.secret)
    monkeypatch.setattr(settings, "new_app_enabled", False)
    assert "/app/auth/link" not in client.get("/settings").text


def test_link_form_is_a_real_navigation_the_csp_lets_reach_pocket_id(
    client, make_household, login, monkeypatch
):
    """The link POST redirects to Pocket ID. hx-boost would turn it into a fetch
    (blocked by connect-src), and browsers check form-action on every redirect hop."""
    import re

    hh = make_household()
    login(hh.username, hh.secret)
    r = client.get("/settings")
    form = re.search(r'<form[^>]*action="/app/auth/link"[^>]*>', r.text).group(0)
    assert 'hx-boost="false"' in form
    csp = r.headers["content-security-policy"]
    assert "form-action 'self' https://id.example.test;" in csp + ";"
    monkeypatch.setattr(settings, "new_app_enabled", False)
    csp = client.get("/settings").headers["content-security-policy"]
    assert csp.endswith("form-action 'self'")


@pytest.mark.parametrize(
    ("issuer", "origin"),
    [
        ("https://id.example.test", "https://id.example.test"),
        ("https://id.example.test:8443/x?y=1#z", "https://id.example.test:8443"),
        ("http://localhost:1411/", "http://localhost:1411"),
        ("https://user:pw@id.example.test/", "https://id.example.test"),
        ("https://[::1]:8443", "https://[::1]:8443"),
        ("https://a.com; script-src *", None),
        ("https://a.com/x;script-src", None),
        ("https://a.com'", None),
        ("id.example.test", None),
        ("//id.example.test", None),
        ("javascript://id.example.test", None),
        ("https://exa_mple.test", None),
        ("https://id.example.test:99999", None),
        ("", None),
        (None, None),
    ],
)
def test_issuer_origin_is_a_clean_origin_or_none(issuer, origin):
    from app.core.config import issuer_origin

    assert issuer_origin(issuer) == origin


def test_link_form_action_uses_only_the_issuer_origin(client, make_household, login, monkeypatch):
    hh = make_household()
    login(hh.username, hh.secret)
    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example.test:8443/x")
    csp = client.get("/settings").headers["content-security-policy"]
    assert csp.endswith("form-action 'self' https://id.example.test:8443")
    monkeypatch.setattr(settings, "oidc_issuer", "https://a.com; script-src *")
    csp = client.get("/settings").headers["content-security-policy"]
    assert csp.endswith("form-action 'self'") and "script-src *" not in csp


@pytest.mark.parametrize("issuer", ["https://a.com; script-src *", "id.example.test"])
def test_production_refuses_a_malformed_issuer(issuer):
    from app.core.config import Settings

    base = dict(
        _env_file=None,
        debug=False,
        app_secret_key="x" * 40,
        app_base_url="https://a.example",
        new_app_enabled=True,
        oidc_client_id="cid",
        oidc_client_secret="secret",
    )
    with pytest.raises(RuntimeError, match="OIDC_ISSUER"):
        Settings(**base, oidc_issuer=issuer)
    assert Settings(**base, oidc_issuer="https://id.example.test").oidc_issuer_origin


# --- final-review fixes ------------------------------------------------------


def _set_cookies(target, response):
    for raw in response.headers.getlist("set-cookie"):
        name, _, rest = raw.partition("=")
        target.cookies.set(name, rest.split(";")[0])


def test_pre_passkey_cookie_without_amr_can_start_a_link(client, db, make_household, login):
    """Cookies issued before this deploy carry no "amr"; they were all password+2FA."""
    from fastapi.responses import Response

    from app.auth import COOKIE_NAME, _cookie_kwargs, _serializer

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    legacy = _serializer.dumps(
        {
            "user_id": user.id,
            "hh_id": hh.household_id,
            "sv": user.session_version,
            "state": "authenticated",
        }
    )
    carrier = Response()
    carrier.set_cookie(COOKIE_NAME, legacy, **_cookie_kwargs(3600))
    _set_cookies(client, carrier)
    fake = _redirecting_client()
    r = _start_link(client, hh, headers, fake)
    assert r.headers["location"].startswith("https://id.example.test/")
    fake.authorize_redirect.assert_called_once()


def test_link_wrong_totp_alerts_the_household(client, db, make_household, login):
    from app.models import Notification

    hh = make_household()
    headers = login(hh.username, hh.secret)
    _start_link(client, hh, headers, _redirecting_client(), code="000000")
    db.expire_all()
    titles = [n.title for n in db.query(Notification).filter_by(user_id=hh.user_id)]
    assert f"Wrong 2FA code for {hh.username.title()}" in titles


def test_link_wrong_password_sends_no_second_factor_alert(client, db, make_household, login):
    from app.models import Notification

    hh = make_household()
    headers = login(hh.username, hh.secret)
    _start_link(client, hh, headers, _redirecting_client(), password="nope")
    db.expire_all()
    assert not any(
        n.title.startswith("Wrong 2FA")
        for n in db.query(Notification).filter_by(user_id=hh.user_id)
    )


@pytest.mark.parametrize(
    "exc",
    ["connect", "status", "oauth", "bad_json"],
)
def test_login_provider_discovery_failure_is_handled(client, exc):
    import httpx
    from authlib.integrations.base_client.errors import OAuthError

    errors = {
        "connect": httpx.ConnectError("down"),
        "status": httpx.HTTPStatusError(
            "500", request=httpx.Request("GET", "https://x"), response=httpx.Response(500)
        ),
        "oauth": OAuthError("bad"),
        "bad_json": ValueError("Expecting value"),
    }
    fake = AsyncMock()
    fake.authorize_redirect.side_effect = errors[exc]
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/login", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app/?auth_error=provider"


def test_link_start_provider_failure_returns_to_settings(client, db, make_household, login):
    import httpx

    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub"})
    fake.authorize_redirect.side_effect = httpx.ConnectError("down")
    r = _start_link(client, hh, headers, fake)
    assert r.headers["location"] == "/settings?passkey_error=1"
    # The half-started link must not turn a later callback in this browser into a link.
    fake.authorize_redirect.side_effect = None
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=not_linked"
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject is None


def test_owner_totp_reset_unlinks_the_members_passkey(client, db, make_household, login):
    import time

    import pyotp

    from tests.test_household_settlement import _add_member

    hh = make_household()
    headers = login(hh.username, hh.secret)
    bob = _add_member(db, hh.household_id, "bob")
    bob.oidc_subject = "bob-sub"
    db.commit()
    r = client.post(
        f"/settings/2fa/reset/{bob.id}",
        headers=headers,
        data={"owner_code": pyotp.TOTP(hh.secret).at(time.time() + 30)},
    )
    assert r.status_code == 302, r.text
    db.expire_all()
    assert db.get(User, bob.id).oidc_subject is None


def test_html_password_change_unlinks_the_passkey(client, db, make_household, login):
    from tests.conftest import PASSWORD

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    r = client.post(
        "/settings/profile/password",
        headers=headers,
        data={"current_password": PASSWORD, "new_password": "another-long-password"},
    )
    assert r.headers["location"] == "/settings?pw_changed=1"
    db.expire_all()
    assert db.get(User, hh.user_id).oidc_subject is None


def test_api_password_change_unlinks_the_passkey(client, db, make_household, login):
    from tests.conftest import PASSWORD

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    r = client.post(
        "/api/v1/settings/profile/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "another-long-password"},
    )
    assert r.status_code == 204, r.text
    db.expire_all()
    assert db.get(User, hh.user_id).oidc_subject is None


def test_settings_unlink_form_is_a_real_navigation(client, db, make_household, login):
    import re

    hh = make_household()
    login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    page = client.get("/settings").text
    form = re.search(r'<form[^>]*action="/app/auth/unlink"[^>]*>', page).group(0)
    assert 'hx-boost="false"' in form
    assert "Sign in with your password to unlink" not in page


def test_settings_hides_unlink_from_a_passkey_session(client, db):
    _member(db)
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    page = client.get("/settings").text
    assert "Passkey linked" in page
    assert "/app/auth/unlink" not in page
    assert "Sign in with your password to unlink" in page


def test_relinking_the_same_passkey_sends_no_second_alert(client, db, make_household, login):
    from app.models import Notification

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "same-sub"
    db.commit()
    fake = _redirecting_client({"sub": "same-sub"})
    _start_link(client, hh, headers, fake)
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?linked=1"
    db.expire_all()
    assert not any(
        n.title.startswith("Passkey linked")
        for n in db.query(Notification).filter_by(user_id=hh.user_id)
    )


@pytest.mark.parametrize("kind", ["bad_json", "status", "no_endpoint"])
def test_callback_provider_garbage_is_handled(client, kind):
    import httpx

    errors = {
        "bad_json": ValueError("Expecting value: line 1 column 1 (char 0)"),
        "status": httpx.HTTPStatusError(
            "502", request=httpx.Request("POST", "https://x/token"), response=httpx.Response(502)
        ),
        "no_endpoint": RuntimeError('Missing "token_endpoint" value'),
    }
    fake = _fake_client(exc=errors[kind])
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=provider"
    assert client.get("/api/v1/auth/me").status_code == 401

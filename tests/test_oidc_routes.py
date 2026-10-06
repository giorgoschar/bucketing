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
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"


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

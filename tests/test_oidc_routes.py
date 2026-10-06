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


def test_link_flow_links_subject_and_keeps_session(client, db, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub", "email": "whatever@x.t"})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/link", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert r.headers["location"].startswith("https://id.example.test/")
        assert "oidc_tx" in client.cookies
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?linked=1"
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject == "new-sub"
    assert client.get("/api/v1/auth/me").json()["id"] == hh.user_id


def test_link_conflict_reports_subject_conflict(client, db, make_household, login):
    db.add(
        User(username="o", email="o@x.t", display_name="O", password_hash="x", oidc_subject="taken")
    )
    db.commit()
    hh = make_household()
    login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "taken"})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/link", follow_redirects=False)
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=subject_conflict"


def test_link_without_session_requires_login(client):
    fake = _redirecting_client()
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/link", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    fake.authorize_redirect.assert_not_called()


def test_link_with_oidc_session_requires_login(client, db):
    _member(db)
    fake = _fake_client({"sub": "s1"})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    fake = _redirecting_client()
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/link", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    fake.authorize_redirect.assert_not_called()


def test_link_for_user_without_totp_requires_login(client, db, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.totp_enabled = False
    db.commit()
    fake = _redirecting_client()
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/link", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    fake.authorize_redirect.assert_not_called()


def test_link_callback_after_logout_requires_login(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub"})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/link", follow_redirects=False)
        client.post("/app/auth/logout", headers=headers)
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=link_requires_login"
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.oidc_subject is None


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

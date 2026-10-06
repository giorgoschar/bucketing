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


def _member(db, email="g@x.t"):
    u = User(username="g", email=email, display_name="G", password_hash="x")
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


def test_callback_unknown_user_gets_error_and_no_session(client, db):
    fake = _fake_client({"sub": "s1", "email": "nobody@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=no_account"
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
    u = User(username="g", email="g@x.t", display_name="G", password_hash="x")
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

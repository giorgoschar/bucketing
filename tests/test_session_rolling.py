"""Quiet OIDC sign-in (prompt only after an explicit sign-out) and the rolling session."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from starlette.responses import RedirectResponse

from app.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    SIGNED_OUT_COOKIE_NAME,
    _csrf_serializer,
    _serializer,
)
from app.core.config import settings
from app.models import Household, HouseholdMember, User

DAY = 86400


@pytest.fixture(autouse=True)
def _oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "new_app_enabled", True)
    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example.test")
    monkeypatch.setattr(settings, "oidc_client_id", "cid")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")


def _member(db, sub="s1"):
    h = Household(name="H", default_currency="EUR")
    u = User(username="g", email="g@x.t", display_name="G", password_hash="x", oidc_subject=sub)
    db.add_all([h, u])
    db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=u.id, role="owner"))
    db.commit()
    return u, h


def _redirecting():
    c = AsyncMock()
    c.authorize_redirect.return_value = RedirectResponse("https://id.example.test/authorize")
    c.authorize_access_token.return_value = {
        "userinfo": {"sub": "s1", "email": "g@x.t", "email_verified": True}
    }
    return c


def _oidc_login(client, fake):
    with patch("app.web_app.oidc_client", return_value=fake):
        return client.get("/app/auth/login", follow_redirects=False)


def _callback(client, fake):
    with patch("app.web_app.oidc_client", return_value=fake):
        return client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)


def test_login_sends_no_prompt_by_default(client):
    fake = _redirecting()
    _oidc_login(client, fake)
    assert "prompt" not in fake.authorize_redirect.call_args.kwargs


def test_logout_marker_forces_prompt_then_callback_clears_it(client, db):
    _member(db)
    fake = _redirecting()
    _callback(client, fake)
    r = client.post("/app/auth/logout", headers={"X-CSRF-Token": client.cookies.get("csrf_token")})
    assert r.status_code == 204
    marker = r.headers["set-cookie"]
    assert f"{SIGNED_OUT_COOKIE_NAME}=1" in marker
    assert client.cookies.get(SIGNED_OUT_COOKIE_NAME) == "1"

    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"

    r = _callback(client, fake)
    assert r.headers["location"] == "/app/"
    assert client.cookies.get(SIGNED_OUT_COOKIE_NAME) is None
    _oidc_login(client, fake)
    assert "prompt" not in fake.authorize_redirect.call_args.kwargs


def test_legacy_logout_sets_marker(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = client.post("/logout", headers=headers)
    assert r.status_code == 302
    assert client.cookies.get(SIGNED_OUT_COOKIE_NAME) == "1"
    fake = _redirecting()
    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_link_flow_still_prompts_login(client, make_household, login):
    from tests.test_oidc_routes import _link_form

    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting()
    with patch("app.web_app.oidc_client", return_value=fake):
        client.post("/app/auth/link", data=_link_form(hh), headers=headers, follow_redirects=False)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


# --- rolling session --------------------------------------------------------


@pytest.fixture()
def clock(monkeypatch):
    """Shift time.time() forward (itsdangerous and the app both read it)."""
    real = time.time
    state = {"offset": 0}
    monkeypatch.setattr(time, "time", lambda: real() + state["offset"])
    return state


def _session_cookie_value(client):
    return client.cookies.get(COOKIE_NAME)


def _set_cookie_names(r):
    return [h.split("=", 1)[0] for h in r.headers.get_list("set-cookie")]


def _signed_in(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    return hh, headers


def test_old_cookie_is_reissued_with_identical_payload(client, make_household, login, clock):
    hh, _ = _signed_in(client, make_household, login)
    before = _session_cookie_value(client)
    payload_before = _serializer.loads(before)
    clock["offset"] = 2 * DAY
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert COOKIE_NAME in _set_cookie_names(r)
    after = _session_cookie_value(client)
    assert after != before
    payload_after, signed_at = _serializer.loads(after, return_timestamp=True)
    assert payload_after == payload_before
    assert time.time() - signed_at.timestamp() < 60


def test_missing_amr_stays_missing(client, make_household, login, clock):
    hh, _ = _signed_in(client, make_household, login)
    legacy = _serializer.dumps(
        {"user_id": hh.user_id, "hh_id": hh.household_id, "sv": 0, "state": "authenticated"}
    )
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, legacy)
    clock["offset"] = 2 * DAY
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert "amr" not in _serializer.loads(_session_cookie_value(client))


def test_legacy_html_route_also_rolls(client, make_household, login, clock):
    _signed_in(client, make_household, login)
    clock["offset"] = 2 * DAY
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert COOKIE_NAME in _set_cookie_names(r)


def test_fresh_cookie_is_not_reissued(client, make_household, login, clock):
    _signed_in(client, make_household, login)
    clock["offset"] = 3600
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert COOKIE_NAME not in _set_cookie_names(r)


def test_expired_cookie_is_not_resurrected(client, make_household, login, clock):
    _signed_in(client, make_household, login)
    clock["offset"] = settings.session_max_age_seconds + DAY
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert not any(
        h.startswith(f"{COOKIE_NAME}=") and "Max-Age=0" not in h
        for h in r.headers.get_list("set-cookie")
    )


def test_stale_sv_is_not_reissued(client, make_household, login, db, clock):
    hh, _ = _signed_in(client, make_household, login)
    user = db.get(User, hh.user_id)
    user.session_version += 1
    db.commit()
    clock["offset"] = 2 * DAY
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert not any(
        h.startswith(f"{COOKIE_NAME}=") and "Max-Age=0" not in h
        for h in r.headers.get_list("set-cookie")
    )


def test_pending_cookie_untouched(client, clock):
    from starlette.responses import Response

    from app.auth import PENDING_COOKIE_NAME, set_pending_session

    resp = Response()
    set_pending_session(resp, "u", "h", "2fa_pending")
    client.cookies.set(
        PENDING_COOKIE_NAME, resp.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    )
    clock["offset"] = 100
    r = client.get("/api/v1/auth/me")
    assert PENDING_COOKIE_NAME not in _set_cookie_names(r)
    assert COOKIE_NAME not in _set_cookie_names(r)


def test_csrf_still_valid_for_active_user_past_original_30_days(
    client, make_household, login, clock
):
    hh, _ = _signed_in(client, make_household, login)
    original_csrf = client.cookies.get(CSRF_COOKIE_NAME)
    for day in range(1, 36):
        clock["offset"] = day * DAY
        assert client.get("/api/v1/auth/me").status_code == 200
    # Original sign-in is 35 days old: both cookies were rolled.
    assert client.cookies.get(CSRF_COOKIE_NAME) != original_csrf
    token = client.cookies.get(CSRF_COOKIE_NAME)
    _csrf_serializer.loads(token, max_age=settings.session_max_age_seconds)
    r = client.post("/api/v1/buckets/nope/archive", headers={"X-CSRF-Token": token})
    assert r.status_code in (404, 422), r.text


def test_young_csrf_token_is_kept(client, make_household, login, clock):
    """A form open in another tab keeps its token: the CSRF cookie is not replaced early."""
    _signed_in(client, make_household, login)
    token = client.cookies.get(CSRF_COOKIE_NAME)
    clock["offset"] = 3 * DAY
    client.get("/api/v1/auth/me")
    assert client.cookies.get(CSRF_COOKIE_NAME) == token

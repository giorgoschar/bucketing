"""Quiet OIDC sign-in (trusted-device cookie) and the rolling session."""

import time
from unittest.mock import AsyncMock, patch

import pytest
from starlette.responses import RedirectResponse

from app.auth import (
    COOKIE_NAME,
    CSRF_COOKIE_NAME,
    DEVICE_COOKIE_NAME,
    _csrf_serializer,
    _device_serializer,
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
        r = client.get("/app/auth/login", follow_redirects=False)
    fake.last_state = fake.authorize_redirect.call_args.kwargs["state"]
    return r


def _callback(client, fake):
    with patch("app.web_app.oidc_client", return_value=fake):
        return client.get(
            f"/app/auth/callback?code=c&state={fake.last_state}", follow_redirects=False
        )


def _sign_in(client, fake):
    """Full OIDC round trip through login then callback."""
    _oidc_login(client, fake)
    return _callback(client, fake)


def _drop_session(client):
    for name in (COOKIE_NAME, CSRF_COOKIE_NAME):
        client.cookies.delete(name)


def test_login_without_device_cookie_prompts(client):
    fake = _redirecting()
    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_callback_sets_device_cookie_and_next_login_is_quiet(client, db):
    _member(db)
    fake = _redirecting()
    r = _sign_in(client, fake)
    assert r.headers["location"] == "/app/"
    assert client.cookies.get(DEVICE_COOKIE_NAME)
    _drop_session(client)
    _oidc_login(client, fake)
    assert "prompt" not in fake.authorize_redirect.call_args.kwargs
    r = _callback(client, fake)
    assert r.headers["location"] == "/app/"
    assert client.get("/api/v1/auth/me").status_code == 200


def test_stale_sv_in_device_cookie_is_refused_at_callback(client, db):
    u, _ = _member(db)
    fake = _redirecting()
    _sign_in(client, fake)
    u.session_version += 1  # e.g. sign-out everywhere from another device
    db.commit()
    _drop_session(client)
    _oidc_login(client, fake)
    assert "prompt" not in fake.authorize_redirect.call_args.kwargs
    r = _callback(client, fake)
    assert r.headers["location"] == "/app/auth/login"
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.cookies.get(DEVICE_COOKIE_NAME) is None
    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_device_cookie_of_another_user_is_refused(client, db):
    u, _ = _member(db)
    fake = _redirecting()
    client.cookies.set(
        DEVICE_COOKIE_NAME, _device_serializer.dumps({"user_id": "someone-else", "sv": 0})
    )
    _oidc_login(client, fake)
    assert "prompt" not in fake.authorize_redirect.call_args.kwargs
    r = _callback(client, fake)
    assert r.headers["location"] == "/app/auth/login"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_tampered_device_cookie_counts_as_absent(client, db):
    u, _ = _member(db)
    good = _device_serializer.dumps({"user_id": u.id, "sv": u.session_version})
    client.cookies.set(DEVICE_COOKIE_NAME, good[:-2] + ("AA" if good[-2:] != "AA" else "BB"))
    fake = _redirecting()
    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_prompted_flow_does_not_need_device_cookie(client, db):
    _member(db)
    fake = _redirecting()
    _oidc_login(client, fake)  # no cookie -> prompted
    assert _callback(client, fake).headers["location"] == "/app/"


def test_failed_callback_sets_no_device_cookie(client, db):
    from authlib.integrations.base_client import OAuthError

    _member(db)
    fake = _redirecting()
    fake.authorize_access_token.side_effect = OAuthError("bad")
    r = _sign_in(client, fake)
    assert "auth_error" in r.headers["location"]
    assert client.cookies.get(DEVICE_COOKIE_NAME) is None
    assert client.cookies.get(COOKIE_NAME) is None


def test_app_logout_revokes_server_side_and_next_login_prompts(client, db):
    u, _ = _member(db)
    fake = _redirecting()
    _sign_in(client, fake)
    old_session = client.cookies.get(COOKIE_NAME)
    r = client.post("/app/auth/logout", headers={"X-CSRF-Token": client.cookies.get("csrf_token")})
    assert r.status_code == 204
    assert client.cookies.get(DEVICE_COOKIE_NAME) is None
    db.refresh(u)
    assert u.session_version == 1
    client.cookies.set(COOKIE_NAME, old_session)  # a copied cookie is dead now
    assert client.get("/api/v1/auth/me").status_code == 401
    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_legacy_logout_deletes_device_cookie(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    assert client.cookies.get(DEVICE_COOKIE_NAME)  # password+2FA sign-in trusts the device too
    r = client.post("/logout", headers=headers)
    assert r.status_code == 302
    assert client.cookies.get(DEVICE_COOKIE_NAME) is None
    fake = _redirecting()
    _oidc_login(client, fake)
    assert fake.authorize_redirect.call_args.kwargs["prompt"] == "login"


def test_link_flow_still_prompts_login(client, db, make_household, login):
    from tests.test_oidc_routes import _link_form

    hh = make_household()
    headers = login(hh.username, hh.secret)  # trusted device, yet link always prompts
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
    clock["offset"] = 2 * DAY
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


def _hidden_csrf_values(html):
    import re

    return re.findall(r'name="_csrf_token" value="([^"]*)"', html)


def test_rendered_forms_carry_the_replaced_csrf_token(client, make_household, login, clock):
    """The CSRF cookie is replaced on the rolling request itself, before the page
    renders, so a non-boosted form posted next still passes CSRF (no logout)."""
    _signed_in(client, make_household, login)
    old = client.cookies.get(CSRF_COOKIE_NAME)
    clock["offset"] = 25 * DAY  # > 24 days old, still inside the 30-day life
    r = client.get("/settings")
    assert r.status_code == 200
    new = client.cookies.get(CSRF_COOKIE_NAME)
    assert new != old
    tokens = _hidden_csrf_values(r.text)
    assert tokens and set(tokens) == {new}
    r = client.post("/app/auth/unlink", data={"_csrf_token": new})
    assert "expired" not in r.headers.get("location", "")


def test_iat_is_stamped_and_preserved(client, make_household, login, clock):
    _signed_in(client, make_household, login)
    iat = _serializer.loads(_session_cookie_value(client))["iat"]
    clock["offset"] = 2 * DAY
    client.get("/api/v1/auth/me")
    assert _serializer.loads(_session_cookie_value(client))["iat"] == iat


def test_cookie_past_absolute_cap_is_not_rolled(client, make_household, login, clock):
    hh, _ = _signed_in(client, make_household, login)
    payload = _serializer.loads(_session_cookie_value(client))
    clock["offset"] = 2 * DAY
    payload["iat"] = int(time.time()) - 91 * DAY  # original sign-in 91 days ago
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, _serializer.dumps(payload))
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401  # rejected outright, never rolled
    assert COOKIE_NAME not in _set_cookie_names(r)


def test_cookie_without_iat_is_not_rolled(client, make_household, login, clock):
    hh, _ = _signed_in(client, make_household, login)
    payload = _serializer.loads(_session_cookie_value(client))
    del payload["iat"]
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, _serializer.dumps(payload))
    clock["offset"] = 2 * DAY
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert COOKIE_NAME not in _set_cookie_names(r)


def test_bearer_request_gets_no_session_or_csrf_cookie(client, make_household, login, clock):
    from app.api_auth import create_access_token

    hh, _ = _signed_in(client, make_household, login)
    token = create_access_token(hh.user_id, hh.household_id, 0)
    clock["offset"] = 25 * DAY
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert COOKIE_NAME not in _set_cookie_names(r)
    assert CSRF_COOKIE_NAME not in _set_cookie_names(r)


def test_household_switch_after_a_day_is_not_overwritten_by_roll(
    client, db, make_household, login, clock
):
    hh, headers = _signed_in(client, make_household, login)
    other = Household(name="Second", default_currency="EUR")
    db.add(other)
    db.flush()
    db.add(HouseholdMember(household_id=other.id, user_id=hh.user_id, role="member"))
    db.commit()
    clock["offset"] = 2 * DAY
    r = client.post("/household/switch", data={"household_id": other.id}, headers=headers)
    assert r.status_code == 302
    assert _set_cookie_names(r).count(COOKIE_NAME) == 1
    assert _serializer.loads(_session_cookie_value(client))["hh_id"] == other.id


def test_unlink_after_a_day_keeps_the_reissued_session(client, db, make_household, login, clock):
    hh, headers = _signed_in(client, make_household, login)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "sub-x"
    db.commit()
    clock["offset"] = 2 * DAY
    r = client.post("/app/auth/unlink", headers=headers)
    assert r.status_code == 302
    assert _set_cookie_names(r).count(COOKIE_NAME) == 1
    db.refresh(user)
    assert _serializer.loads(_session_cookie_value(client))["sv"] == user.session_version
    assert client.get("/api/v1/auth/me").status_code == 200


# --- real Authlib state storage ---------------------------------------------


class _RealStateClient:
    """Real Authlib app for authorize_redirect and state storage; only the token
    exchange is faked (it still validates and consumes the state like Authlib does)."""

    def __init__(self, sub="s1"):
        from authlib.integrations.starlette_client import OAuth

        oauth = OAuth()
        oauth.register(
            name="pocketid",
            client_id="cid",
            client_secret="secret",
            authorize_url="https://id.example.test/authorize",
            access_token_url="https://id.example.test/token",
            client_kwargs={"scope": "openid email profile"},
        )
        self.app = oauth.pocketid
        self.sub = sub

    async def authorize_redirect(self, request, redirect_uri=None, **kwargs):
        return await self.app.authorize_redirect(request, redirect_uri, **kwargs)

    async def authorize_access_token(self, request):
        from authlib.integrations.base_client import OAuthError

        state = request.query_params.get("state")
        data = await self.app.framework.get_state_data(request.session, state)
        if not data:
            raise OAuthError(error="mismatching_state")
        await self.app.framework.clear_state_data(request.session, state)
        return {"userinfo": {"sub": self.sub, "email": "g@x.t", "email_verified": True}}


def _start(client, fake, path="/app/auth/login"):
    from urllib.parse import parse_qs, urlparse

    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get(path, follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    return r, q["state"][0], q.get("prompt", [None])[0]


def _finish(client, fake, state, extra=""):
    with patch("app.web_app.oidc_client", return_value=fake):
        return client.get(f"/app/auth/callback?code=c&state={state}{extra}", follow_redirects=False)


def test_real_state_prompted_sign_in(client, db):
    _member(db)
    fake = _RealStateClient()
    r, state, prompt = _start(client, fake)
    assert prompt == "login" and len(state) >= 40  # our own state reached Authlib
    assert _finish(client, fake, state).headers["location"] == "/app/"
    assert client.get("/api/v1/auth/me").status_code == 200


def test_real_state_quiet_sign_in_with_valid_device(client, db):
    _member(db)
    fake = _RealStateClient()
    _, state, _ = _start(client, fake)
    _finish(client, fake, state)
    _drop_session(client)
    _, state, prompt = _start(client, fake)
    assert prompt is None
    assert _finish(client, fake, state).headers["location"] == "/app/"
    assert client.get("/api/v1/auth/me").status_code == 200


def _stale_device_browser(client, db):
    """A browser whose trusted-device cookie went stale (sign-out everywhere elsewhere)."""
    u, _ = _member(db)
    fake = _RealStateClient()
    _, state, _ = _start(client, fake)
    _finish(client, fake, state)
    u.session_version += 1
    db.commit()
    _drop_session(client)
    return u, fake


def test_error_callback_then_replay_of_quiet_state_is_refused(client, db):
    """(a) The flag must not vanish with an error callback and let the replay skip the device check."""
    _stale_device_browser(client, db)
    fake = _RealStateClient()
    _, s1, prompt = _start(client, fake)
    assert prompt is None
    assert "auth_error" in _finish(client, fake, s1, "&error=x").headers["location"]
    r = _finish(client, fake, s1)
    assert "auth_error" in r.headers["location"]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_prompted_login_does_not_upgrade_an_earlier_quiet_state(client, db):
    """(b) A later prompted transaction must not make an earlier quiet one count as prompted."""
    _stale_device_browser(client, db)
    fake = _RealStateClient()
    _, s1, prompt1 = _start(client, fake)
    assert prompt1 is None
    stale_cookie = client.cookies.get(DEVICE_COOKIE_NAME)
    client.cookies.delete(DEVICE_COOKIE_NAME)
    _, s2, prompt2 = _start(client, fake)
    assert prompt2 == "login"
    client.cookies.set(DEVICE_COOKIE_NAME, stale_cookie)
    r = _finish(client, fake, s1)
    assert "auth_error" in r.headers["location"]
    assert client.get("/api/v1/auth/me").status_code == 401


def test_link_does_not_complete_an_earlier_quiet_state(client, db, make_household, login):
    """(c) Replaying a quiet state after /link must not link a passkey."""
    from tests.test_oidc_routes import _link_form

    hh = make_household()
    headers = login(hh.username, hh.secret)  # password session + trusted device
    fake = _RealStateClient(sub="attacker-sub")
    _, s1, prompt = _start(client, fake)
    assert prompt is None
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.post(
            "/app/auth/link", data=_link_form(hh), headers=headers, follow_redirects=False
        )
    assert r.status_code in (302, 307)
    r = _finish(client, fake, s1)
    assert "auth_error" in r.headers["location"]
    db.expire_all()
    assert db.get(User, hh.user_id).oidc_subject is None


def test_real_state_link_flow_links(client, db, make_household, login):
    from urllib.parse import parse_qs, urlparse

    from tests.test_oidc_routes import _link_form

    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _RealStateClient(sub="new-sub")
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.post(
            "/app/auth/link", data=_link_form(hh), headers=headers, follow_redirects=False
        )
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["prompt"] == ["login"]
    r = _finish(client, fake, q["state"][0])
    assert r.headers["location"] == "/app/?linked=1"
    db.expire_all()
    assert db.get(User, hh.user_id).oidc_subject == "new-sub"


def test_callback_without_state_is_never_prompted(client, db):
    _stale_device_browser(client, db)
    fake = _RealStateClient()
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c", follow_redirects=False)
    assert "auth_error" in r.headers["location"]


# --- absolute lifetime ------------------------------------------------------


def _age_session(client, clock, days, step=7):
    """Use the app daily-ish so the cookie keeps rolling, up to `days` since sign-in."""
    d = 0
    while d + step < days:
        d += step
        clock["offset"] = d * DAY
        assert client.get("/api/v1/auth/me").status_code == 200
    clock["offset"] = days * DAY


def test_switch_at_day_89_keeps_original_iat_and_day_91_is_rejected(
    client, db, make_household, login, clock
):
    hh, headers = _signed_in(client, make_household, login)
    other = Household(name="Second", default_currency="EUR")
    db.add(other)
    db.flush()
    db.add(HouseholdMember(household_id=other.id, user_id=hh.user_id, role="member"))
    db.commit()
    iat = _serializer.loads(_session_cookie_value(client))["iat"]
    _age_session(client, clock, 89)
    headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
    r = client.post("/household/switch", data={"household_id": other.id}, headers=headers)
    assert r.status_code == 302
    after = _serializer.loads(_session_cookie_value(client))
    assert after["hh_id"] == other.id and after["iat"] == iat

    clock["offset"] = 91 * DAY
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.get("/dashboard")
    assert r.status_code == 302 and r.headers["location"].startswith("/login")


def test_switch_on_a_pre_iat_cookie_carries_its_signing_time(
    client, db, make_household, login, clock
):
    """A cookie from before iat existed cannot restart the 90-day cap by re-issue."""
    hh, _ = _signed_in(client, make_household, login)
    other = Household(name="Second", default_currency="EUR")
    db.add(other)
    db.flush()
    db.add(HouseholdMember(household_id=other.id, user_id=hh.user_id, role="member"))
    db.commit()
    payload = _serializer.loads(_session_cookie_value(client))
    del payload["iat"]
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, _serializer.dumps(payload))
    client.cookies.set(CSRF_COOKIE_NAME, csrf)
    signed_at = _serializer.loads(client.cookies.get(COOKIE_NAME), return_timestamp=True)[1]
    clock["offset"] = 20 * DAY
    r = client.post(
        "/household/switch", data={"household_id": other.id}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 302
    issued = next(
        h.split(";", 1)[0].split("=", 1)[1]
        for h in r.headers.get_list("set-cookie")
        if h.startswith(f"{COOKIE_NAME}=")
    )
    after = _serializer.loads(issued)
    assert after["hh_id"] == other.id
    assert after["iat"] == int(signed_at.timestamp())

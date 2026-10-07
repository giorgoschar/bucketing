from starlette.responses import Response

from app.auth import CSRF_COOKIE_NAME, set_session
from app.models import Household, HouseholdMember, User


def _member(db, totp=True):
    u = User(username="g", email="g@x.t", display_name="G", password_hash="x", totp_enabled=totp)
    h = Household(name="Home")
    db.add_all([u, h])
    db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=u.id, role="owner"))
    db.commit()
    return u, h


def _login(client, u, h, amr):
    r = Response()
    set_session(r, u.id, h.id, u.session_version, amr=amr)
    for raw in r.headers.getlist("set-cookie"):
        name, _, rest = raw.partition("=")
        client.cookies.set(name, rest.split(";")[0])
    return client.cookies.get(CSRF_COOKIE_NAME)


def test_cookie_get_works(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200 and r.json()["household_id"] == h.id


def test_no_credentials_is_json_401_not_redirect(client):
    r = client.get("/api/v1/auth/me", follow_redirects=False)
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/json")


def test_cookie_post_without_csrf_is_403_and_session_survives(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    r = client.post("/api/v1/notifications/read-all")
    assert r.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_cookie_post_with_csrf_header_passes_csrf(client, db):
    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    r = client.post("/api/v1/notifications/read-all", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200


def test_password_session_without_totp_is_403(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "pwd")
    assert client.get("/api/v1/auth/me").status_code == 403


def test_oidc_session_without_totp_is_allowed(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "oidc")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_stale_session_version_is_401(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    u.session_version += 1
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_removed_member_cookie_is_401(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    db.query(HouseholdMember).delete()
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_web_ui_oidc_session_without_totp_is_not_sent_to_enroll(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "oidc")
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 200


def test_household_switch_preserves_amr(client, db):
    u, h = _member(db, totp=False)
    h2 = Household(name="Other")
    db.add(h2)
    db.flush()
    db.add(HouseholdMember(household_id=h2.id, user_id=u.id, role="owner"))
    db.commit()
    csrf = _login(client, u, h, "oidc")
    r = client.post("/household/switch", data={"household_id": h2.id, "_csrf_token": csrf})
    assert r.status_code == 302
    assert client.get("/api/v1/auth/me").json()["household_id"] == h2.id


def test_non_ascii_csrf_header_is_403_not_500(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    r = client.post(
        "/api/v1/notifications/read-all", headers={"X-CSRF-Token": "é".encode("latin-1")}
    )
    assert r.status_code == 403


def test_change_password_keeps_oidc_session_type(client, db):
    from app.auth import hash_password

    u, h = _member(db, totp=False)
    u.password_hash = hash_password("old-password-123")
    db.commit()
    csrf = _login(client, u, h, "oidc")
    r = client.post(
        "/settings/profile/password",
        data={
            "current_password": "old-password-123",
            "new_password": "new-password-1234",
            "_csrf_token": csrf,
        },
    )
    assert r.status_code == 302
    client.cookies.set(CSRF_COOKIE_NAME, r.cookies.get(CSRF_COOKIE_NAME) or csrf)
    assert client.get("/dashboard").status_code == 200


def test_create_household_keeps_oidc_session_type(client, db):
    u, h = _member(db, totp=False)
    csrf = _login(client, u, h, "oidc")
    r = client.post("/settings/household/new", data={"name": "Second", "_csrf_token": csrf})
    assert r.status_code == 302
    assert client.get("/dashboard").status_code == 200


def test_me_response_shape(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    body = client.get("/api/v1/auth/me").json()
    assert set(body) == {"id", "username", "display_name", "email", "avatar_color", "household_id"}
    assert body["id"] == u.id and body["household_id"] == h.id


def test_expected_account_header_matching_passes(client, db):
    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    r = client.post(
        "/api/v1/notifications/read-all",
        headers={"X-CSRF-Token": csrf, "X-Expected-Account": f"{u.id}:{h.id}"},
    )
    assert r.status_code == 200


def test_expected_account_header_mismatch_is_412_and_writes_nothing(client, db):
    from app.models import Notification, NotificationType

    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    db.add(
        Notification(
            household_id=h.id, user_id=u.id, type=NotificationType.general, title="t", is_read=False
        )
    )
    db.commit()
    for expected in (f"someone-else:{h.id}", f"{u.id}:other-household", ""):
        r = client.post(
            "/api/v1/notifications/read-all",
            headers={"X-CSRF-Token": csrf, "X-Expected-Account": expected},
        )
        assert r.status_code == 412
        assert r.json()["detail"] == "Signed in as a different account"
    db.expire_all()
    assert db.query(Notification).filter_by(user_id=u.id).one().is_read is False


def test_no_expected_account_header_is_unchanged(client, db):
    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    r = client.post("/api/v1/notifications/read-all", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200


# --- cross-origin requests never ride on the cookie ------------------------


def test_same_origin_post_with_origin_header_works(client, db):
    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    r = client.post(
        "/api/v1/notifications/read-all",
        headers={"X-CSRF-Token": csrf, "Origin": "http://testserver"},
    )
    assert r.status_code == 200


def test_get_without_origin_header_works(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_foreign_origin_cookie_request_is_401(client, db):
    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    r = client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Cross-origin cookie requests are not allowed"
    r = client.post(
        "/api/v1/notifications/read-all",
        headers={"X-CSRF-Token": csrf, "Origin": "null"},
    )
    assert r.status_code == 401


def test_origin_is_checked_against_app_base_url(client, db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_base_url", "https://expenses.example.com/")
    u, h = _member(db)
    _login(client, u, h, "pwd")
    ok = client.get("/api/v1/auth/me", headers={"Origin": "https://expenses.example.com"})
    assert ok.status_code == 200
    # The request's own host no longer counts once APP_BASE_URL is set.
    assert client.get("/api/v1/auth/me", headers={"Origin": "http://testserver"}).status_code == 401


def test_bearer_requests_ignore_origin(client, db):
    from app.api_auth import create_access_token

    u, h = _member(db)
    token = create_access_token(u.id, h.id, u.session_version)
    r = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}", "Origin": "capacitor://localhost"},
    )
    assert r.status_code == 200


def test_cookie_auth_reissues_a_missing_csrf_cookie(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    client.cookies.delete(CSRF_COOKIE_NAME)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert any(c.startswith(f"{CSRF_COOKIE_NAME}=") for c in r.headers.get_list("set-cookie"))


def test_rejected_cookie_gets_no_csrf_cookie(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "pwd")
    client.cookies.delete(CSRF_COOKIE_NAME)
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 403
    assert not any(c.startswith(f"{CSRF_COOKIE_NAME}=") for c in r.headers.get_list("set-cookie"))

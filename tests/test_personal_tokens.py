"""Personal ingest tokens (Phase 5): a long-lived, per-user, per-household
credential for the iOS Shortcut. Only its SHA-256 is stored; the plaintext is
shown exactly once."""

import hashlib
import re

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.models import BucketStatus, HouseholdMember, PersonalApiToken
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member

PAT_RE = re.compile(r"^pat_[A-Za-z0-9_-]{32}$")


def _ingest_auth(db, raw):
    from app.api_auth import require_ingest_token

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw)
    return require_ingest_token(credentials=creds, db=db)


def _create_api(client, headers, **body):
    body.setdefault("name", "iPhone")
    return client.post("/api/v1/settings/tokens", headers=headers, json=body)


# ---------------------------------------------------------------- service / auth


def test_issue_stores_only_the_hash(db, make_household):
    from app.services import issue_personal_token

    hh = make_household()
    record, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    assert PAT_RE.match(raw)
    assert record.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert record.prefix == raw[:12] and len(record.prefix) == 12
    assert record.scopes == "ingest"
    # The plaintext is nowhere in the row.
    row = db.get(PersonalApiToken, record.id)
    assert raw not in {str(getattr(row, c.name)) for c in PersonalApiToken.__table__.columns}


def test_ingest_auth_accepts_valid_token_and_records_use(db, make_household):
    from app.services import issue_personal_token

    hh = make_household()
    record, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    assert record.last_used_at is None
    token = _ingest_auth(db, raw)
    assert token.id == record.id
    db.refresh(record)
    assert record.last_used_at is not None


@pytest.mark.parametrize("raw", ["pat_" + "x" * 32, "nonsense", "pat_", ""])
def test_ingest_auth_rejects_unknown_tokens(db, raw):
    with pytest.raises(HTTPException) as exc:
        _ingest_auth(db, raw)
    assert exc.value.status_code == 401


def test_ingest_auth_rejects_missing_header(db):
    from app.api_auth import require_ingest_token

    with pytest.raises(HTTPException) as exc:
        require_ingest_token(credentials=None, db=db)
    assert exc.value.status_code == 401


def test_ingest_auth_rejects_jwt(api, db):  # noqa: F811
    headers, hh = api
    jwt_token = headers["Authorization"].split()[1]
    with pytest.raises(HTTPException) as exc:
        _ingest_auth(db, jwt_token)
    assert exc.value.status_code == 401


def test_ingest_auth_rejects_removed_member(db, make_household):
    from app.services import issue_personal_token

    hh = make_household()
    member = _add_member(db, hh.household_id, "bob")
    db.commit()
    _, raw = issue_personal_token(
        db, user_id=member.id, household_id=hh.household_id, name="Bob phone"
    )
    db.commit()
    assert _ingest_auth(db, raw)
    db.query(HouseholdMember).filter_by(user_id=member.id).delete()
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _ingest_auth(db, raw)
    assert exc.value.status_code == 401


def test_ingest_auth_requires_ingest_scope(db, make_household):
    from app.services import issue_personal_token

    hh = make_household()
    record, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="x"
    )
    record.scopes = "read"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        _ingest_auth(db, raw)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------- API management


def test_api_create_returns_plaintext_once_and_list_shows_prefix(client, api, db):  # noqa: F811
    headers, hh = api
    r = _create_api(client, headers, default_bucket_id=hh.bucket_id)
    assert r.status_code == 201, r.text
    body = r.json()
    raw = body["token"]
    assert PAT_RE.match(raw)
    assert body["prefix"] == raw[:12]
    assert body["default_bucket_id"] == hh.bucket_id

    r = client.get("/api/v1/settings/tokens", headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["prefix"] == raw[:12]
    assert items[0]["last_used_at"] is None
    assert raw not in r.text
    assert "token" not in items[0] and "token_hash" not in items[0]


def test_api_revoke_makes_token_unusable(client, api, db):  # noqa: F811
    headers, hh = api
    created = _create_api(client, headers).json()
    assert _ingest_auth(db, created["token"])

    r = client.delete(f"/api/v1/settings/tokens/{created['id']}", headers=headers)
    assert r.status_code == 204
    db.expire_all()
    with pytest.raises(HTTPException) as exc:
        _ingest_auth(db, created["token"])
    assert exc.value.status_code == 401
    # Revoked tokens are kept (audit) but marked, and drop off the list.
    assert db.get(PersonalApiToken, created["id"]).revoked_at is not None
    assert client.get("/api/v1/settings/tokens", headers=headers).json() == []


def test_api_cannot_revoke_someone_elses_token(client, api, db):  # noqa: F811
    from app.services import issue_personal_token

    headers, hh = api
    bob = _add_member(db, hh.household_id, "bob")
    db.commit()
    record, _ = issue_personal_token(db, user_id=bob.id, household_id=hh.household_id, name="Bob")
    db.commit()
    r = client.delete(f"/api/v1/settings/tokens/{record.id}", headers=headers)
    assert r.status_code == 404
    db.refresh(record)
    assert record.revoked_at is None
    # ...and the owner does not see Bob's token in their list.
    assert client.get("/api/v1/settings/tokens", headers=headers).json() == []


def test_api_rejects_foreign_or_archived_default_bucket(client, api, db, make_household):  # noqa: F811
    from app.models import Bucket

    headers, hh = api
    other = make_household(name="Other", username="other")
    assert _create_api(client, headers, default_bucket_id=other.bucket_id).status_code == 400

    bucket = db.get(Bucket, hh.bucket_id)
    bucket.status = BucketStatus.archived
    db.commit()
    assert _create_api(client, headers, default_bucket_id=hh.bucket_id).status_code == 400


def test_api_rejects_blank_name(client, api):  # noqa: F811
    headers, _ = api
    assert _create_api(client, headers, name="   ").status_code == 422


def test_pat_is_not_accepted_by_normal_api_routes(client, api, db):  # noqa: F811
    headers, _ = api
    raw = _create_api(client, headers).json()["token"]
    for path in ("/api/v1/buckets", "/api/v1/settings/tokens", "/api/v1/settings/profile"):
        r = client.get(path, headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 401, path


def test_api_token_endpoints_need_auth(client):
    assert client.get("/api/v1/settings/tokens").status_code == 401
    assert client.post("/api/v1/settings/tokens", json={"name": "x"}).status_code == 401


# ---------------------------------------------------------------- HTML settings page


def test_automations_page_renders(client, authed):
    r = client.get("/settings/automations")
    assert r.status_code == 200
    assert "Automations" in r.text


def test_html_create_shows_plaintext_once(client, db, authed):
    r = client.post(
        "/settings/automations/tokens",
        headers=authed.headers,
        data={"name": "My iPhone", "default_bucket_id": authed.bucket_id},
    )
    assert r.status_code == 200, r.text
    m = re.search(r"pat_[A-Za-z0-9_-]{32}", r.text)
    assert m, "plaintext token not shown after creation"
    raw = m.group(0)
    record = db.query(PersonalApiToken).one()
    assert record.user_id == authed.user_id
    assert record.default_bucket_id == authed.bucket_id

    again = client.get("/settings/automations")
    assert raw not in again.text
    assert record.prefix in again.text


def test_html_create_requires_csrf(client, authed):
    r = client.post("/settings/automations/tokens", data={"name": "x"})
    assert r.status_code in (400, 403)


def test_html_revoke(client, db, authed):
    from app.services import issue_personal_token

    record, raw = issue_personal_token(
        db, user_id=authed.user_id, household_id=authed.household_id, name="x"
    )
    db.commit()
    r = client.post(f"/settings/automations/tokens/{record.id}/revoke", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    with pytest.raises(HTTPException):
        _ingest_auth(db, raw)


def test_html_page_requires_login(client):
    r = client.get("/settings/automations")
    assert r.status_code in (302, 303, 401)


# ---------------------------------------------------------------- revocation on
# account-recovery steps (review fix). Rows are kept, only revoked_at is set.


def _ingest_status(client, raw, merchant="Shop"):
    return client.post(
        "/api/v1/ingest/apple-pay",
        json={"merchant": merchant, "amount": "1"},
        headers={"Authorization": f"Bearer {raw}"},
    ).status_code


def _day2day(db, bucket_id):
    from app.models import Bucket, BucketType

    db.get(Bucket, bucket_id).type = BucketType.day2day
    db.commit()


def _issue(db, user_id, household_id, name="iPhone"):
    from app.services import issue_personal_token

    record, raw = issue_personal_token(db, user_id=user_id, household_id=household_id, name=name)
    db.commit()
    return record, raw


def _next_totp(secret):
    import time

    import pyotp

    return pyotp.TOTP(secret).at(time.time() + 30)


def test_html_password_change_revokes_tokens(client, db, authed):
    from tests.conftest import PASSWORD

    _day2day(db, authed.bucket_id)
    record, raw = _issue(db, authed.user_id, authed.household_id)
    assert _ingest_status(client, raw) == 201
    r = client.post(
        "/settings/profile/password",
        headers=authed.headers,
        data={"current_password": PASSWORD, "new_password": "another-long-password"},
    )
    assert r.status_code == 302
    assert _ingest_status(client, raw, "Other") == 401
    db.expire_all()
    assert db.get(PersonalApiToken, record.id).revoked_at is not None


def test_api_password_change_revokes_tokens(client, api, db):  # noqa: F811
    from tests.conftest import PASSWORD

    headers, hh = api
    _, raw = _issue(db, hh.user_id, hh.household_id)
    r = client.post(
        "/api/v1/settings/profile/password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "another-long-password"},
    )
    assert r.status_code == 204, r.text
    assert _ingest_status(client, raw) == 401


def test_totp_disable_revokes_tokens(client, db, authed):
    from tests.conftest import PASSWORD

    _, raw = _issue(db, authed.user_id, authed.household_id)
    r = client.post(
        "/settings/2fa/disable",
        headers=authed.headers,
        data={"current_password": PASSWORD, "code": _next_totp(authed.secret)},
    )
    assert r.status_code == 302, r.text
    assert _ingest_status(client, raw) == 401


def test_owner_2fa_reset_revokes_member_tokens_only(client, db, authed):
    _day2day(db, authed.bucket_id)
    bob = _add_member(db, authed.household_id, "bob")
    db.commit()
    _, bob_raw = _issue(db, bob.id, authed.household_id, "Bob")
    _, owner_raw = _issue(db, authed.user_id, authed.household_id, "Owner")
    r = client.post(
        f"/settings/2fa/reset/{bob.id}",
        headers=authed.headers,
        data={"owner_code": _next_totp(authed.secret)},
    )
    assert r.status_code == 302, r.text
    assert _ingest_status(client, bob_raw) == 401
    assert _ingest_status(client, owner_raw) == 201


def test_removed_then_readded_member_token_stays_revoked(client, db, authed):
    from app.models import MemberRole

    _day2day(db, authed.bucket_id)
    bob = _add_member(db, authed.household_id, "bob")
    db.commit()
    record, raw = _issue(db, bob.id, authed.household_id, "Bob")
    assert _ingest_status(client, raw) == 201
    r = client.post(f"/settings/remove-member/{bob.id}", headers=authed.headers)
    assert r.status_code == 302
    db.add(
        HouseholdMember(household_id=authed.household_id, user_id=bob.id, role=MemberRole.member)
    )
    db.commit()
    assert _ingest_status(client, raw, "Again") == 401
    db.expire_all()
    assert db.get(PersonalApiToken, record.id).revoked_at is not None


def test_api_member_removal_revokes_tokens(client, api, db):  # noqa: F811
    headers, hh = api
    bob = _add_member(db, hh.household_id, "bob")
    db.commit()
    record, _ = _issue(db, bob.id, hh.household_id, "Bob")
    r = client.delete(f"/api/v1/settings/household/members/{bob.id}", headers=headers)
    assert r.status_code == 204, r.text
    db.expire_all()
    assert db.get(PersonalApiToken, record.id).revoked_at is not None


def test_leaving_household_revokes_tokens(client, db, authed):
    record, _ = _issue(db, authed.user_id, authed.household_id)
    r = client.post(
        "/settings/leave-household", headers=authed.headers, data={"confirm_name": "Test Household"}
    )
    assert r.status_code == 302, r.text
    db.expire_all()
    assert db.get(PersonalApiToken, record.id).revoked_at is not None


def test_plain_logout_keeps_tokens(client, db, authed):
    _day2day(db, authed.bucket_id)
    _, raw = _issue(db, authed.user_id, authed.household_id)
    assert client.post("/logout", headers=authed.headers).status_code == 302
    assert _ingest_status(client, raw) == 201


def test_api_create_response_is_not_cacheable(client, api):  # noqa: F811
    headers, _ = api
    r = _create_api(client, headers)
    assert r.status_code == 201
    assert r.headers.get("cache-control") == "no-store"


def test_failed_ingest_auth_is_ip_rate_limited(client, db, authed):
    _day2day(db, authed.bucket_id)
    _, raw = _issue(db, authed.user_id, authed.household_id)
    bad = "pat_" + "B" * 32
    for i in range(20):
        assert _ingest_status(client, bad) == 401, i
    assert _ingest_status(client, bad) == 429
    assert _ingest_status(client, "not-a-pat") == 429
    # Failures never lock out a valid token.
    assert _ingest_status(client, raw) == 201

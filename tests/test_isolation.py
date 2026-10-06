"""
Cross-household isolation.

Ids in this app are opaque UUIDs, but that is not an access control. Every
route that accepts an id from the client must scope it to the caller's
household.
"""

from datetime import date

from app.models import RecurringBill, Transaction, TransactionSplit


def _make_txn(client, headers, bucket_id, amount="10"):
    r = client.post(
        "/transactions",
        data={
            "bucket_id": bucket_id,
            "transaction_date": "2026-07-20",
            "amount": amount,
            "type": "expense",
        },
        headers=headers,
    )
    assert r.status_code == 302, r.text[:200]


def test_cannot_read_another_households_bucket(client, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    assert client.get(f"/buckets/{victim.bucket_id}").status_code == 404


def test_cannot_create_transaction_in_foreign_bucket(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post(
        "/transactions",
        data={
            "bucket_id": victim.bucket_id,
            "transaction_date": "2026-07-20",
            "amount": "99",
            "type": "expense",
        },
        headers=authed.headers,
    )
    assert r.status_code in (400, 403, 404)
    assert db.query(Transaction).filter_by(bucket_id=victim.bucket_id).count() == 0


def test_cannot_move_transaction_into_foreign_bucket(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    _make_txn(client, authed.headers, authed.bucket_id)
    txn = db.query(Transaction).one()

    r = client.post(
        f"/transactions/{txn.id}/edit",
        data={
            "bucket_id": victim.bucket_id,
            "transaction_date": "2026-07-20",
            "amount": "10",
            "type": "expense",
        },
        headers=authed.headers,
    )

    assert r.status_code in (400, 403, 404)
    db.expire_all()
    assert db.get(Transaction, txn.id).bucket_id == authed.bucket_id


def test_cannot_split_onto_a_non_member(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post(
        "/transactions",
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-07-20",
            "amount": "50",
            "type": "expense",
            "is_shared": "on",
            f"split_{victim.user_id}": "50",
        },
        headers=authed.headers,
    )

    assert r.status_code in (400, 403, 404)
    assert db.query(TransactionSplit).filter_by(user_id=victim.user_id).count() == 0


def test_cannot_attach_bill_to_foreign_bucket(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post(
        "/bills",
        data={
            "name": "Evil",
            "amount": "10",
            "start_date": "2026-01-01",
            "interval_months": "1",
            "frequency": "monthly",
            "bucket_id": victim.bucket_id,
        },
        headers=authed.headers,
    )

    assert r.status_code in (400, 403, 404)
    assert db.query(RecurringBill).filter_by(bucket_id=victim.bucket_id).count() == 0


def test_cannot_use_foreign_category(client, db, authed, make_household):
    from app.models import Category

    victim = make_household(name="Victim", username="victim")
    cat = Category(household_id=victim.household_id, name="Victim Cat")
    db.add(cat)
    db.commit()

    r = client.post(
        "/transactions",
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-07-20",
            "amount": "10",
            "type": "expense",
            "category_id": cat.id,
        },
        headers=authed.headers,
    )
    assert r.status_code in (400, 403, 404)


def test_cannot_set_foreign_user_as_payer(client, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post(
        "/transactions",
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-07-20",
            "amount": "10",
            "type": "expense",
            "paid_by": victim.user_id,
        },
        headers=authed.headers,
    )
    assert r.status_code in (400, 403, 404)


def test_cannot_edit_or_delete_foreign_bucket(client, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post(
        f"/buckets/{victim.bucket_id}/edit",
        data={"name": "Pwned", "type": "custom"},
        headers=authed.headers,
    )
    assert r.status_code == 404
    r = client.post(f"/buckets/{victim.bucket_id}/archive", headers=authed.headers)
    assert r.status_code == 404


def test_insights_only_reports_own_household(client, db, authed, make_household):
    """A victim's spending must never leak into the attacker's totals."""
    victim = make_household(name="Victim", username="victim")
    db.add(
        Transaction(
            bucket_id=victim.bucket_id,
            household_id=victim.household_id,
            amount=9999,
            currency="EUR",
            type="expense",
            transaction_date=date(2026, 7, 20),
        )
    )
    db.commit()

    _make_txn(client, authed.headers, authed.bucket_id, amount="10")
    r = client.get("/insights?preset=all_time")
    assert r.status_code == 200
    assert "9,999" not in r.text and "9999" not in r.text


def test_non_owner_cannot_rename_household(client, db, make_household, login):
    """The HTML route used to let any member change household settings."""
    import pyotp

    from app.auth import hash_password
    from app.models import Household, HouseholdMember, MemberRole, User
    from tests.conftest import PASSWORD

    owner = make_household(name="Shared", username="owner")
    secret = pyotp.random_base32()
    member = User(
        username="member",
        display_name="Member",
        email="member@example.com",
        password_hash=hash_password(PASSWORD),
        totp_secret=secret,
        totp_enabled=True,
        session_version=0,
    )
    db.add(member)
    db.flush()
    db.add(
        HouseholdMember(household_id=owner.household_id, user_id=member.id, role=MemberRole.member)
    )
    db.commit()

    headers = login("member", secret)
    r = client.post(
        "/settings/household", data={"name": "Hijacked", "default_currency": "EUR"}, headers=headers
    )

    assert r.status_code == 403
    db.expire_all()
    assert db.get(Household, owner.household_id).name == "Shared"


# ---------------------------------------------------------------------------
# C1/H2: a removed member's cached cookie or token must stop working.
# ---------------------------------------------------------------------------


def _add_member_user(db, household_id, username="member"):
    import pyotp

    from app.auth import hash_password
    from app.models import HouseholdMember, MemberRole, User
    from tests.conftest import PASSWORD

    secret = pyotp.random_base32()
    user = User(
        username=username,
        display_name=username.title(),
        email=f"{username}@example.com",
        password_hash=hash_password(PASSWORD),
        totp_secret=secret,
        totp_enabled=True,
        session_version=0,
    )
    db.add(user)
    db.flush()
    db.add(HouseholdMember(household_id=household_id, user_id=user.id, role=MemberRole.member))
    db.commit()
    return user, secret


def _web_login(app, username, secret):
    import pyotp
    from fastapi.testclient import TestClient

    from tests.conftest import PASSWORD, form_csrf

    c = TestClient(app, follow_redirects=False)
    assert (
        c.post(
            "/login", data={**form_csrf(c, "/login"), "username": username, "password": PASSWORD}
        ).status_code
        == 302
    )
    assert (
        c.post(
            "/login/verify",
            data={**form_csrf(c, "/login/verify"), "code": pyotp.TOTP(secret).now()},
        ).status_code
        == 302
    )
    return c


def _api_login(client, username, secret):
    import pyotp

    from tests.conftest import PASSWORD

    r = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _drop_membership(db, household_id, user_id):
    """Remove membership behind the app's back: no session_version bump."""
    from app.models import HouseholdMember

    db.query(HouseholdMember).filter_by(household_id=household_id, user_id=user_id).delete()
    db.commit()


def test_removed_member_cookie_is_rejected(app, db, make_household):
    owner = make_household(name="Shared", username="owner")
    member, secret = _add_member_user(db, owner.household_id)
    member_client = _web_login(app, "member", secret)
    assert member_client.get("/dashboard").status_code == 200

    owner_client = _web_login(app, "owner", owner.secret)
    r = owner_client.post(
        f"/settings/remove-member/{member.id}",
        headers={"X-CSRF-Token": owner_client.cookies.get("csrf_token")},
    )
    assert r.status_code == 302

    r = member_client.get("/dashboard")
    assert r.status_code == 302 and r.headers["location"] == "/login"


def test_session_without_membership_is_rejected(app, db, make_household):
    owner = make_household(name="Shared", username="owner")
    member, secret = _add_member_user(db, owner.household_id)
    member_client = _web_login(app, "member", secret)

    _drop_membership(db, owner.household_id, member.id)

    for path in ("/dashboard", "/settings", "/insights"):
        r = member_client.get(path)
        assert r.status_code == 302 and r.headers["location"] == "/login", path


def test_access_token_without_membership_is_401(client, db, make_household):
    owner = make_household(name="Shared", username="owner")
    member, secret = _add_member_user(db, owner.household_id)
    tokens = _api_login(client, "member", secret)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/api/v1/buckets", headers=headers).status_code == 200

    _drop_membership(db, owner.household_id, member.id)

    assert client.get("/api/v1/buckets", headers=headers).status_code == 401


def test_refresh_token_without_membership_is_401_and_revoked(client, db, make_household):
    from app.api_auth import _hash_token
    from app.models import RefreshToken

    owner = make_household(name="Shared", username="owner")
    member, secret = _add_member_user(db, owner.household_id)
    tokens = _api_login(client, "member", secret)

    _drop_membership(db, owner.household_id, member.id)

    r = client.post("/api/v1/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
    db.expire_all()
    record = db.query(RefreshToken).filter_by(token_hash=_hash_token(tokens["refresh_token"])).one()
    assert record.revoked


def test_api_removal_revokes_member_refresh_tokens(client, db, make_household):
    owner = make_household(name="Shared", username="owner")
    member, secret = _add_member_user(db, owner.household_id)
    member_tokens = _api_login(client, "member", secret)
    owner_tokens = _api_login(client, "owner", owner.secret)

    r = client.delete(
        f"/api/v1/settings/household/members/{member.id}",
        headers={"Authorization": f"Bearer {owner_tokens['access_token']}"},
    )
    assert r.status_code == 204, r.text

    r = client.post(
        "/api/v1/auth/token/refresh", json={"refresh_token": member_tokens["refresh_token"]}
    )
    assert r.status_code == 401
    r = client.get(
        "/api/v1/buckets", headers={"Authorization": f"Bearer {member_tokens['access_token']}"}
    )
    assert r.status_code == 401


def test_switch_does_not_revive_an_invalidated_cookie(app, db, make_household):
    from app.models import HouseholdMember, MemberRole, User

    hh = make_household(name="Home", username="owner")
    other = make_household(name="Other", username="other")
    db.add(
        HouseholdMember(household_id=other.household_id, user_id=hh.user_id, role=MemberRole.member)
    )
    db.commit()
    c = _web_login(app, "owner", hh.secret)
    csrf = c.cookies.get("csrf_token")

    user = db.get(User, hh.user_id)
    user.session_version += 1  # e.g. password changed on another device
    db.commit()

    r = c.post(
        "/household/switch",
        data={"household_id": other.household_id},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 302 and r.headers["location"] == "/login"
    # No fresh session minted; at most the stale one is cleared.
    set_cookie = r.headers.get("set-cookie", "")
    assert "session=" not in set_cookie or "session=;" in set_cookie


def test_no_csrf_cookie_for_invalidated_session(app, db, make_household):
    from app.models import User

    hh = make_household(username="owner")
    c = _web_login(app, "owner", hh.secret)
    user = db.get(User, hh.user_id)
    user.session_version += 1
    db.commit()

    c.cookies.delete("csrf_token")
    r = c.get("/login")
    assert "csrf_token" not in r.headers.get("set-cookie", "")

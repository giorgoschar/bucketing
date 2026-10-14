import pyotp
import pytest

from app.api_auth import create_access_token
from app.models import Category, Household, HouseholdMember, MemberRole
from tests.test_api_invites import CSRF_COOKIE_NAME, _login, _user

H = "/api/v1/settings/household"
HS = "/api/v1/settings/households"


def _csrf(client):
    return {"X-CSRF-Token": [c.value for c in client.cookies.jar if c.name == CSRF_COOKIE_NAME][-1]}


def _join(db, user, hh, role=MemberRole.member):
    db.add(HouseholdMember(household_id=hh.id, user_id=user.id, role=role))
    db.commit()


def _role(db, user, hh):
    return db.query(HouseholdMember).filter_by(user_id=user.id, household_id=hh.id).one().role


def _totp_user(db, name, hh=None, role=MemberRole.owner):
    u, hh = _user(db, name, hh, role)
    u.totp_secret = pyotp.random_base32()
    u.oidc_subject = f"sub-{name}"
    u.totp_backup_codes = "codes"
    db.commit()
    return u, hh


# --- list + switch -----------------------------------------------------------------------------


def test_list_shows_my_households_with_role_and_active(client, db):
    ann, hh = _user(db, "ann")
    other = Household(name="Other")
    db.add(other)
    db.flush()
    _join(db, ann, other)
    stranger, _ = _user(db, "zed")
    csrf = _login(client, ann, hh)
    rows = client.get(HS).json()
    assert {(r["name"], r["role"], r["active"]) for r in rows} == {
        ("ann home", "owner", True),
        ("Other", "member", False),
    }
    assert client.get("/api/v1/auth/me", headers=csrf).status_code == 200
    assert stranger.id not in str(rows)


def test_switch_to_my_other_household_moves_the_session(client, db):
    ann, hh = _user(db, "ann")
    other = Household(name="Other")
    db.add(other)
    db.flush()
    _join(db, ann, other)
    _login(client, ann, hh)
    r = client.post(f"{HS}/switch", json={"household_id": other.id}, headers=_csrf(client))
    assert r.status_code == 200 and r.json() == {"household_id": other.id}
    assert client.get("/api/v1/auth/me").json()["household_id"] == other.id


def test_switch_to_a_household_im_not_in_is_403(client, db):
    ann, hh = _user(db, "ann")
    _, theirs = _user(db, "zed")
    _login(client, ann, hh)
    for target in (theirs.id, "nope"):
        r = client.post(f"{HS}/switch", json={"household_id": target}, headers=_csrf(client))
        assert r.status_code == 403
    assert client.get("/api/v1/auth/me").json()["household_id"] == hh.id


# --- create ------------------------------------------------------------------------------------


def test_create_household_makes_me_owner_seeds_categories_and_switches(client, db):
    ann, hh = _user(db, "ann")
    _login(client, ann, hh)
    r = client.post(HS, json={"name": "  Cabin ", "default_currency": "EUR"}, headers=_csrf(client))
    assert r.status_code == 201
    new = db.get(Household, r.json()["household_id"])
    assert new.name == "Cabin" and _role(db, ann, new) == MemberRole.owner
    assert db.query(Category).filter_by(household_id=new.id).count() > 0
    assert client.get("/api/v1/auth/me").json()["household_id"] == new.id


def test_create_household_rejects_blank_name_and_bad_currency(client, db):
    ann, hh = _user(db, "ann")
    _login(client, ann, hh)
    assert (
        client.post(
            HS, json={"name": "  ", "default_currency": "EUR"}, headers=_csrf(client)
        ).status_code
        == 400
    )
    assert (
        client.post(
            HS, json={"name": "x", "default_currency": "ZZZ"}, headers=_csrf(client)
        ).status_code
        == 400
    )
    assert db.query(HouseholdMember).filter_by(user_id=ann.id).count() == 1


def test_create_needs_login(client):
    assert client.post(HS, json={"name": "x"}).status_code == 401


# --- leave -------------------------------------------------------------------------------------


def test_member_leaves_and_lands_in_their_other_household(client, db):
    ann, hh = _user(db, "ann")
    bob, bob_hh = _user(db, "bob")
    _join(db, bob, hh)
    _login(client, bob, hh)
    r = client.post(f"{H}/leave", json={}, headers=_csrf(client))
    assert r.status_code == 200 and r.json() == {"household_id": bob_hh.id}
    assert db.query(HouseholdMember).filter_by(user_id=bob.id, household_id=hh.id).count() == 0
    assert db.get(Household, hh.id).archived_at is None
    assert client.get("/api/v1/auth/me").json()["household_id"] == bob_hh.id


def test_owner_with_other_members_cannot_leave(client, db):
    ann, hh = _user(db, "ann")
    bob, _ = _user(db, "bob")
    _join(db, bob, hh)
    _login(client, ann, hh)
    r = client.post(f"{H}/leave", json={}, headers=_csrf(client))
    assert r.status_code == 400 and _role(db, ann, hh) == MemberRole.owner


def test_last_member_must_type_the_name_then_the_household_is_archived(client, db):
    ann, hh = _user(db, "ann")
    _login(client, ann, hh)
    assert (
        client.post(f"{H}/leave", json={"confirm_name": "nope"}, headers=_csrf(client)).status_code
        == 400
    )
    assert client.post(f"{H}/leave", json={}, headers=_csrf(client)).status_code == 400
    assert db.get(Household, hh.id).archived_at is None
    r = client.post(f"{H}/leave", json={"confirm_name": "ann home"}, headers=_csrf(client))
    assert r.status_code == 200 and r.json() == {"household_id": None}
    db.expire_all()
    assert db.get(Household, hh.id).archived_at is not None
    assert client.get("/api/v1/auth/me").status_code == 401  # no household left: signed out


# --- transfer ownership --------------------------------------------------------------------------


def test_owner_transfers_ownership(client, db):
    ann, hh = _user(db, "ann")
    bob, _ = _user(db, "bob")
    _join(db, bob, hh)
    _login(client, ann, hh)
    r = client.post(f"{H}/transfer-ownership/{bob.id}", headers=_csrf(client))
    assert r.status_code == 204
    assert (_role(db, ann, hh), _role(db, bob, hh)) == (MemberRole.member, MemberRole.owner)


def test_transfer_by_a_member_is_403_and_changes_nothing(client, db):
    ann, hh = _user(db, "ann")
    bob, _ = _user(db, "bob")
    _join(db, bob, hh)
    _login(client, bob, hh)
    assert client.post(f"{H}/transfer-ownership/{bob.id}", headers=_csrf(client)).status_code == 403
    assert _role(db, ann, hh) == MemberRole.owner


def test_transfer_to_self_or_a_stranger(client, db):
    ann, hh = _user(db, "ann")
    zed, _ = _user(db, "zed")
    _login(client, ann, hh)
    assert client.post(f"{H}/transfer-ownership/{ann.id}", headers=_csrf(client)).status_code == 400
    assert client.post(f"{H}/transfer-ownership/{zed.id}", headers=_csrf(client)).status_code == 404
    assert _role(db, ann, hh) == MemberRole.owner


# --- reset 2FA -----------------------------------------------------------------------------------


def _reset(client, member, owner, code=None):
    code = pyotp.TOTP(owner.get_totp_secret()).now() if code is None else code
    return client.post(
        f"{H}/members/{member.id}/reset-2fa", json={"owner_code": code}, headers=_csrf(client)
    )


def test_owner_resets_a_members_2fa_and_nothing_secret_comes_back(client, db):
    ann, hh = _totp_user(db, "ann")
    bob, _ = _totp_user(db, "bob", hh, MemberRole.member)
    old_secret, sv = bob.totp_secret, bob.session_version
    _login(client, ann, hh)
    r = _reset(client, bob, ann)
    assert r.status_code == 204 and r.content == b""
    db.refresh(bob)
    assert (bob.totp_secret, bob.totp_enabled, bob.totp_backup_codes, bob.oidc_subject) == (
        None,
        False,
        None,
        None,
    )
    assert bob.last_totp_step is None and bob.session_version == sv + 1 and old_secret


def test_reset_with_a_wrong_owner_code_changes_nothing(client, db):
    ann, hh = _totp_user(db, "ann")
    bob, _ = _totp_user(db, "bob", hh, MemberRole.member)
    _login(client, ann, hh)
    assert _reset(client, bob, ann, code="000000").status_code == 400
    db.refresh(bob)
    assert bob.totp_enabled and bob.totp_secret and bob.oidc_subject


def test_reset_by_a_member_is_403(client, db):
    ann, hh = _totp_user(db, "ann")
    bob, _ = _totp_user(db, "bob", hh, MemberRole.member)
    _login(client, bob, hh)
    assert _reset(client, ann, bob).status_code == 403
    db.refresh(ann)
    assert ann.totp_enabled


def test_reset_of_someone_outside_the_household_is_404(client, db):
    ann, hh = _totp_user(db, "ann")
    zed, _ = _totp_user(db, "zed")
    _login(client, ann, hh)
    assert _reset(client, zed, ann).status_code == 404
    db.refresh(zed)
    assert zed.totp_enabled and zed.oidc_subject


def test_reset_needs_csrf(client, db):
    ann, hh = _totp_user(db, "ann")
    bob, _ = _totp_user(db, "bob", hh, MemberRole.member)
    _login(client, ann, hh)
    r = client.post(f"{H}/members/{bob.id}/reset-2fa", json={"owner_code": "1"})
    assert r.status_code == 403


# --- cookie session only -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/v1/invites/tok/accept", None),
        (f"{HS}/switch", {"household_id": "x"}),
        (HS, {"name": "New"}),
        (f"{H}/leave", {"confirm_name": ""}),
        (f"{H}/transfer-ownership/m", None),
        (f"{H}/members/m/reset-2fa", {"owner_code": "000000"}),
    ],
)
def test_household_admin_rejects_bearer_tokens(client, db, path, body):
    ann, hh = _user(db, "ann")
    token = create_access_token(ann.id, hh.id, ann.session_version)
    r = client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text
    assert db.query(Household).count() == 1

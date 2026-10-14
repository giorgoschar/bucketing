from datetime import timedelta

from starlette.responses import Response

from app.auth import CSRF_COOKIE_NAME, set_session
from app.core.clock import utcnow_naive
from app.models import Household, HouseholdMember, Invitation, MemberRole, User


def _user(db, name, hh=None, role=MemberRole.owner, totp=True):
    u = User(
        username=name,
        email=f"{name}@x.t",
        display_name=name.title(),
        password_hash="x",
        totp_enabled=totp,
    )
    db.add(u)
    db.flush()
    if hh is None:
        hh = Household(name=f"{name} home")
        db.add(hh)
        db.flush()
    db.add(HouseholdMember(household_id=hh.id, user_id=u.id, role=role))
    db.commit()
    return u, hh


def _login(client, u, hh, amr="pwd"):
    r = Response()
    set_session(r, u.id, hh.id, u.session_version, amr=amr)
    for raw in r.headers.getlist("set-cookie"):
        name, _, rest = raw.partition("=")
        client.cookies.set(name, rest.split(";")[0])
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}


def _invite(db, owner, hh, **kw):
    inv = Invitation(household_id=hh.id, created_by=owner.id, **kw)
    db.add(inv)
    db.commit()
    return inv


def test_preview_needs_no_login_and_shows_only_name_and_inviter(client, db):
    owner, hh = _user(db, "ann")
    inv = _invite(db, owner, hh, expires_at=utcnow_naive() + timedelta(days=1))
    r = client.get(f"/api/v1/invites/{inv.token}")
    assert r.status_code == 200
    assert r.json() == {"household_name": "ann home", "inviter": "Ann"}


def test_preview_unknown_used_expired_archived(client, db):
    owner, hh = _user(db, "ann")
    assert client.get("/api/v1/invites/nope").status_code == 404
    used = _invite(db, owner, hh, used_at=utcnow_naive())
    assert client.get(f"/api/v1/invites/{used.token}").status_code == 404
    old = _invite(db, owner, hh, expires_at=utcnow_naive() - timedelta(seconds=1))
    assert client.get(f"/api/v1/invites/{old.token}").status_code == 410
    hh.archived_at = utcnow_naive()
    ok = _invite(db, owner, hh)
    assert client.get(f"/api/v1/invites/{ok.token}").status_code == 404


def test_accept_requires_login(client, db):
    owner, hh = _user(db, "ann")
    inv = _invite(db, owner, hh)
    assert client.post(f"/api/v1/invites/{inv.token}/accept").status_code == 401


def test_accept_joins_as_member_burns_invite_and_switches_session(client, db):
    owner, hh = _user(db, "ann")
    bob, bob_hh = _user(db, "bob", totp=False)  # an OIDC-only sign-in has no 2FA
    inv = _invite(db, owner, hh, expires_at=utcnow_naive() + timedelta(days=1))
    csrf = _login(client, bob, bob_hh, amr="oidc")
    r = client.post(f"/api/v1/invites/{inv.token}/accept", headers=csrf)
    assert r.status_code == 200
    assert r.json() == {"household_id": hh.id, "household_name": "ann home"}
    m = db.query(HouseholdMember).filter_by(user_id=bob.id, household_id=hh.id).one()
    assert m.role == MemberRole.member
    db.refresh(inv)
    assert inv.used_by == bob.id and inv.used_at is not None
    assert client.get("/api/v1/auth/me").json()["household_id"] == hh.id
    # single use
    csrf = {"X-CSRF-Token": [c.value for c in client.cookies.jar if c.name == CSRF_COOKIE_NAME][-1]}
    again = client.post(f"/api/v1/invites/{inv.token}/accept", headers=csrf)
    assert again.status_code == 404


def test_accept_needs_csrf(client, db):
    owner, hh = _user(db, "ann")
    bob, bob_hh = _user(db, "bob")
    inv = _invite(db, owner, hh)
    _login(client, bob, bob_hh)
    assert client.post(f"/api/v1/invites/{inv.token}/accept").status_code == 403
    assert db.query(HouseholdMember).filter_by(user_id=bob.id, household_id=hh.id).count() == 0


def test_accept_expired_and_bad_token_change_nothing(client, db):
    owner, hh = _user(db, "ann")
    bob, bob_hh = _user(db, "bob")
    old = _invite(db, owner, hh, expires_at=utcnow_naive() - timedelta(seconds=1))
    csrf = _login(client, bob, bob_hh)
    assert client.post(f"/api/v1/invites/{old.token}/accept", headers=csrf).status_code == 410
    assert client.post("/api/v1/invites/nope/accept", headers=csrf).status_code == 404
    assert db.query(HouseholdMember).filter_by(user_id=bob.id, household_id=hh.id).count() == 0


def test_already_member_is_409_and_invite_stays_usable(client, db):
    owner, hh = _user(db, "ann")
    inv = _invite(db, owner, hh)
    csrf = _login(client, owner, hh)
    assert client.post(f"/api/v1/invites/{inv.token}/accept", headers=csrf).status_code == 409
    db.refresh(inv)
    assert inv.used_at is None


def test_accept_race_on_membership_is_a_409_not_a_500(client, db, monkeypatch):
    # Two invites to one household accepted at once: the second insert hits uq_household_member.
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    owner, hh = _user(db, "ann")
    bob, bob_hh = _user(db, "bob")
    inv = _invite(db, owner, hh)
    csrf = _login(client, bob, bob_hh)

    def boom(self):
        raise IntegrityError("INSERT", {}, Exception("uq_household_member"))

    monkeypatch.setattr(Session, "commit", boom)
    r = client.post(f"/api/v1/invites/{inv.token}/accept", headers=csrf)
    assert r.status_code == 409 and r.json()["detail"] == "You are already in this household."

import pytest

from app.models import User
from app.services.identity import IdentityError, link_oidc_subject, resolve_oidc_user


def _user(db, username, email, sub=None):
    u = User(
        username=username, email=email, display_name=username, password_hash="x", oidc_subject=sub
    )
    db.add(u)
    db.commit()
    return u


def test_known_subject_wins(db):
    u = _user(db, "g", "g@x.t", sub="sub-1")
    assert resolve_oidc_user(db, {"sub": "sub-1", "email": "other@x.t"}).id == u.id


def test_email_alone_never_links(db):
    u = _user(db, "g", "g@x.t")
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "sub-2", "email": "g@x.t", "email_verified": True})
    assert e.value.code == "not_linked"
    db.refresh(u)
    assert u.oidc_subject is None


def test_unknown_subject_creates_nothing(db):
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "s", "email": "nobody@x.t", "email_verified": True})
    assert e.value.code == "not_linked"
    assert db.query(User).count() == 0


def test_missing_sub_is_refused(db):
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"email": "g@x.t", "email_verified": True})
    assert e.value.code == "not_linked"


def test_link_sets_subject(db):
    u = _user(db, "g", "g@x.t")
    link_oidc_subject(db, u, "sub-1")
    db.refresh(u)
    assert u.oidc_subject == "sub-1"


def test_link_is_idempotent(db):
    u = _user(db, "g", "g@x.t", sub="sub-1")
    link_oidc_subject(db, u, "sub-1")
    assert u.oidc_subject == "sub-1"


def test_link_conflicts_with_other_user(db):
    _user(db, "a", "a@x.t", sub="sub-1")
    b = _user(db, "b", "b@x.t")
    with pytest.raises(IdentityError) as e:
        link_oidc_subject(db, b, "sub-1")
    assert e.value.code == "subject_conflict"
    db.refresh(b)
    assert b.oidc_subject is None


def test_link_conflicts_with_existing_different_subject(db):
    u = _user(db, "g", "g@x.t", sub="sub-old")
    with pytest.raises(IdentityError) as e:
        link_oidc_subject(db, u, "sub-new")
    assert e.value.code == "subject_conflict"
    db.refresh(u)
    assert u.oidc_subject == "sub-old"


@pytest.mark.parametrize("sub", [None, ""])
def test_link_empty_sub_is_refused(db, sub):
    u = _user(db, "g", "g@x.t")
    with pytest.raises(IdentityError) as e:
        link_oidc_subject(db, u, sub)
    assert e.value.code == "not_linked"


def test_link_integrity_error_becomes_subject_conflict_and_rolls_back(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    u = _user(db, "g", "g@x.t")
    rolled = []
    monkeypatch.setattr(
        db, "commit", lambda: (_ for _ in ()).throw(IntegrityError("stmt", {}, Exception("dup")))
    )
    real_rollback = db.rollback
    monkeypatch.setattr(db, "rollback", lambda: (rolled.append(1), real_rollback())[1])
    with pytest.raises(IdentityError) as e:
        link_oidc_subject(db, u, "sub-race")
    assert e.value.code == "subject_conflict"
    assert rolled
    monkeypatch.undo()
    db.refresh(u)
    assert u.oidc_subject is None

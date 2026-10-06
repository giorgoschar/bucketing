import pytest

from app.models import User
from app.services.identity import IdentityError, resolve_oidc_user


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


def test_first_sign_in_links_by_verified_email(db):
    u = _user(db, "g", "G@X.t")
    got = resolve_oidc_user(db, {"sub": "sub-2", "email": "g@x.T", "email_verified": True})
    assert got.id == u.id
    db.refresh(u)
    assert u.oidc_subject == "sub-2"


def test_unverified_email_is_refused(db):
    _user(db, "g", "g@x.t")
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "s", "email": "g@x.t", "email_verified": False})
    assert e.value.code == "no_account"


def test_unknown_email_is_refused_and_creates_nothing(db):
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "s", "email": "nobody@x.t", "email_verified": True})
    assert e.value.code == "no_account"
    assert db.query(User).count() == 0


def test_email_already_linked_to_another_subject_is_refused(db):
    _user(db, "g", "g@x.t", sub="sub-old")
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "sub-new", "email": "g@x.t", "email_verified": True})
    assert e.value.code == "subject_conflict"


def test_missing_sub_is_refused(db):
    with pytest.raises(IdentityError):
        resolve_oidc_user(db, {"email": "g@x.t", "email_verified": True})

"""Map a verified Pocket ID identity to a local user. Never creates users."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User


class IdentityError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def resolve_oidc_user(db: Session, claims: dict) -> User:
    sub = claims.get("sub")
    if not sub:
        raise IdentityError("no_account")

    user = db.query(User).filter(User.oidc_subject == sub).one_or_none()
    if user:
        return user

    email = (claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is not True:
        raise IdentityError("no_account")

    matches = db.query(User).filter(func.lower(User.email) == email).all()
    if not matches:
        raise IdentityError("no_account")
    if len(matches) > 1:
        raise IdentityError("ambiguous")
    user = matches[0]
    if user.oidc_subject and user.oidc_subject != sub:
        raise IdentityError("subject_conflict")

    user.oidc_subject = sub
    db.commit()
    return user

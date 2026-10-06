"""Map a verified Pocket ID identity to a local user. Never creates users.

Matching is by the OIDC `sub` only. Email is never used to link: a passkey is
attached to an account solely from inside an already signed-in password+2FA
session (see link_oidc_subject and GET /app/auth/link).
"""

from sqlalchemy.orm import Session

from app.models import User


class IdentityError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def resolve_oidc_user(db: Session, claims: dict) -> User:
    sub = claims.get("sub")
    if not sub:
        raise IdentityError("not_linked")
    user = db.query(User).filter(User.oidc_subject == sub).one_or_none()
    if not user:
        raise IdentityError("not_linked")
    return user


def link_oidc_subject(db: Session, user: User, sub: str | None) -> None:
    if not sub:
        raise IdentityError("not_linked")
    other = db.query(User).filter(User.oidc_subject == sub, User.id != user.id).first()
    if other:
        raise IdentityError("subject_conflict")
    if user.oidc_subject:
        if user.oidc_subject != sub:
            raise IdentityError("subject_conflict")
        return
    user.oidc_subject = sub
    db.commit()

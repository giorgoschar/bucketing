"""TOTP enrolment shared by the old settings pages (app/routes/settings.py)
and /api/v1/settings/security (2d §7.5). The secret lives on the user row
while totp_enabled is False (an enrolment in progress); it grants nothing
until a valid code confirms it."""

import json
import logging
import secrets

import bcrypt as _bcrypt
import pyotp
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.auth import invalidate_user_sessions
from app.core.config import settings
from app.models import User

security_logger = logging.getLogger("security")

BACKUP_CODE_COUNT = 8


def pending_secret(db: Session, user: User) -> str:
    """The user's in-progress TOTP secret, created (and committed) if needed."""
    secret = None
    if user.totp_secret:
        try:
            secret = user.get_totp_secret()
        except InvalidToken:
            # Unreadable pending secret (key changed): safe to replace only while
            # not enrolled; an enabled secret is never overwritten here.
            if user.totp_enabled:
                raise
            security_logger.error(
                "Pending TOTP secret for user_id=%s is unreadable; restarting enrollment", user.id
            )
    if not secret:
        secret = pyotp.random_base32()
        user.set_totp_secret(secret)
        # The step counter belongs to the old secret; keeping it could refuse
        # the new secret's first code as a replay.
        user.last_totp_step = None
        db.commit()
    return secret


def otpauth_uri(user: User, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=settings.app_name)


def new_backup_codes() -> tuple[list[str], str]:
    """(plain codes to show once, JSON of their bcrypt hashes to store)."""
    plain = [secrets.token_hex(5).upper() for _ in range(BACKUP_CODE_COUNT)]
    hashed = [_bcrypt.hashpw(c.encode(), _bcrypt.gensalt()).decode() for c in plain]
    return plain, json.dumps(hashed)


def backup_codes_remaining(user: User) -> int:
    if not user.totp_enabled or not user.totp_backup_codes:
        return 0
    try:
        return len(json.loads(user.totp_backup_codes))
    except (ValueError, TypeError):
        return 0


def turn_off_totp(db: Session, user: User) -> None:
    """Clear the secret and codes, sign out everywhere, revoke Shortcut
    tokens. The caller has verified password and code, and commits."""
    from app.services import revoke_user_tokens

    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    user.last_totp_step = None
    invalidate_user_sessions(db, user)
    revoke_user_tokens(db, user.id)

"""Personal API tokens: issue, list, revoke.

A token is ``pat_`` + 32 url-safe characters. Only its SHA-256 hex digest is
stored, so a database leak does not leak usable credentials; the plaintext is
returned once by :func:`issue_personal_token` and never logged. Tokens belong
to one member in one household and are only ever managed by that member.
"""
import hashlib
import secrets

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.clock import utcnow_naive
from app.models import Bucket, BucketStatus, PersonalApiToken

TOKEN_PREFIX = "pat_"
TOKEN_BODY_LEN = 32
DISPLAY_PREFIX_LEN = 12
INGEST_SCOPE = "ingest"
MAX_NAME_LEN = 60


def hash_personal_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_raw_token() -> str:
    # token_urlsafe(24) yields exactly 32 chars from [A-Za-z0-9_-].
    body = secrets.token_urlsafe(24)[:TOKEN_BODY_LEN]
    return TOKEN_PREFIX + body


def active_household_bucket(db: Session, household_id: str, bucket_id: str | None) -> Bucket | None:
    """The bucket if it is an active bucket of this household, else None."""
    if not bucket_id:
        return None
    bucket = db.get(Bucket, bucket_id)
    if bucket is None or bucket.household_id != household_id \
            or bucket.status != BucketStatus.active:
        return None
    return bucket


def issue_personal_token(
    db: Session,
    *,
    user_id: str,
    household_id: str,
    name: str,
    default_bucket_id: str | None = None,
) -> tuple[PersonalApiToken, str]:
    """Create a token for ``user_id`` in ``household_id``; return (row, plaintext).

    The caller has authenticated ``user_id`` as a member of ``household_id``
    and commits. Raises HTTP 422 for a blank name and 400 for a default bucket
    that is not an active bucket of the household.
    """
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Give the token a name.")
    if len(name) > MAX_NAME_LEN:
        raise HTTPException(status_code=422,
                            detail=f"Name must be at most {MAX_NAME_LEN} characters.")
    default_bucket_id = default_bucket_id or None
    if default_bucket_id and active_household_bucket(db, household_id, default_bucket_id) is None:
        raise HTTPException(status_code=400,
                            detail="Default bucket must be an active bucket of this household.")

    raw = _new_raw_token()
    record = PersonalApiToken(
        user_id=user_id,
        household_id=household_id,
        name=name,
        token_hash=hash_personal_token(raw),
        prefix=raw[:DISPLAY_PREFIX_LEN],
        scopes=INGEST_SCOPE,
        default_bucket_id=default_bucket_id,
    )
    db.add(record)
    db.flush()
    return record, raw


def list_personal_tokens(db: Session, *, user_id: str, household_id: str) -> list[PersonalApiToken]:
    """This member's live (unrevoked) tokens for this household, newest first."""
    return (
        db.query(PersonalApiToken)
        .filter(PersonalApiToken.user_id == user_id,
                PersonalApiToken.household_id == household_id,
                PersonalApiToken.revoked_at.is_(None))
        .order_by(PersonalApiToken.created_at.desc())
        .all()
    )


def revoke_personal_token(db: Session, *, token_id: str, user_id: str, household_id: str) -> None:
    """Revoke one of this member's tokens; 404 for anything else. Caller commits."""
    record = db.get(PersonalApiToken, token_id)
    if (record is None or record.user_id != user_id
            or record.household_id != household_id or record.revoked_at is not None):
        raise HTTPException(status_code=404, detail="Token not found.")
    record.revoked_at = utcnow_naive()


def revoke_user_tokens(db: Session, user_id: str, household_id: str | None = None) -> int:
    """Revoke a user's live tokens (all households, or just one). Rows are kept.

    Called on account-recovery steps (password change, 2FA disable/reset) and
    when a member leaves or is removed, so a re-added member's old Shortcut
    stays dead. NOT called on plain logout. Caller commits.
    """
    q = db.query(PersonalApiToken).filter(PersonalApiToken.user_id == user_id,
                                          PersonalApiToken.revoked_at.is_(None))
    if household_id is not None:
        q = q.filter(PersonalApiToken.household_id == household_id)
    return q.update({PersonalApiToken.revoked_at: utcnow_naive()}, synchronize_session=False)


def token_dict(record: PersonalApiToken) -> dict:
    """Public view of a token: never the hash, never the plaintext."""
    return {
        "id": record.id,
        "name": record.name,
        "prefix": record.prefix,
        "scopes": record.scope_list,
        "default_bucket_id": record.default_bucket_id,
        "last_used_at": record.last_used_at.isoformat() if record.last_used_at else None,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }

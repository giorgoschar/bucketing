"""
JWT authentication utilities and FastAPI dependencies for the /api/v1 routes.

Token design:
  - Access token:  short-lived JWT (default 60 min), Bearer scheme
  - Refresh token: long-lived opaque token stored as SHA-256 hash in DB
  - Pending token: access token with scope="2fa_pending", valid only for TOTP verify

Access token claims:
  {
    "sub":   "<user_id>",
    "hh":    "<household_id>",
    "sv":    <session_version int>,   # invalidated on password/TOTP change
    "scope": "api" | "2fa_pending",
    "exp":   <unix timestamp>
  }
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, RefreshToken

_bearer = HTTPBearer(auto_error=False)

_ALGORITHM = settings.jwt_algorithm


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, household_id: str, session_version: int) -> str:
    """Return a signed JWT access token with scope='api'."""
    expire = _utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub":   user_id,
        "hh":    household_id,
        "sv":    session_version,
        "scope": "api",
        "exp":   expire,
    }
    return jwt.encode(payload, settings.effective_jwt_secret, algorithm=_ALGORITHM)


def create_pending_token(user_id: str, household_id: str) -> str:
    """Return a short-lived JWT valid only for the TOTP-verify endpoint (scope='2fa_pending')."""
    expire = _utcnow() + timedelta(minutes=5)
    payload = {
        "sub":   user_id,
        "hh":    household_id,
        "scope": "2fa_pending",
        "exp":   expire,
    }
    return jwt.encode(payload, settings.effective_jwt_secret, algorithm=_ALGORITHM)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_refresh_token(user_id: str, household_id: str, db: Session) -> str:
    """
    Generate a cryptographically random refresh token, store its hash in the DB,
    and return the raw token to the caller (never stored in plaintext).
    """
    raw = secrets.token_urlsafe(48)
    expires_at = _utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
    record = RefreshToken(
        user_id=user_id,
        household_id=household_id,
        token_hash=_hash_token(raw),
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    return raw


# ---------------------------------------------------------------------------
# Token verification helpers
# ---------------------------------------------------------------------------

def _decode_token(token: str) -> dict:
    """Decode and return JWT claims; raises HTTPException on any failure."""
    try:
        return jwt.decode(token, settings.effective_jwt_secret, algorithms=[_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_api_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """
    Full API auth dependency.  Validates the Bearer access token and enforces:
      1. Token present, valid signature, not expired
      2. scope == 'api' (not a pending 2FA token)
      3. User exists in DB
      4. session_version matches (invalidated on password/TOTP change)
      5. TOTP enrolled

    Returns (user, household_id).
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_token(credentials.credentials)

    if claims.get("scope") != "api":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token scope is not valid for this endpoint",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, claims["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if claims.get("sv", -1) != user.session_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated — please log in again",
        )

    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TOTP enrollment required",
        )

    return user, claims["hh"]


def require_api_pending(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """
    Dependency for the TOTP-verify endpoint only.
    Token must have scope='2fa_pending'.
    Returns (user, household_id).
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = _decode_token(credentials.credentials)

    if claims.get("scope") != "2fa_pending":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A pending 2FA token is required for this endpoint",
        )

    user = db.get(User, claims["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user, claims["hh"]


def rotate_refresh_token(raw_token: str, db: Session) -> tuple[str, str]:
    """
    Validate a refresh token, revoke it, issue a new refresh + access token pair.
    Returns (new_access_token, new_refresh_token).
    Raises HTTP 401 on any failure.
    """
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter_by(token_hash=token_hash).first()

    if not record or record.revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or revoked")

    now = _utcnow()
    expires_at = record.expires_at
    # Make expires_at timezone-aware if it isn't (SQLite stores naive datetimes)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now > expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="TOTP enrollment required")

    # Revoke old token
    record.revoked = True
    db.commit()

    # Issue new pair
    new_access = create_access_token(user.id, record.household_id, user.session_version)
    new_refresh = create_refresh_token(user.id, record.household_id, db)
    return new_access, new_refresh


def revoke_refresh_token(raw_token: str, db: Session) -> None:
    """Mark a refresh token as revoked (logout)."""
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
    if record and not record.revoked:
        record.revoked = True
        db.commit()

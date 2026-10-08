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
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.clock import utcnow, utcnow_naive
from app.core.config import settings
from app.core.database import get_db
from app.models import HouseholdMember, PersonalApiToken, RefreshToken, User

_bearer = HTTPBearer(auto_error=False)

_ALGORITHM = settings.jwt_algorithm


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return utcnow()


def create_access_token(user_id: str, household_id: str, session_version: int) -> str:
    """Return a signed JWT access token with scope='api'."""
    expire = _utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "hh": household_id,
        "sv": session_version,
        "scope": "api",
        "exp": expire,
    }
    return jwt.encode(payload, settings.effective_jwt_secret, algorithm=_ALGORITHM)


def create_pending_token(user_id: str, household_id: str) -> str:
    """Return a short-lived JWT valid only for the TOTP-verify endpoint (scope='2fa_pending')."""
    expire = _utcnow() + timedelta(minutes=5)
    payload = {
        "sub": user_id,
        "hh": household_id,
        "scope": "2fa_pending",
        "exp": expire,
    }
    return jwt.encode(payload, settings.effective_jwt_secret, algorithm=_ALGORITHM)


def _is_member(db: Session, household_id: str | None, user_id: str) -> bool:
    return (
        db.query(HouseholdMember).filter_by(household_id=household_id, user_id=user_id).first()
        is not None
    )


def revoke_member_access(db: Session, user: User, household_id: str) -> None:
    """Kill a removed member's sessions and refresh tokens for this household.

    Bumping session_version logs the user out everywhere (cookies and access
    tokens carry it); revoking refresh tokens stops new access tokens being
    minted. The caller commits.
    """
    user.session_version = (user.session_version or 0) + 1
    db.query(RefreshToken).filter_by(user_id=user.id, household_id=household_id).update(
        {RefreshToken.revoked: True}, synchronize_session=False
    )
    # Personal ingest tokens too, so re-adding the member later does not
    # revive an old Shortcut.
    from app.services.personal_tokens import revoke_user_tokens

    revoke_user_tokens(db, user.id, household_id)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_refresh_token(
    user_id: str, household_id: str, db: Session, session_version: int = 0
) -> str:
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
        session_version=session_version,
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
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_of(url: str | None) -> str | None:
    """Canonical scheme://host[:port] of a URL or Origin header, else None.

    Lowercases scheme and host, drops a default port, path, query and userinfo, so
    "https://Expenses.example:443/" and "https://expenses.example" compare equal.
    "null", schemeless or malformed values give None (never equal to anything).
    """
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname  # already lowercased, userinfo stripped
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _app_origin(request: Request) -> str | None:
    # Production refuses to start without APP_BASE_URL; the request URL is the DEBUG fallback.
    return _origin_of(settings.app_base_url or str(request.base_url))


def _cookie_auth(request: Request, db: Session, *, allow_unenrolled: bool = False):
    """Session-cookie auth for the new app at /app (same origin, no tokens in JS)."""
    from app.auth import COOKIE_NAME, csrf_matches, decode_cookie

    # CORS allows some origins for Bearer clients (mobile/Capacitor); the cookie is
    # for the same-origin app only, so a cross-origin request never rides on it.
    # Same-origin fetches send Origin on POST and often omit it on GET: both pass.
    origin = request.headers.get("origin")
    if origin is not None and (
        _origin_of(origin) is None or _origin_of(origin) != _app_origin(request)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cross-origin cookie requests are not allowed",
        )

    unauth = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    if not session or session.get("state") != "authenticated":
        raise unauth
    user = db.get(User, session.get("user_id"))
    if not user or session.get("sv", -1) != user.session_version:
        raise unauth
    hh_id = session.get("hh_id")
    if not _is_member(db, hh_id, user.id):
        raise unauth
    if request.method in _UNSAFE and not csrf_matches(request, user.id):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    if not allow_unenrolled and not user.totp_enabled and session.get("amr") != "oidc":
        raise HTTPException(status_code=403, detail="TOTP enrollment required")
    # The offline queue names the account it was saved under; the shared session cookie may have
    # flipped to someone else since, and a queued write must never land in their household.
    expected = request.headers.get("X-Expected-Account")
    if expected is not None and expected != f"{user.id}:{hh_id}":
        raise HTTPException(status_code=412, detail="Signed in as a different account")
    # Fully validated: lets the security-headers middleware re-issue a missing CSRF cookie.
    request.state.user = user
    request.state.user_id = user.id
    from app.auth import csrf_for_request

    csrf_for_request(request)  # a token near its end of life is replaced via the middleware
    return user, hh_id


def _api_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
    *,
    allow_unenrolled: bool,
):
    if not credentials:
        return _cookie_auth(request, db, allow_unenrolled=allow_unenrolled)

    if credentials.credentials.startswith(PAT_PREFIX):
        # Personal ingest tokens only ever authenticate the ingest endpoint.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Personal tokens are not valid for this endpoint",
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

    if not _is_member(db, claims.get("hh"), user.id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not a member of this household",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # allow_unenrolled is for the cookie session only; a Bearer token always needs 2FA.
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TOTP enrollment required",
        )

    return user, claims["hh"]


def require_api_auth(
    request: Request,
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
    return _api_auth(request, credentials, db, allow_unenrolled=False)


def require_api_auth_enrolling(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """require_api_auth without the "2FA enrolled" check: for the three
    security endpoints a signed-in member needs to set 2FA up again after
    turning it off (2d §7.5). Everything else uses require_api_auth."""
    return _api_auth(request, credentials, db, allow_unenrolled=True)


PAT_PREFIX = "pat_"


def _ingest_unauthorized(detail: str = "Invalid ingest token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# Failed ingest authentications per client IP. Valid tokens are limited per
# token by the endpoint itself (60/hour); this only throttles guessing.
INGEST_FAILURE_LIMIT = "20/minute"


def _ingest_failure(request: Request | None, detail: str = "Invalid ingest token") -> HTTPException:
    """Count a failed ingest auth against the client IP: 401, or 429 once over
    the limit. Uses the shared limiter's storage (reset between tests)."""
    if request is not None:
        from limits import parse

        from app.core.ratelimit import client_key, limiter

        if not limiter.limiter.hit(parse(INGEST_FAILURE_LIMIT), "ingest-fail", client_key(request)):
            return HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed attempts; try again later.",
            )
    return _ingest_unauthorized(detail)


def require_ingest_token(
    request: Request = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> PersonalApiToken:
    """Auth dependency for the ingest endpoint: a personal ``pat_`` token only.

    Enforces: Bearer present and ``pat_``-prefixed (JWTs are never accepted
    here), a stored hash matches, not revoked, scope includes ``ingest``, the
    owner still exists and is still a member of the token's household. Records
    ``last_used_at``. Returns the token row. The token itself is never logged.

    A rejection is logged and recorded (Settings → Automations) so a broken
    wake-up is diagnosable even when the failure is here and not in the
    payload — a revoked token says not a word about the request body.
    """
    try:
        if not credentials or not credentials.credentials.startswith(PAT_PREFIX):
            raise _ingest_failure(request, "A personal ingest token is required")

        from app.services.personal_tokens import INGEST_SCOPE, hash_personal_token

        digest = hash_personal_token(credentials.credentials)
        # Lookup is by the SHA-256 of a 192-bit random secret, so query timing
        # reveals nothing usable; the compare_digest is belt and braces.
        record = db.query(PersonalApiToken).filter_by(token_hash=digest).first()
        if record is None or not hmac.compare_digest(record.token_hash, digest):
            raise _ingest_failure(request)
        if record.revoked_at is not None:
            raise _ingest_failure(request, "Token revoked")
        if INGEST_SCOPE not in record.scope_list:
            raise _ingest_failure(request, "Token scope is not valid for this endpoint")
        if db.get(User, record.user_id) is None or not _is_member(
            db, record.household_id, record.user_id
        ):
            raise _ingest_failure(request, "Not a member of this household")

        record.last_used_at = utcnow_naive()
        db.commit()
        return record
    except HTTPException as exc:
        from app.services.ingest import record_ingest_attempt

        record_ingest_attempt(
            status=exc.status_code,
            detail=exc.detail,
            content_type=request.headers.get("content-type") if request else None,
            raw_token=credentials.credentials if credentials else None,
            path=request.url.path if request else None,
            db=db,
        )
        raise


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalid or revoked"
        )

    now = _utcnow()
    expires_at = record.expires_at
    # Make expires_at timezone-aware if it isn't (SQLite stores naive datetimes)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if now > expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )

    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if record.session_version != user.session_version:
        record.revoked = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated — please log in again",
        )

    if not _is_member(db, record.household_id, user.id):
        record.revoked = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a member of this household"
        )

    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="TOTP enrollment required"
        )

    # Revoke old token
    record.revoked = True
    db.commit()

    # Issue new pair
    new_access = create_access_token(user.id, record.household_id, user.session_version)
    new_refresh = create_refresh_token(user.id, record.household_id, db, user.session_version)
    return new_access, new_refresh


def revoke_refresh_token(raw_token: str, db: Session) -> None:
    """Mark a refresh token as revoked (logout)."""
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
    if record and not record.revoked:
        record.revoked = True
        db.commit()

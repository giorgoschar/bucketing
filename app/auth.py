"""
Auth helpers: password hashing, session cookie management, CSRF, FastAPI dependencies.

Session cookie payload:
  Full session:    {"user_id": "...", "hh_id": "...", "sv": <int>, "state": "authenticated"}
  Pending session: {"user_id": "...", "hh_id": "...", "state": "2fa_pending"|"2fa_enroll"}
"""
import bcrypt as _bcrypt
import hashlib
import logging
import secrets
from datetime import datetime
from typing import Optional

from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, HouseholdMember

_serializer = URLSafeSerializer(settings.app_secret_key, salt="session")
_csrf_serializer = URLSafeSerializer(settings.app_secret_key, salt="csrf")

COOKIE_NAME = "session"
PENDING_COOKIE_NAME = "session_pending"
PENDING_MAX_AGE = 60 * 5  # 5 minutes

security_logger = logging.getLogger("security")


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def _prepare(plain: str) -> bytes:
    """SHA-256 digest → bytes, always <72 bytes for bcrypt."""
    return hashlib.sha256(plain.encode()).hexdigest().encode()


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(_prepare(plain), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(_prepare(plain), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session cookies
# ---------------------------------------------------------------------------

def _cookie_kwargs(max_age: int) -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "max_age": max_age,
        "secure": not settings.debug,
    }


def set_session(response, user_id: str, household_id: str, session_version: int):
    """Set a full authenticated session cookie."""
    value = _serializer.dumps({
        "user_id": user_id,
        "hh_id": household_id,
        "sv": session_version,
        "state": "authenticated",
    })
    response.set_cookie(COOKIE_NAME, value, **_cookie_kwargs(60 * 60 * 24 * 30))
    response.delete_cookie(PENDING_COOKIE_NAME)


def set_pending_session(response, user_id: str, household_id: str, state: str):
    """Set a short-lived pending session (2fa_pending or 2fa_enroll)."""
    value = _serializer.dumps({
        "user_id": user_id,
        "hh_id": household_id,
        "state": state,
    })
    response.set_cookie(PENDING_COOKIE_NAME, value, **_cookie_kwargs(PENDING_MAX_AGE))


def clear_session(response):
    response.delete_cookie(COOKIE_NAME)
    response.delete_cookie(PENDING_COOKIE_NAME)


def decode_cookie(cookie: str) -> Optional[dict]:
    try:
        return _serializer.loads(cookie)
    except BadSignature:
        return None


def get_current_session(request: Request) -> Optional[dict]:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    return decode_cookie(cookie)


def get_pending_session(request: Request) -> Optional[dict]:
    cookie = request.cookies.get(PENDING_COOKIE_NAME)
    if not cookie:
        return None
    return decode_cookie(cookie)


# ---------------------------------------------------------------------------
# CSRF — double-submit via itsdangerous-signed token
# ---------------------------------------------------------------------------

def generate_csrf_token(user_id: str) -> str:
    """Return a signed CSRF token tied to this user."""
    nonce = secrets.token_hex(16)
    return _csrf_serializer.dumps({"uid": user_id, "n": nonce})


def verify_csrf_token(token: str, user_id: str) -> bool:
    """Verify the submitted CSRF token matches the user."""
    try:
        data = _csrf_serializer.loads(token, max_age=60 * 60 * 4)  # 4 hours
        return data.get("uid") == user_id
    except Exception:
        return False


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_auth(request: Request, db: Session = Depends(get_db)):
    """
    Full auth dependency. Enforces:
    1. Cookie present and valid signature, state == "authenticated"
    2. User exists in DB
    3. session_version matches (invalidates old sessions after pw change)
    4. TOTP enrolled — if not, redirects to enroll flow
    Returns (user, household_id).
    """
    session = get_current_session(request)

    # Check for a pending 2FA cookie and redirect appropriately
    if not session:
        pending = get_pending_session(request)
        if pending:
            state = pending.get("state")
            if state == "2fa_pending":
                raise HTTPException(status_code=302, headers={"Location": "/login/verify"})
            if state == "2fa_enroll":
                raise HTTPException(status_code=302, headers={"Location": "/settings/2fa/enroll"})
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    if session.get("state") != "authenticated":
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    user = db.get(User, session["user_id"])
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    # Session version check — invalidates all cookies after password change / TOTP reset
    if session.get("sv", -1) != user.session_version:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    # TOTP enrollment enforcement — every authenticated user must enroll
    if not user.totp_enabled:
        raise HTTPException(status_code=302, headers={"Location": "/settings/2fa/enroll"})

    return user, session["hh_id"]


def require_household_member(
    request: Request,
    db: Session = Depends(get_db),
):
    """Returns (user, household_member) ensuring user belongs to active household."""
    session = get_current_session(request)
    if not session or session.get("state") != "authenticated":
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    user = db.get(User, session["user_id"])
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    if session.get("sv", -1) != user.session_version:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    if not user.totp_enabled:
        raise HTTPException(status_code=302, headers={"Location": "/settings/2fa/enroll"})

    hh_id = session["hh_id"]
    membership = (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id, household_id=hh_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=302, headers={"Location": "/dashboard"})

    return user, membership


def require_pending_session(request: Request) -> dict:
    """
    Dependency for /login/verify and /settings/2fa/enroll.
    Returns the pending session dict or redirects to login.
    """
    pending = get_pending_session(request)
    if not pending:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    return pending


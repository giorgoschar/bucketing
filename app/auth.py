"""
Auth helpers: password hashing and session cookie management.
Sessions are signed cookies via itsdangerous — no JWT, no DB sessions.
Cookie stores: {"user_id": "...", "active_household_id": "..."}
"""
import bcrypt as _bcrypt
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import Request, HTTPException, Depends
from itsdangerous import URLSafeSerializer, BadSignature
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, HouseholdMember

_serializer = URLSafeSerializer(settings.app_secret_key, salt="session")

COOKIE_NAME = "session"


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
# Session cookie
# ---------------------------------------------------------------------------

def create_session_cookie(user_id: str, household_id: str) -> str:
    return _serializer.dumps({"user_id": user_id, "hh_id": household_id})


def decode_session_cookie(cookie: str) -> Optional[dict]:
    try:
        return _serializer.loads(cookie)
    except BadSignature:
        return None


def set_session(response, user_id: str, household_id: str):
    value = create_session_cookie(user_id, household_id)
    response.set_cookie(
        COOKIE_NAME,
        value,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )


def clear_session(response):
    response.delete_cookie(COOKIE_NAME)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def get_current_session(request: Request) -> Optional[dict]:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    return decode_session_cookie(cookie)


def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dependency: returns (user, active_household_id) or redirects to login."""
    session = get_current_session(request)
    if not session:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    user = db.get(User, session["user_id"])
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    return user, session["hh_id"]


def require_household_member(
    request: Request,
    db: Session = Depends(get_db),
):
    """Returns (user, household_member) ensuring user belongs to active household."""
    session = get_current_session(request)
    if not session:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    user = db.get(User, session["user_id"])
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})

    hh_id = session["hh_id"]
    membership = (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id, household_id=hh_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=302, headers={"Location": "/dashboard"})

    return user, membership

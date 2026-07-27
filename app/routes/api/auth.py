"""
API auth routes: login → pending token → TOTP verify → access+refresh tokens.

Flow:
  1. POST /api/v1/auth/login         → {pending_token}
  2. POST /api/v1/auth/totp/verify   → {access_token, refresh_token, token_type, user}
  3. POST /api/v1/auth/token/refresh → {access_token, refresh_token, token_type}
  4. POST /api/v1/auth/logout        → 204
  5. GET  /api/v1/auth/me            → {user}
"""
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

import pyotp

from app.auth import verify_password_constant_time, security_logger
from app.api_auth import (
    create_pending_token,
    create_access_token,
    create_refresh_token,
    rotate_refresh_token,
    revoke_refresh_token,
    require_api_auth,
    require_api_pending,
)
from app.database import get_db
from app.models import User, HouseholdMember

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TotpVerifyRequest(BaseModel):
    pending_token: str
    code: str


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


def _user_dict(user: User) -> dict:
    return {
        "id":           user.id,
        "username":     user.username,
        "display_name": user.display_name,
        "email":        user.email,
        "avatar_color": user.avatar_color,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """
    Step 1: Validate credentials.
    Returns a short-lived pending_token (5 min) that must be exchanged via /totp/verify.
    """
    identifier = body.username.strip().lower()
    user = db.query(User).filter(
        or_(User.username == identifier, User.email == identifier)
    ).first()
    # Constant-time regardless of whether the account exists (see app/auth.py).
    if not verify_password_constant_time(body.password, user.password_hash if user else None):
        security_logger.warning("API login failed for username=%s", identifier)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Determine the household for this user
    membership = db.query(HouseholdMember).filter_by(user_id=user.id).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no household",
        )

    pending_token = create_pending_token(user.id, membership.household_id)
    return {"pending_token": pending_token, "token_type": "bearer"}


@router.post("/totp/verify")
def totp_verify(body: TotpVerifyRequest, db: Session = Depends(get_db)):
    """
    Step 2: Verify TOTP code using the pending_token from /login.
    Returns a full access_token + refresh_token pair.
    """
    from app.api_auth import _decode_token
    claims = _decode_token(body.pending_token)
    if claims.get("scope") != "2fa_pending":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid pending token")

    user = db.get(User, claims["sub"])
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.totp_enabled or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="TOTP not enrolled")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        security_logger.warning("API TOTP verify failed for user_id=%s", user.id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")

    hh_id = claims["hh"]
    access_token = create_access_token(user.id, hh_id, user.session_version)
    refresh_token = create_refresh_token(user.id, hh_id, db)

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "user":          _user_dict(user),
    }


@router.post("/token/refresh")
def token_refresh(body: TokenRefreshRequest, db: Session = Depends(get_db)):
    """
    Exchange a refresh token for a new access + refresh token pair (rotation).
    The old refresh token is immediately revoked.
    """
    new_access, new_refresh = rotate_refresh_token(body.refresh_token, db)
    return {
        "access_token":  new_access,
        "refresh_token": new_refresh,
        "token_type":    "bearer",
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: LogoutRequest, db: Session = Depends(get_db)):
    """Revoke the given refresh token. Idempotent — does not error if already revoked."""
    revoke_refresh_token(body.refresh_token, db)


@router.get("/me")
def me(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Return the authenticated user's profile."""
    user, hh_id = auth
    return {
        **_user_dict(user),
        "household_id": hh_id,
    }

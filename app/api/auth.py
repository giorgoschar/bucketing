"""
API auth routes: login → pending token → TOTP verify → access+refresh tokens.

Flow:
  1. POST /api/v1/auth/login         → {pending_token}
  2. POST /api/v1/auth/totp/verify   → {access_token, refresh_token, token_type, user}
  3. POST /api/v1/auth/token/refresh → {access_token, refresh_token, token_type}
  4. POST /api/v1/auth/logout        → 204
  5. GET  /api/v1/auth/me            → {user}
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api_auth import (
    create_access_token,
    create_pending_token,
    create_refresh_token,
    require_api_auth,
    revoke_refresh_token,
    rotate_refresh_token,
)
from app.auth import (
    clear_failed_logins,
    is_locked,
    log_id,
    register_failed_login,
    security_logger,
    verify_password_constant_time,
    verify_totp,
)
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.models import HouseholdMember, User

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

def _locked_out() -> HTTPException:
    # Same wording as a bad password; 429 like the per-IP limit, so a lockout
    # does not confirm the account exists.
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Invalid credentials")


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """
    Step 1: Validate credentials.
    Returns a short-lived pending_token (5 min) that must be exchanged via /totp/verify.
    """
    identifier = body.username.strip().lower()
    user = db.query(User).filter(
        or_(User.username == identifier, User.email == identifier)
    ).first()
    # Constant-time regardless of whether the account exists (see app/auth.py).
    password_ok = verify_password_constant_time(body.password, user.password_hash if user else None)
    if is_locked(user):
        raise _locked_out()
    if not password_ok:
        register_failed_login(db, user)
        security_logger.warning("API login failed for username=%s", log_id(identifier))
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
@limiter.limit("10/minute")
def totp_verify(request: Request, body: TotpVerifyRequest, db: Session = Depends(get_db)):
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

    if is_locked(user):
        raise _locked_out()

    if not verify_totp(db, user, body.code):
        register_failed_login(db, user)
        security_logger.warning("API TOTP verify failed for user_id=%s", user.id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TOTP code")
    clear_failed_logins(db, user)

    hh_id = claims["hh"]
    access_token = create_access_token(user.id, hh_id, user.session_version)
    refresh_token = create_refresh_token(user.id, hh_id, db, user.session_version)

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "token_type":    "bearer",
        "user":          _user_dict(user),
    }


@router.post("/token/refresh")
@limiter.limit("10/minute")
def token_refresh(request: Request, body: TokenRefreshRequest, db: Session = Depends(get_db)):
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

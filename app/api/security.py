"""/api/v1/settings/security: 2FA set up, on and off, and passkey status
(2d §7.5). The passkey itself is linked and unlinked by native form posts to
/app/auth/link and /app/auth/unlink (app/web_app.py)."""

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import _bearer, require_api_auth, require_api_auth_enrolling
from app.auth import (
    COOKIE_NAME,
    current_iat,
    decode_cookie,
    is_locked,
    register_failed_login,
    security_logger,
    set_session,
    verify_password,
    verify_totp,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.services.totp import (
    backup_codes_remaining,
    new_backup_codes,
    otpauth_uri,
    pending_secret,
    turn_off_totp,
)

router = APIRouter(prefix="/settings/security", tags=["settings"])

ALREADY_ON = "Two-factor authentication is already on."
LOCKED = "Too many failed attempts: the account is temporarily locked. Try again later."


class SecurityOut(BaseModel):
    totp_enabled: bool
    backup_codes_remaining: int
    passkey_available: bool  # the new app and the identity provider are configured
    passkey_linked: bool
    password_session: bool  # false on a passkey-only session: link/unlink need password + 2FA


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str


class BackupCodesOut(BaseModel):
    backup_codes: list[str]


class TotpDisableIn(BaseModel):
    current_password: str
    code: str


def _session_amr(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    # Cookies from before passkeys existed carry no "amr": they were all password + 2FA.
    return session.get("amr", "pwd") if session else None


def _password_session(request: Request, credentials: HTTPAuthorizationCredentials | None) -> bool:
    # Only a real Bearer token counts; some other Authorization header (a proxy's
    # Basic auth, say) leaves the cookie session in charge.
    if credentials is not None:
        return True  # Bearer tokens come from password + TOTP sign-in only
    return _session_amr(request) == "pwd"


@router.get("", response_model=SecurityOut)
def security(
    request: Request,
    auth=Depends(require_api_auth_enrolling),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    user, _ = auth
    return SecurityOut(
        totp_enabled=user.totp_enabled,
        backup_codes_remaining=backup_codes_remaining(user),
        passkey_available=bool(settings.new_app_enabled and settings.oidc_enabled),
        passkey_linked=bool(user.oidc_subject),
        password_session=_password_session(request, credentials),
    )


@router.post("/totp/setup", response_model=TotpSetupOut)
@limiter.limit("10/minute")
def totp_setup(
    request: Request,
    response: Response,
    auth=Depends(require_api_auth_enrolling),
    db: Session = Depends(get_db),
):
    """The pending secret (reused across calls) and its otpauth:// link."""
    user, _ = auth
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail=ALREADY_ON)
    secret = pending_secret(db, user)
    response.headers["Cache-Control"] = "no-store"
    return TotpSetupOut(secret=secret, otpauth_uri=otpauth_uri(user, secret))


@router.post("/totp/enable", response_model=BackupCodesOut)
@limiter.limit("10/minute")
def totp_enable(
    request: Request,
    response: Response,
    body: TotpCodeIn,
    auth=Depends(require_api_auth_enrolling),
    db: Session = Depends(get_db),
):
    """Confirm the pending secret with a code; returns the 8 backup codes once."""
    user, _ = auth
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail=ALREADY_ON)
    try:
        has_secret = bool(user.totp_secret and user.get_totp_secret())
    except InvalidToken:
        has_secret = False
    if not has_secret or not verify_totp(db, user, body.code.strip()):
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")
    plain, hashed_json = new_backup_codes()
    user.totp_enabled = True
    user.totp_backup_codes = hashed_json
    db.commit()
    security_logger.info("TOTP enrolled for '%s' (new app)", user.username)
    response.headers["Cache-Control"] = "no-store"
    return BackupCodesOut(backup_codes=plain)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def totp_disable(
    request: Request,
    body: TotpDisableIn,
    auth=Depends(require_api_auth),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Turn 2FA off: the same effects as the old route (secret and codes
    cleared, every session and token revoked), then this browser's cookie is
    reissued so the caller stays signed in, to set it up again."""
    user, hh_id = auth
    if is_locked(user):
        raise HTTPException(status_code=429, detail=LOCKED)
    if not verify_password(body.current_password, user.password_hash):
        register_failed_login(db, user)
        raise HTTPException(status_code=400, detail="Incorrect password.")
    if not user.totp_secret or not verify_totp(db, user, body.code.strip()):
        register_failed_login(db, user)
        raise HTTPException(status_code=400, detail="Invalid authenticator code.")
    amr = _session_amr(request)
    iat = current_iat(request)
    turn_off_totp(db, user)
    db.commit()
    security_logger.info("TOTP disabled for '%s' (new app)", user.username)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if amr and credentials is None:
        set_session(response, user.id, hh_id, user.session_version, amr=amr, iat=iat)
    return response

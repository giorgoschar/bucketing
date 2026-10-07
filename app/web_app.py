"""The new app at /app: passkey sign-in via Pocket ID, and (Task 5) the SPA itself."""

import logging
import time
from pathlib import Path

import httpx
from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from joserfc.errors import JoseError
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    clear_failed_logins,
    clear_session,
    csrf_matches,
    decode_cookie,
    invalidate_user_sessions,
    is_locked,
    register_failed_login,
    require_csrf,
    set_session,
    verify_password_constant_time,
    verify_totp,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.oidc import oidc_client
from app.core.ratelimit import limiter
from app.login_alerts import (
    UNLINK_PASSKEY,
    alert_failed_second_factor,
    alert_passkey_linked,
    alert_sign_in,
)
from app.models import HouseholdMember, User
from app.services.identity import IdentityError, link_oidc_subject, resolve_oidc_user

security_logger = logging.getLogger("security")

router = APIRouter(prefix="/app/auth", include_in_schema=False)


def _enabled() -> None:
    if not (settings.new_app_enabled and settings.oidc_enabled):
        raise HTTPException(status_code=404)


def _fail(code: str) -> RedirectResponse:
    return RedirectResponse(f"/app/?auth_error={code}", status_code=302)


def _callback_url(request: Request) -> str:
    base = (settings.app_base_url or str(request.base_url)).rstrip("/")
    return f"{base}/app/auth/callback"


def _password_session_user(request: Request, db: Session) -> tuple[User, str] | None:
    """(user, household_id) behind a currently valid full password+2FA session cookie, else None.

    Cookies issued before passkeys existed carry no "amr"; they were all password+2FA.
    """
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    if not session or session.get("state") != "authenticated" or session.get("amr", "pwd") != "pwd":
        return None
    user = db.get(User, session.get("user_id"))
    if not user or not user.totp_enabled or session.get("sv", -1) != user.session_version:
        return None
    hh_id = session.get("hh_id")
    if not db.query(HouseholdMember).filter_by(household_id=hh_id, user_id=user.id).first():
        return None
    return user, hh_id


# Discovery (load_server_metadata) can fail with a transport error, a bad status
# (httpx), a non-JSON body (ValueError) or metadata without an authorize endpoint.
_PROVIDER_ERRORS = (httpx.HTTPError, OAuthError, OSError, ValueError, RuntimeError)


LINK_MAX_AGE_SECONDS = 600


def _clear_link_state(request: Request) -> None:
    request.session.pop("link_user_id", None)
    request.session.pop("link_started_at", None)


@router.post("/link", dependencies=[Depends(_enabled), Depends(require_csrf)])
@limiter.limit("5/minute")
async def link(
    request: Request,
    password: str = Form(""),
    totp_code: str = Form(""),
    db: Session = Depends(get_db),
):
    found = _password_session_user(request, db)
    if not found:
        return _fail("link_requires_login")
    user, hh_id = found
    _clear_link_state(request)
    if is_locked(user):
        return RedirectResponse("/settings?passkey_error=1", status_code=302)
    # Fresh credentials every time; never say which factor was wrong.
    password_ok = verify_password_constant_time(password, user.password_hash)
    totp_ok = bool(user.totp_secret) and verify_totp(db, user, totp_code.strip())
    if not (password_ok and totp_ok):
        register_failed_login(db, user)
        security_logger.warning("OIDC link refused: bad credentials")
        if password_ok:
            # Same signal as the login path: someone knows the password.
            alert_failed_second_factor(db, request, user, hh_id)
        return RedirectResponse("/settings?passkey_error=1", status_code=302)
    clear_failed_logins(db, user)
    request.session["link_user_id"] = user.id
    request.session["link_started_at"] = int(time.time())
    # prompt=login makes Pocket ID run a fresh passkey ceremony.
    try:
        return await oidc_client().authorize_redirect(
            request, _callback_url(request), prompt="login"
        )
    except _PROVIDER_ERRORS as exc:
        security_logger.warning("OIDC provider unreachable: %s", type(exc).__name__)
        _clear_link_state(request)
        return RedirectResponse("/settings?passkey_error=1", status_code=302)


@router.post("/unlink", dependencies=[Depends(_enabled), Depends(require_csrf)])
@limiter.limit("20/minute")
async def unlink(request: Request, db: Session = Depends(get_db)):
    found = _password_session_user(request, db)
    if not found:
        # Back to Settings (where the form lives), not into the new app.
        return RedirectResponse("/settings?passkey_error=1", status_code=302)
    user, hh_id = found
    user.oidc_subject = None
    # Sessions opened with the passkey must not outlive it: bump session_version
    # (which also revokes API refresh tokens), then re-issue THIS browser's
    # session so the person unlinking stays signed in. Personal ingest tokens
    # (the Apple Pay Shortcut) are deliberately left alone.
    invalidate_user_sessions(db, user)
    db.commit()
    security_logger.info("OIDC passkey unlinked")
    response = RedirectResponse("/settings?passkey=unlinked", status_code=302)
    set_session(response, user.id, hh_id, user.session_version, amr="pwd")
    return response


@router.get("/login", dependencies=[Depends(_enabled)])
@limiter.limit("20/minute")
async def login(request: Request):
    _clear_link_state(request)
    # prompt=login: a sign-out on a shared device must not be undone by Pocket ID's
    # own session silently signing the next person straight back in.
    try:
        return await oidc_client().authorize_redirect(
            request, _callback_url(request), prompt="login"
        )
    except _PROVIDER_ERRORS as exc:
        security_logger.warning("OIDC provider unreachable: %s", type(exc).__name__)
        return _fail("provider")


@router.get("/callback", dependencies=[Depends(_enabled)])
@limiter.limit("20/minute")
async def callback(request: Request, db: Session = Depends(get_db)):
    # Always consume link state first, so an abandoned or failed link flow can
    # never turn a later sign-in in this browser into a link.
    link_user_id = request.session.pop("link_user_id", None)
    link_started_at = request.session.pop("link_started_at", None)
    if request.query_params.get("error"):
        return _fail("denied")
    try:
        token = await oidc_client().authorize_access_token(request)
    except OAuthError as exc:
        security_logger.warning("OIDC callback rejected: %s", type(exc).__name__)
        return _fail("state")
    except JoseError as exc:
        security_logger.warning("OIDC ID token rejected: %s", type(exc).__name__)
        return _fail("token")
    except httpx.HTTPError as exc:
        security_logger.warning("OIDC provider unreachable: %s", type(exc).__name__)
        return _fail("provider")
    claims = token.get("userinfo") or {}

    if link_user_id:
        found = _password_session_user(request, db)
        user, hh_id = found if found else (None, None)
        fresh = (
            isinstance(link_started_at, int)
            and 0 <= time.time() - link_started_at <= LINK_MAX_AGE_SECONDS
        )
        if not user or user.id != link_user_id or not fresh:
            return _fail("link_requires_login")
        try:
            link_oidc_subject(db, user, claims.get("sub"))
        except IdentityError as exc:
            security_logger.warning("OIDC link refused: %s", exc.code)
            return _fail(exc.code)
        security_logger.info("OIDC passkey linked")
        alert_passkey_linked(db, request, user, hh_id)
        return RedirectResponse("/app/?linked=1", status_code=302)

    try:
        user = resolve_oidc_user(db, claims)
    except IdentityError as exc:
        security_logger.warning("OIDC sign-in refused: %s", exc.code)
        return _fail(exc.code)
    member = (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id)
        .order_by(HouseholdMember.joined_at.asc())
        .first()
    )
    if not member:
        security_logger.warning("OIDC sign-in refused: no_household")
        return _fail("no_household")
    response = RedirectResponse("/app/", status_code=302)
    set_session(response, user.id, member.household_id, user.session_version, amr="oidc")
    alert_sign_in(db, request, user, member.household_id, method="a passkey", remedy=UNLINK_PASSKEY)
    return response


@router.post("/logout", dependencies=[Depends(_enabled)], status_code=204)
async def logout(request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    if session and not csrf_matches(request, session.get("user_id", "")):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    response = Response(status_code=204)
    clear_session(response)
    return response


DIST_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"

APP_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
    "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; "
    "manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)

spa = APIRouter(include_in_schema=False)


def _spa_enabled() -> None:
    if not settings.new_app_enabled:
        raise HTTPException(status_code=404)


def _file(rel: str) -> Path | None:
    if "\x00" in rel:
        return None
    try:
        root = DIST_DIR.resolve()
        target = (root / rel).resolve()
    except (ValueError, OSError):
        return None
    if root not in target.parents and target != root:
        return None
    return target if target.is_file() else None


@spa.api_route("/app", methods=["GET", "HEAD"], dependencies=[Depends(_spa_enabled)])
def app_root():
    return RedirectResponse("/app/", status_code=308)


@spa.api_route("/app/{path:path}", methods=["GET", "HEAD"], dependencies=[Depends(_spa_enabled)])
def app_files(path: str):
    if "\x00" in path:
        raise HTTPException(status_code=404)
    if path.startswith("auth/"):
        # The real auth routes are registered first and win on a matching method;
        # a GET reaching here for a POST-only route keeps its 405, anything else is a 404.
        known = {route.path for route in router.routes}
        raise HTTPException(status_code=405 if f"/app/{path}" in known else 404)
    found = _file(path) if path else None
    if found:
        immutable = path.startswith("assets/")
        return FileResponse(
            found,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"
            },
        )
    if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
        raise HTTPException(status_code=404)
    index = _file("index.html")
    if not index:
        raise HTTPException(status_code=404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})

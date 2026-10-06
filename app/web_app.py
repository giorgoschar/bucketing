"""The new app at /app: passkey sign-in via Pocket ID, and (Task 5) the SPA itself."""

import logging

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import COOKIE_NAME, clear_session, csrf_matches, decode_cookie, set_session
from app.core.config import settings
from app.core.database import get_db
from app.core.oidc import oidc_client
from app.core.ratelimit import limiter
from app.models import HouseholdMember
from app.services.identity import IdentityError, resolve_oidc_user

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


@router.get("/login", dependencies=[Depends(_enabled)])
@limiter.limit("20/minute")
async def login(request: Request):
    return await oidc_client().authorize_redirect(request, _callback_url(request))


@router.get("/callback", dependencies=[Depends(_enabled)])
@limiter.limit("20/minute")
async def callback(request: Request, db: Session = Depends(get_db)):
    if request.query_params.get("error"):
        return _fail("denied")
    try:
        token = await oidc_client().authorize_access_token(request)
    except OAuthError as exc:
        security_logger.warning("OIDC callback rejected: %s", type(exc).__name__)
        return _fail("state")
    claims = token.get("userinfo") or {}
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
        return _fail("no_household")
    response = RedirectResponse("/app/", status_code=302)
    set_session(response, user.id, member.household_id, user.session_version, amr="oidc")
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

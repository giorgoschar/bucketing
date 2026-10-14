"""API: join a household from an invite link, and household admin (switch, create, leave,
transfer ownership, reset a member's 2FA). The rules mirror app/routes/settings.py."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api_auth import _bearer, require_api_auth
from app.auth import COOKIE_NAME, current_iat, decode_cookie, security_logger, set_session
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.models import User
from app.services.households import HouseholdError, accept_invite, valid_invite

invites = APIRouter(prefix="/invites", tags=["invites"])


def _fail(e: HouseholdError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.detail)


def _follow(request: Request, response: Response, credentials, user: User, hh_id: str) -> None:
    """Point this browser's session cookie at `hh_id`, like the old switch/create/join do.
    Bearer clients carry their household in the token and are left alone."""
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    if credentials is None and session:
        set_session(
            response,
            user.id,
            hh_id,
            user.session_version,
            amr=session.get("amr", "pwd"),
            iat=current_iat(request),
        )


@invites.get("/{token}")
@limiter.limit("30/minute")
def preview_invite(request: Request, token: str, db: Session = Depends(get_db)):
    """What the invite link is for. Public (the link is the credential): household name and who sent it."""
    try:
        invite = valid_invite(db, token)
    except HouseholdError as e:
        raise _fail(e) from None
    inviter = invite.created_by_user
    return {
        "household_name": invite.household.name,
        "inviter": inviter.display_name if inviter else None,
    }


@invites.post("/{token}/accept")
@limiter.limit("10/minute")
def accept(
    request: Request,
    response: Response,
    token: str,
    auth=Depends(require_api_auth),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """The signed-in caller joins the invite's household as a member. The invite is burned."""
    user, _ = auth
    try:
        invite = accept_invite(db, user, token)
    except HouseholdError as e:
        raise _fail(e) from None
    security_logger.info(
        "Invite used: '%s' joined household %s (new app)", user.username, invite.household_id
    )
    _follow(request, response, credentials, user, invite.household_id)
    return {"household_id": invite.household_id, "household_name": invite.household.name}

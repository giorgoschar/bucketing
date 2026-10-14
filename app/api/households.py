"""API: join a household from an invite link, and household admin (switch, create, leave,
transfer ownership, reset a member's 2FA). The rules mirror app/routes/settings.py."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import _bearer, require_api_auth
from app.auth import (
    COOKIE_NAME,
    clear_session,
    current_iat,
    decode_cookie,
    security_logger,
    set_session,
)
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.models import Household, HouseholdMember, User
from app.services.households import (
    HouseholdError,
    accept_invite,
    create_household,
    leave_household,
    reset_member_2fa,
    transfer_ownership,
    valid_invite,
)

invites = APIRouter(prefix="/invites", tags=["invites"])


def cookie_only(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """Household changes are for the browser session, like the old cookie-only routes: a Bearer
    (mobile or personal) token can never move ownership, join, leave or switch."""
    if credentials is not None:
        raise HTTPException(status_code=403, detail="This is for the signed-in browser session.")


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


@invites.post("/{token}/accept", dependencies=[Depends(cookie_only)])
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


# ---------------------------------------------------------------------------
# Household admin (Settings › Household). Each route is the new-app twin of one in
# app/routes/settings.py and enforces the same role.
# ---------------------------------------------------------------------------

admin = APIRouter(prefix="/settings", tags=["settings"])


class SwitchIn(BaseModel):
    household_id: str


class CreateIn(BaseModel):
    name: str
    default_currency: str = "EUR"


class LeaveIn(BaseModel):
    confirm_name: str = ""


class ResetIn(BaseModel):
    owner_code: str


@admin.get("/households")
def list_households(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """The households the caller belongs to (archived ones are gone from their memberships)."""
    user, hh_id = auth
    rows = (
        db.query(Household, HouseholdMember.role)
        .join(HouseholdMember, HouseholdMember.household_id == Household.id)
        .filter(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.joined_at.asc())
        .all()
    )
    return [{"id": h.id, "name": h.name, "role": r.value, "active": h.id == hh_id} for h, r in rows]


@admin.post("/households/switch", dependencies=[Depends(cookie_only)])
def switch_household(
    request: Request,
    response: Response,
    body: SwitchIn,
    auth=Depends(require_api_auth),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Make another household of the caller's the active one for this browser session."""
    user, _ = auth
    if (
        not db.query(HouseholdMember)
        .filter_by(user_id=user.id, household_id=body.household_id)
        .first()
    ):
        raise HTTPException(status_code=403, detail="Not a member of that household")
    _follow(request, response, credentials, user, body.household_id)
    return {"household_id": body.household_id}


@admin.post("/households", status_code=status.HTTP_201_CREATED, dependencies=[Depends(cookie_only)])
def create_new_household(
    request: Request,
    response: Response,
    body: CreateIn,
    auth=Depends(require_api_auth),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Any signed-in user may start another household; they own it and it becomes active."""
    user, _ = auth
    try:
        household = create_household(db, user, body.name, body.default_currency)
    except HouseholdError as e:
        raise _fail(e) from None
    _follow(request, response, credentials, user, household.id)
    return {"household_id": household.id}


@admin.post("/household/leave", dependencies=[Depends(cookie_only)])
def leave(
    request: Request,
    response: Response,
    body: LeaveIn,
    auth=Depends(require_api_auth),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    try:
        nxt = leave_household(db, user, hh_id, body.confirm_name)
    except HouseholdError as e:
        raise _fail(e) from None
    security_logger.info("'%s' left household %s (new app)", user.username, hh_id)
    if nxt:
        _follow(request, response, credentials, user, nxt)
    elif credentials is None:
        clear_session(response)  # no household left: the old app sends them to /setup
    return {"household_id": nxt}


@admin.post(
    "/household/transfer-ownership/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(cookie_only)],
)
def transfer(member_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    try:
        transfer_ownership(db, user, hh_id, member_id)
    except HouseholdError as e:
        raise _fail(e) from None


@admin.post(
    "/household/members/{member_id}/reset-2fa",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(cookie_only)],
)
@limiter.limit("5/minute")
def reset_2fa(
    request: Request,
    member_id: str,
    body: ResetIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    try:
        reset_member_2fa(db, user, hh_id, member_id, body.owner_code)
    except HouseholdError as e:
        raise _fail(e) from None

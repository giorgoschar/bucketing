"""
Auth routes: login, logout, first-run setup wizard, invite join, 2FA verify, register.
"""
import json
from datetime import datetime, timedelta

import pyotp
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Household, HouseholdMember, Invitation, MemberRole
from app.auth import (
    hash_password, verify_password,
    set_session, set_pending_session, clear_session,
    get_current_session, get_pending_session,
    security_logger,
)
from app.config import settings
from app.seed import seed_categories
from app.templates import templates

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _is_first_run(db: Session) -> bool:
    return db.query(User).count() == 0


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    if _is_first_run(db):
        return RedirectResponse("/setup", status_code=302)
    session = get_current_session(request)
    if session and session.get("state") == "authenticated":
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# Setup wizard (first run only)
# ---------------------------------------------------------------------------

@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db)):
    if not _is_first_run(db) and not settings.allow_registration:
        return RedirectResponse("/login", status_code=302)
    if not _is_first_run(db):
        return RedirectResponse("/register", status_code=302)
    return templates.TemplateResponse("auth/setup.html", {"request": request})


@router.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    household_name: str = Form(...),
    display_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not _is_first_run(db):
        raise HTTPException(status_code=404)

    if len(password) < 12:
        return templates.TemplateResponse(
            "auth/setup.html",
            {"request": request, "error": "Password must be at least 12 characters."},
        )

    # Create household
    household = Household(name=household_name.strip())
    db.add(household)
    db.flush()

    # Create user
    user = User(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        avatar_color="#6366f1",
    )
    db.add(user)
    db.flush()

    # Add as owner
    db.add(HouseholdMember(
        household_id=household.id,
        user_id=user.id,
        role=MemberRole.owner,
    ))

    db.commit()
    seed_categories(db, household.id)

    security_logger.info("Setup: first user '%s' created from %s", user.username, _client_ip(request))

    # Must enroll TOTP before accessing the app
    response = RedirectResponse("/settings/2fa/enroll", status_code=302)
    set_pending_session(response, user.id, household.id, "2fa_enroll")
    return response


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if _is_first_run(db):
        return RedirectResponse("/setup", status_code=302)
    session = get_current_session(request)
    if session and session.get("state") == "authenticated":
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("10/15minutes")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    user = db.query(User).filter_by(username=username.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        security_logger.warning("Failed login for '%s' from %s", username.strip().lower(), ip)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid username or password."},
        )

    # Pick first household the user belongs to
    membership = db.query(HouseholdMember).filter_by(user_id=user.id).first()
    if not membership:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "You don't belong to any household. Ask for an invite."},
        )

    security_logger.info("Password OK for '%s' from %s — pending 2FA", user.username, ip)

    if user.totp_enabled:
        response = RedirectResponse("/login/verify", status_code=302)
        set_pending_session(response, user.id, membership.household_id, "2fa_pending")
    else:
        response = RedirectResponse("/settings/2fa/enroll", status_code=302)
        set_pending_session(response, user.id, membership.household_id, "2fa_enroll")

    return response


# ---------------------------------------------------------------------------
# 2FA Verify (TOTP code entry)
# ---------------------------------------------------------------------------

@router.get("/login/verify", response_class=HTMLResponse)
def verify_totp_page(request: Request):
    pending = get_pending_session(request)
    if not pending or pending.get("state") != "2fa_pending":
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("auth/verify_totp.html", {"request": request})


@router.post("/login/verify", response_class=HTMLResponse)
@limiter.limit("5/15minutes")
def verify_totp_submit(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    pending = get_pending_session(request)
    if not pending or pending.get("state") != "2fa_pending":
        return RedirectResponse("/login", status_code=302)

    user = db.get(User, pending["user_id"])
    if not user or not user.totp_enabled:
        return RedirectResponse("/login", status_code=302)

    totp = pyotp.TOTP(user.totp_secret)
    if totp.verify(code.strip(), valid_window=1):
        security_logger.info("2FA success for '%s' from %s", user.username, ip)
        response = RedirectResponse("/dashboard", status_code=302)
        set_session(response, user.id, pending["hh_id"], user.session_version)
        return response

    security_logger.warning("2FA failure for '%s' from %s", user.username, ip)
    return templates.TemplateResponse(
        "auth/verify_totp.html",
        {"request": request, "error": "Invalid code. Please try again."},
    )


@router.get("/login/verify/backup", response_class=HTMLResponse)
def verify_backup_page(request: Request):
    pending = get_pending_session(request)
    if not pending or pending.get("state") != "2fa_pending":
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("auth/verify_backup.html", {"request": request})


@router.post("/login/verify/backup", response_class=HTMLResponse)
@limiter.limit("5/15minutes")
def verify_backup_submit(
    request: Request,
    backup_code: str = Form(...),
    db: Session = Depends(get_db),
):
    import bcrypt as _bcrypt
    ip = _client_ip(request)
    pending = get_pending_session(request)
    if not pending or pending.get("state") != "2fa_pending":
        return RedirectResponse("/login", status_code=302)

    user = db.get(User, pending["user_id"])
    if not user or not user.totp_enabled or not user.totp_backup_codes:
        return RedirectResponse("/login", status_code=302)

    codes: list = json.loads(user.totp_backup_codes)
    code_input = backup_code.strip().encode()
    matched_index = None
    for i, hashed in enumerate(codes):
        try:
            if _bcrypt.checkpw(code_input, hashed.encode()):
                matched_index = i
                break
        except Exception:
            continue

    if matched_index is None:
        security_logger.warning("Backup code failure for '%s' from %s", user.username, ip)
        return templates.TemplateResponse(
            "auth/verify_backup.html",
            {"request": request, "error": "Invalid backup code."},
        )

    # Remove the used code
    codes.pop(matched_index)
    user.totp_backup_codes = json.dumps(codes)
    db.commit()

    security_logger.info("Backup code used for '%s' from %s (%d remaining)", user.username, ip, len(codes))
    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, pending["hh_id"], user.session_version)
    return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    clear_session(response)
    return response


# ---------------------------------------------------------------------------
# Household switcher
# ---------------------------------------------------------------------------

@router.post("/household/switch", response_class=HTMLResponse)
def switch_household(
    request: Request,
    household_id: str = Form(...),
    db: Session = Depends(get_db),
):
    session = get_current_session(request)
    if not session or session.get("state") != "authenticated":
        return RedirectResponse("/login", status_code=302)

    user = db.get(User, session["user_id"])
    membership = db.query(HouseholdMember).filter_by(
        user_id=user.id, household_id=household_id
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of that household")

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, household_id, user.session_version)
    return response


# ---------------------------------------------------------------------------
# Register (Mode B — coming soon or future full registration)
# ---------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if not settings.allow_registration:
        return templates.TemplateResponse("auth/register_soon.html", {"request": request})
    # Future: render full registration form
    return templates.TemplateResponse("auth/register_soon.html", {"request": request})


# ---------------------------------------------------------------------------
# Invite: join a household
# ---------------------------------------------------------------------------

@router.get("/join/{token}", response_class=HTMLResponse)
def join_page(token: str, request: Request, db: Session = Depends(get_db)):
    invite = db.query(Invitation).filter_by(token=token).first()
    if not invite or invite.used_at:
        return templates.TemplateResponse(
            "auth/invite_invalid.html", {"request": request}
        )
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        return templates.TemplateResponse(
            "auth/invite_invalid.html", {"request": request, "expired": True}
        )
    return templates.TemplateResponse(
        "auth/join.html",
        {"request": request, "invite": invite, "household": invite.household},
    )


@router.post("/join/{token}", response_class=HTMLResponse)
def join_submit(
    token: str,
    request: Request,
    display_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    invite = db.query(Invitation).filter_by(token=token).first()
    if not invite or invite.used_at:
        raise HTTPException(status_code=400, detail="Invalid invite")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite expired")

    if len(password) < 12:
        return templates.TemplateResponse(
            "auth/join.html",
            {
                "request": request,
                "invite": invite,
                "household": invite.household,
                "error": "Password must be at least 12 characters.",
            },
        )

    existing = db.query(User).filter_by(username=username.strip().lower()).first()
    if existing:
        return templates.TemplateResponse(
            "auth/join.html",
            {
                "request": request,
                "invite": invite,
                "household": invite.household,
                "error": "Username already taken.",
            },
        )

    user = User(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        avatar_color="#ec4899",
    )
    db.add(user)
    db.flush()

    db.add(HouseholdMember(
        household_id=invite.household_id,
        user_id=user.id,
        role=MemberRole.member,
    ))

    invite.used_at = datetime.utcnow()
    invite.used_by = user.id
    db.commit()

    security_logger.info("Invite used: '%s' joined household %s from %s", user.username, invite.household_id, ip)

    # New user must enroll TOTP before accessing the app
    response = RedirectResponse("/settings/2fa/enroll", status_code=302)
    set_pending_session(response, user.id, invite.household_id, "2fa_enroll")
    return response

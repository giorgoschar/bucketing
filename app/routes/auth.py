"""
Auth routes: login, logout, first-run setup wizard, invite join, 2FA verify, register.
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import (
    clear_device_cookie,
    clear_failed_logins,
    clear_session,
    get_current_session,
    get_pending_session,
    hash_password,
    invalidate_user_sessions,
    is_locked,
    log_id,
    register_failed_login,
    require_auth,
    require_csrf,
    security_logger,
    set_pending_session,
    set_session,
    verify_password_constant_time,
    verify_totp,
)
from app.core.clock import utcnow_naive
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.login_alerts import alert_failed_second_factor, alert_sign_in
from app.models import Household, HouseholdMember, Invitation, MemberRole, User
from app.seed import seed_categories
from app.templates import templates

router = APIRouter(dependencies=[Depends(require_csrf)])


def _is_first_run(db: Session) -> bool:
    return db.query(User).count() == 0


def _client_ip(request: Request) -> str:
    """Best-effort client IP for security logs.

    X-Forwarded-For is only honoured when TRUST_PROXY_HEADERS is set: any client
    can send that header, so trusting it unconditionally lets an attacker forge
    the source IP in the audit trail of every failed login.
    """
    if settings.trust_proxy_headers:
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
    email: str = Form(...),
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

    email_clean = email.strip().lower()
    if db.query(User).filter(User.email == email_clean).first():
        return templates.TemplateResponse(
            "auth/setup.html",
            {"request": request, "error": "That email is already registered."},
        )

    # Create household
    household = Household(name=household_name.strip())
    db.add(household)
    db.flush()

    # Create user
    user = User(
        username=username.strip().lower(),
        email=email_clean,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        avatar_color="#6366f1",
    )
    db.add(user)
    db.flush()

    # Add as owner
    db.add(
        HouseholdMember(
            household_id=household.id,
            user_id=user.id,
            role=MemberRole.owner,
        )
    )

    db.commit()
    seed_categories(db, household.id)

    security_logger.info(
        "Setup: first user '%s' created from %s", user.username, _client_ip(request)
    )

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
    identifier = username.strip().lower()
    user = db.query(User).filter(or_(User.username == identifier, User.email == identifier)).first()
    # Always run bcrypt, even for an unknown identifier, so response time does
    # not disclose which accounts exist.
    password_ok = verify_password_constant_time(password, user.password_hash if user else None)
    if is_locked(user):
        security_logger.warning("Login for locked account '%s' from %s", log_id(identifier), ip)
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=429,
        )
    if not password_ok:
        register_failed_login(db, user)
        security_logger.warning("Failed login for '%s' from %s", log_id(identifier), ip)
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

    if is_locked(user):
        return templates.TemplateResponse(
            "auth/verify_totp.html",
            {"request": request, "error": "Invalid code. Please try again."},
            status_code=429,
        )

    if verify_totp(db, user, code):
        clear_failed_logins(db, user)
        security_logger.info("2FA success for '%s' from %s", user.username, ip)
        response = RedirectResponse("/dashboard", status_code=302)
        set_session(response, user.id, pending["hh_id"], user.session_version)
        alert_sign_in(db, request, user, pending["hh_id"])
        return response

    register_failed_login(db, user)
    security_logger.warning("2FA failure for '%s' from %s", user.username, ip)
    alert_failed_second_factor(db, request, user, pending["hh_id"])
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

    if is_locked(user):
        return templates.TemplateResponse(
            "auth/verify_backup.html",
            {"request": request, "error": "Invalid backup code."},
            status_code=429,
        )

    codes: list = json.loads(user.totp_backup_codes)
    code_input = backup_code.strip().encode()
    matched_index = None
    for i, hashed in enumerate(codes):
        try:
            if _bcrypt.checkpw(code_input, hashed.encode()):
                matched_index = i
                break
        except (ValueError, TypeError):
            # A malformed stored hash must not block the remaining codes.
            security_logger.warning("Backup code check skipped: unusable hash at index %d", i)
            continue

    if matched_index is None:
        register_failed_login(db, user)
        security_logger.warning("Backup code failure for '%s' from %s", user.username, ip)
        alert_failed_second_factor(db, request, user, pending["hh_id"])
        return templates.TemplateResponse(
            "auth/verify_backup.html",
            {"request": request, "error": "Invalid backup code."},
        )

    # Remove the used code
    codes.pop(matched_index)
    user.totp_backup_codes = json.dumps(codes)
    db.commit()
    clear_failed_logins(db, user)

    security_logger.info(
        "Backup code used for '%s' from %s (%d remaining)", user.username, ip, len(codes)
    )
    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, pending["hh_id"], user.session_version)
    alert_sign_in(db, request, user, pending["hh_id"], method=f"a backup code ({len(codes)} left)")
    return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """Log out everywhere: bumping session_version kills every cookie and token
    this user holds (there is no per-device session table)."""
    session = get_current_session(request)
    if session and session.get("state") == "authenticated":
        user = db.get(User, session["user_id"])
        if user and session.get("sv", -1) == user.session_version:
            invalidate_user_sessions(db, user)
            db.commit()
            security_logger.info("Logout for '%s'", user.username)
    response = RedirectResponse("/login", status_code=302)
    clear_session(response)
    clear_device_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Household switcher
# ---------------------------------------------------------------------------


@router.post("/household/switch", response_class=HTMLResponse)
def switch_household(
    request: Request,
    household_id: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, _ = auth
    membership = (
        db.query(HouseholdMember).filter_by(user_id=user.id, household_id=household_id).first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of that household")

    response = RedirectResponse("/dashboard", status_code=302)
    amr = (get_current_session(request) or {}).get("amr", "pwd")
    set_session(response, user.id, household_id, user.session_version, amr=amr)
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
        return templates.TemplateResponse("auth/invite_invalid.html", {"request": request})
    if invite.expires_at and invite.expires_at < utcnow_naive():
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
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    invite = db.query(Invitation).filter_by(token=token).first()
    if not invite or invite.used_at:
        raise HTTPException(status_code=400, detail="Invalid invite")
    if invite.expires_at and invite.expires_at < utcnow_naive():
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

    email_clean = email.strip().lower()
    if db.query(User).filter(User.email == email_clean).first():
        return templates.TemplateResponse(
            "auth/join.html",
            {
                "request": request,
                "invite": invite,
                "household": invite.household,
                "error": "That email is already registered.",
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
        email=email_clean,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        avatar_color="#ec4899",
    )
    db.add(user)
    db.flush()

    db.add(
        HouseholdMember(
            household_id=invite.household_id,
            user_id=user.id,
            role=MemberRole.member,
        )
    )

    invite.used_at = utcnow_naive()
    invite.used_by = user.id
    db.commit()

    security_logger.info(
        "Invite used: '%s' joined household %s from %s", user.username, invite.household_id, ip
    )

    # New user must enroll TOTP before accessing the app
    response = RedirectResponse("/settings/2fa/enroll", status_code=302)
    set_pending_session(response, user.id, invite.household_id, "2fa_enroll")
    return response

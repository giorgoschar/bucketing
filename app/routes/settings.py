"""
Settings routes: household, members, invites, profile, categories, 2FA.
"""
import base64
import io
import json
import secrets
from datetime import datetime, timedelta
import uuid

import bcrypt as _bcrypt
import pyotp
import qrcode
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import (
    require_auth, require_pending_session,
    hash_password, verify_password,
    set_session, get_current_session,
    security_logger,
)
from app.config import settings
from app.models import (
    Household, HouseholdMember, User, Invitation, Category, MemberRole
)
from app.seed import seed_categories
from app.templates import templates

router = APIRouter(prefix="/settings")

AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444",
    "#f97316", "#f59e0b", "#10b981", "#06b6d4",
    "#3b82f6", "#84cc16",
]


def _ctx(db, user, hh_id):
    household = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]
    return {"household": household, "households": households}


@router.get("", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _ctx(db, user, hh_id)
    household = ctx["household"]

    members = (
        db.query(HouseholdMember)
        .filter_by(household_id=hh_id)
        .all()
    )
    invitations = (
        db.query(Invitation)
        .filter_by(household_id=hh_id)
        .filter(Invitation.used_at.is_(None))
        .all()
    )
    categories = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .order_by(Category.is_default.desc(), Category.name)
        .all()
    )

    # Check if current user is owner
    my_membership = db.query(HouseholdMember).filter_by(
        user_id=user.id, household_id=hh_id
    ).first()

    ctx.update({
        "request": request,
        "user": user,
        "members": members,
        "invitations": invitations,
        "categories": categories,
        "is_owner": my_membership and my_membership.role == MemberRole.owner,
        "avatar_colors": AVATAR_COLORS,
        "currencies": settings.currencies,
    })
    return templates.TemplateResponse("settings/index.html", ctx)


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------

@router.post("/household", response_class=HTMLResponse)
def update_household(
    name: str = Form(...),
    default_currency: str = Form("EUR"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    household = db.get(Household, hh_id)
    household.name = name.strip()
    household.default_currency = default_currency
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/household/new", response_class=HTMLResponse)
def create_household(
    request: Request,
    name: str = Form(...),
    default_currency: str = Form("EUR"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    household = Household(name=name.strip(), default_currency=default_currency)
    db.add(household)
    db.flush()
    db.add(HouseholdMember(
        household_id=household.id,
        user_id=user.id,
        role=MemberRole.owner,
    ))
    db.commit()
    seed_categories(db, household.id)

    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, household.id, user.session_version)
    return response


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.post("/profile", response_class=HTMLResponse)
def update_profile(
    display_name: str = Form(...),
    avatar_color: str = Form("#6366f1"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    user.display_name = display_name.strip()
    user.avatar_color = avatar_color
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/profile/password", response_class=HTMLResponse)
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    if not verify_password(current_password, user.password_hash):
        ctx = _ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "Current password is incorrect."})
        return templates.TemplateResponse("settings/index.html", ctx)
    if len(new_password) < 12:
        ctx = _ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "Password must be at least 12 characters."})
        return templates.TemplateResponse("settings/index.html", ctx)
    user.password_hash = hash_password(new_password)
    user.session_version = (user.session_version or 0) + 1
    db.commit()
    security_logger.info("Password changed for '%s'", user.username)
    return RedirectResponse("/settings?pw_changed=1", status_code=302)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.post("/invite", response_class=HTMLResponse)
def create_invite(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    invite = Invitation(
        household_id=hh_id,
        token=str(uuid.uuid4()),
        created_by=user.id,
        expires_at=datetime.utcnow() + timedelta(days=settings.invite_expiry_days),
    )
    db.add(invite)
    db.commit()

    invite_url = str(request.base_url) + f"join/{invite.token}"
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/invite_link.html",
            {"request": request, "invite_url": invite_url, "invite": invite},
        )
    return RedirectResponse("/settings", status_code=302)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.post("/categories", response_class=HTMLResponse)
def create_category(
    name: str = Form(...),
    color: str = Form("#6366f1"),
    icon: str = Form("📦"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    cat = Category(
        household_id=hh_id,
        name=name.strip(),
        color=color,
        icon=icon,
    )
    db.add(cat)
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/categories/{cat_id}/delete", response_class=HTMLResponse)
def delete_category(
    cat_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    cat = db.get(Category, cat_id)
    if not cat or cat.household_id != hh_id:
        raise HTTPException(status_code=404)
    db.delete(cat)
    db.commit()
    return RedirectResponse("/settings", status_code=302)


# ---------------------------------------------------------------------------
# 2FA — TOTP enroll
# ---------------------------------------------------------------------------

def _generate_qr_base64(totp_uri: str) -> str:
    img = qrcode.make(totp_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@router.get("/2fa/enroll", response_class=HTMLResponse)
def enroll_totp_page(request: Request, db: Session = Depends(get_db)):
    """Accessible with a pending 2fa_enroll session OR a full authenticated session (for re-enroll)."""
    pending = None
    user = None

    session = get_current_session(request)
    if session and session.get("state") == "authenticated":
        user = db.get(User, session["user_id"])
    else:
        from app.auth import get_pending_session
        pending = get_pending_session(request)
        if not pending or pending.get("state") != "2fa_enroll":
            return RedirectResponse("/login", status_code=302)
        user = db.get(User, pending["user_id"])

    if not user:
        return RedirectResponse("/login", status_code=302)

    if user.totp_enabled:
        return RedirectResponse("/settings", status_code=302)

    # Generate a fresh secret for this enroll attempt
    secret = pyotp.random_base32()
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.username, issuer_name=settings.app_name
    )
    qr_b64 = _generate_qr_base64(totp_uri)

    return templates.TemplateResponse(
        "auth/enroll_totp.html",
        {
            "request": request,
            "secret": secret,
            "qr_b64": qr_b64,
            "is_pending": pending is not None,
        },
    )


@router.post("/2fa/enroll", response_class=HTMLResponse)
def enroll_totp_submit(
    request: Request,
    secret: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    """Verify the TOTP code against the submitted secret and save."""
    from app.auth import get_pending_session

    pending = None
    user = None
    hh_id = None

    session = get_current_session(request)
    if session and session.get("state") == "authenticated":
        user = db.get(User, session["user_id"])
        hh_id = session["hh_id"]
    else:
        pending = get_pending_session(request)
        if not pending or pending.get("state") != "2fa_enroll":
            return RedirectResponse("/login", status_code=302)
        user = db.get(User, pending["user_id"])
        hh_id = pending["hh_id"]

    if not user:
        return RedirectResponse("/login", status_code=302)

    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        # Regenerate QR for the same secret so user can retry
        totp_uri = totp.provisioning_uri(name=user.username, issuer_name=settings.app_name)
        qr_b64 = _generate_qr_base64(totp_uri)
        return templates.TemplateResponse(
            "auth/enroll_totp.html",
            {
                "request": request,
                "secret": secret,
                "qr_b64": qr_b64,
                "is_pending": pending is not None,
                "error": "Invalid code. Please try again.",
            },
        )

    # Generate 8 one-time backup codes
    plain_codes = [secrets.token_hex(5).upper() for _ in range(8)]
    hashed_codes = [_bcrypt.hashpw(c.encode(), _bcrypt.gensalt()).decode() for c in plain_codes]

    user.totp_secret = secret
    user.totp_enabled = True
    user.totp_backup_codes = json.dumps(hashed_codes)
    db.commit()

    security_logger.info("TOTP enrolled for '%s'", user.username)

    # Upgrade to full session
    response = templates.TemplateResponse(
        "auth/backup_codes.html",
        {"request": request, "codes": plain_codes},
    )
    set_session(response, user.id, hh_id, user.session_version)
    return response


# ---------------------------------------------------------------------------
# 2FA — disable (self) and admin reset
# ---------------------------------------------------------------------------

@router.post("/2fa/disable", response_class=HTMLResponse)
def disable_totp(
    request: Request,
    current_password: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    if not verify_password(current_password, user.password_hash):
        ctx = _ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "totp_error": "Incorrect password."})
        return templates.TemplateResponse("settings/index.html", ctx)

    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(code.strip(), valid_window=1):
        ctx = _ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "totp_error": "Invalid authenticator code."})
        return templates.TemplateResponse("settings/index.html", ctx)

    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    user.session_version = (user.session_version or 0) + 1
    db.commit()

    security_logger.info("TOTP disabled for '%s'", user.username)
    response = RedirectResponse("/settings/2fa/enroll", status_code=302)
    from app.auth import set_pending_session
    set_pending_session(response, user.id, hh_id, "2fa_enroll")
    return response


@router.post("/2fa/reset/{member_id}", response_class=HTMLResponse)
def admin_reset_member_totp(
    member_id: str,
    request: Request,
    owner_code: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Household owner resets another member's TOTP. Requires owner's own TOTP code."""
    owner, hh_id = auth

    # Confirm requester is owner
    owner_membership = db.query(HouseholdMember).filter_by(
        user_id=owner.id, household_id=hh_id
    ).first()
    if not owner_membership or owner_membership.role != MemberRole.owner:
        raise HTTPException(status_code=403)

    # Verify owner's TOTP
    if not owner.totp_secret or not pyotp.TOTP(owner.totp_secret).verify(owner_code.strip(), valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid authenticator code.")

    # Confirm target is a member of this household
    target_membership = db.query(HouseholdMember).filter_by(
        user_id=member_id, household_id=hh_id
    ).first()
    if not target_membership:
        raise HTTPException(status_code=404)

    target_user = db.get(User, member_id)
    if not target_user:
        raise HTTPException(status_code=404)

    target_user.totp_secret = None
    target_user.totp_enabled = False
    target_user.totp_backup_codes = None
    target_user.session_version = (target_user.session_version or 0) + 1
    db.commit()

    security_logger.info(
        "Owner '%s' reset TOTP for member '%s' in household %s",
        owner.username, target_user.username, hh_id,
    )
    return RedirectResponse("/settings", status_code=302)

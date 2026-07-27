"""
Settings routes: household, members, invites, profile, categories, 2FA.
"""
import base64
import io
import json
import secrets
from datetime import datetime, timedelta

import bcrypt as _bcrypt
import pyotp
import qrcode
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.auth import (
    require_auth, require_pending_session, require_csrf,
    hash_password, verify_password,
    set_session, clear_session, get_current_session,
    security_logger,
)
from app.config import settings
from app.models import (
    Household, HouseholdMember, User, Invitation, Category, MemberRole
)
from app.category_rules import learn_rule, list_rules
from app.models import CategoryRule
from app.seed import seed_categories
from app.services import base_ctx
from app.templates import templates

from app.ratelimit import limiter

router = APIRouter(prefix="/settings", dependencies=[Depends(require_csrf)])

AVATAR_COLORS = [
    "#6366f1", "#8b5cf6", "#ec4899", "#ef4444",
    "#f97316", "#f59e0b", "#10b981", "#06b6d4",
    "#3b82f6", "#84cc16",
]


def _require_owner(db: Session, user_id: str, hh_id: str) -> HouseholdMember:
    """Assert the user owns this household, or raise 403."""
    membership = db.query(HouseholdMember).filter_by(user_id=user_id, household_id=hh_id).first()
    if not membership or membership.role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="Only the household owner can do that.")
    return membership


@router.get("", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = base_ctx(db, user, hh_id)
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
        "category_rules": list_rules(db, hh_id),
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
    # Matches the API, which has always been owner-only. The HTML route let any
    # member rename the household and switch its currency.
    _require_owner(db, user.id, hh_id)
    if default_currency not in settings.currencies:
        raise HTTPException(status_code=400, detail="Unsupported currency.")
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
    request: Request,
    display_name: str = Form(...),
    email: str = Form(default=""),
    avatar_color: str = Form("#6366f1"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    email_clean = email.strip().lower() or None
    if email_clean:
        conflict = db.query(User).filter(
            User.email == email_clean, User.id != user.id
        ).first()
        if conflict:
            ctx = base_ctx(db, user, hh_id)
            members = db.query(HouseholdMember).filter_by(household_id=hh_id).all()
            invitations = db.query(Invitation).filter_by(household_id=hh_id).filter(Invitation.used_at.is_(None)).all()
            categories = db.query(Category).filter_by(household_id=hh_id).order_by(Category.is_default.desc(), Category.name).all()
            my_membership = db.query(HouseholdMember).filter_by(user_id=user.id, household_id=hh_id).first()
            ctx.update({
                "request": request,
                "user": user,
                "members": members,
                "invitations": invitations,
                "categories": categories,
                "is_owner": my_membership and my_membership.role == MemberRole.owner,
                "avatar_colors": AVATAR_COLORS,
                "currencies": settings.currencies,
                "profile_error": "That email is already registered to another account.",
            })
            return templates.TemplateResponse("settings/index.html", ctx)
    user.display_name = display_name.strip()
    user.email = email_clean
    user.avatar_color = avatar_color
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/profile/password", response_class=HTMLResponse)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    if not verify_password(current_password, user.password_hash):
        ctx = base_ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "Current password is incorrect."})
        return templates.TemplateResponse("settings/index.html", ctx)
    if len(new_password) < 12:
        ctx = base_ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "Password must be at least 12 characters."})
        return templates.TemplateResponse("settings/index.html", ctx)
    if verify_password(new_password, user.password_hash):
        ctx = base_ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "New password must differ from the current one."})
        return templates.TemplateResponse("settings/index.html", ctx)

    user.password_hash = hash_password(new_password)
    user.session_version = (user.session_version or 0) + 1
    db.commit()
    security_logger.info("Password changed for '%s'", user.username)

    # Bumping session_version invalidates every existing cookie, including the
    # one this request arrived on — without re-issuing it the user was bounced
    # to /login immediately after a successful password change. Other devices
    # still get logged out, which is the point.
    response = RedirectResponse("/settings?pw_changed=1", status_code=302)
    set_session(response, user.id, hh_id, user.session_version)
    return response


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@router.post("/invite", response_class=HTMLResponse)
@limiter.limit("10/hour")
def create_invite(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    invite = Invitation(
        household_id=hh_id,
        token=secrets.token_urlsafe(32),
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
    if cat.is_default:
        # The API already refuses this; the HTML route did not.
        raise HTTPException(status_code=400, detail="Cannot delete a default category.")

    # transactions.category_id and recurring_bills.category_id are plain FKs
    # with no ON DELETE rule. Deleting a category that is still referenced
    # raises an IntegrityError on Postgres (and now on SQLite too, since foreign
    # keys are enforced). Detach the references first.
    from app.models import RecurringBill, Transaction
    db.query(Transaction).filter_by(category_id=cat_id).update(
        {"category_id": None}, synchronize_session=False
    )
    db.query(RecurringBill).filter_by(category_id=cat_id).update(
        {"category_id": None}, synchronize_session=False
    )
    db.delete(cat)
    db.commit()
    return RedirectResponse("/settings", status_code=302)


# ---------------------------------------------------------------------------
# 2FA — TOTP enroll
# ---------------------------------------------------------------------------

def _pending_secret(db: Session, user: User) -> str:
    """Return the user's in-progress TOTP secret, creating one if needed.

    A secret stored while totp_enabled is False is an enrollment in progress:
    it grants nothing until a valid code confirms it.
    """
    if not user.totp_secret:
        user.totp_secret = pyotp.random_base32()
        db.commit()
    return user.totp_secret


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

    # The secret is held server-side (totp_secret set, totp_enabled still False)
    # rather than round-tripped through a hidden form field, so the client never
    # gets to choose which secret the account ends up with. Reusing a pending
    # secret also means a page reload or the back button keeps showing the same
    # QR code the user already scanned.
    secret = _pending_secret(db, user)

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
@limiter.limit("10/minute")
def enroll_totp_submit(
    request: Request,
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    """Verify the TOTP code against the server-held pending secret and save.

    The secret is deliberately NOT read from the request: it lives on the user
    row (with totp_enabled=False) from the moment the QR code is rendered.
    """
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

    # Enrollment can only ever move a user from "no 2FA" to "2FA". Without this
    # check, anyone holding a session cookie could silently re-enroll a secret
    # they control (and mint fresh backup codes) without knowing the password or
    # the current TOTP code — a complete 2FA bypass. Rotating an existing secret
    # goes through /settings/2fa/disable, which demands both.
    if user.totp_enabled:
        security_logger.warning(
            "Rejected TOTP re-enrollment attempt for already-enrolled user '%s'", user.username
        )
        return RedirectResponse("/settings", status_code=302)

    secret = user.totp_secret
    if not secret:
        # No enrollment in progress (e.g. a stale form) — start a fresh one.
        return RedirectResponse("/settings/2fa/enroll", status_code=302)

    totp = pyotp.TOTP(secret)
    if not totp.verify(code.strip(), valid_window=1):
        # Re-render the QR for the same secret so the user can retry
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

    # secret is already on the row; confirming it is what flips enrollment on.
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
@limiter.limit("5/minute")
def disable_totp(
    request: Request,
    current_password: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    if not verify_password(current_password, user.password_hash):
        ctx = base_ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "totp_error": "Incorrect password."})
        return templates.TemplateResponse("settings/index.html", ctx)

    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(code.strip(), valid_window=1):
        ctx = base_ctx(db, user, hh_id)
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
@limiter.limit("5/minute")
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


# ---------------------------------------------------------------------------
# Member management (owner only): remove member + transfer ownership
# ---------------------------------------------------------------------------

@router.post("/remove-member/{member_id}", response_class=HTMLResponse)
def remove_member(
    member_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Owner removes a member from the household. All their data stays."""
    owner, hh_id = auth

    owner_membership = db.query(HouseholdMember).filter_by(
        user_id=owner.id, household_id=hh_id
    ).first()
    if not owner_membership or owner_membership.role != MemberRole.owner:
        raise HTTPException(status_code=403)

    if member_id == owner.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself.")

    target_membership = db.query(HouseholdMember).filter_by(
        user_id=member_id, household_id=hh_id
    ).first()
    if not target_membership:
        raise HTTPException(status_code=404)

    if target_membership.role == MemberRole.owner:
        raise HTTPException(status_code=400, detail="Cannot remove another owner. Transfer ownership first.")

    db.delete(target_membership)
    db.commit()

    security_logger.info(
        "Owner '%s' removed member '%s' from household %s",
        owner.username, member_id, hh_id,
    )
    return RedirectResponse("/settings", status_code=302)


@router.post("/transfer-ownership/{member_id}", response_class=HTMLResponse)
def transfer_ownership(
    member_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Transfer household ownership from the current owner to another member."""
    owner, hh_id = auth

    owner_membership = db.query(HouseholdMember).filter_by(
        user_id=owner.id, household_id=hh_id
    ).first()
    if not owner_membership or owner_membership.role != MemberRole.owner:
        raise HTTPException(status_code=403)

    if member_id == owner.id:
        raise HTTPException(status_code=400, detail="Already the owner.")

    target_membership = db.query(HouseholdMember).filter_by(
        user_id=member_id, household_id=hh_id
    ).first()
    if not target_membership:
        raise HTTPException(status_code=404)

    owner_membership.role = MemberRole.member
    target_membership.role = MemberRole.owner
    db.commit()

    target_user = db.get(User, member_id)
    security_logger.info(
        "Ownership of household %s transferred from '%s' to '%s'",
        hh_id, owner.username, target_user.username if target_user else member_id,
    )
    return RedirectResponse("/settings", status_code=302)


# ---------------------------------------------------------------------------
# Leave household
# ---------------------------------------------------------------------------

@router.post("/leave-household", response_class=HTMLResponse)
def leave_household(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    my_membership = db.query(HouseholdMember).filter_by(
        user_id=user.id, household_id=hh_id
    ).first()
    if not my_membership:
        raise HTTPException(status_code=404)

    # Block owners from leaving if other members remain
    if my_membership.role == MemberRole.owner:
        other_members = db.query(HouseholdMember).filter(
            HouseholdMember.household_id == hh_id,
            HouseholdMember.user_id != user.id,
        ).count()
        if other_members > 0:
            ctx = base_ctx(db, user, hh_id)
            ctx.update({
                "request": request,
                "user": user,
                "leave_error": "You are the owner. Use the ··· menu next to each member to transfer ownership or remove them before leaving.",
            })
            # Re-render settings with error
            members = db.query(HouseholdMember).filter_by(household_id=hh_id).all()
            invitations = db.query(Invitation).filter_by(household_id=hh_id).filter(Invitation.used_at.is_(None)).all()
            categories = db.query(Category).filter_by(household_id=hh_id).order_by(Category.is_default.desc(), Category.name).all()
            ctx.update({
                "members": members,
                "invitations": invitations,
                "categories": categories,
                "is_owner": True,
                "avatar_colors": AVATAR_COLORS,
                "currencies": settings.currencies,
            })
            return templates.TemplateResponse("settings/index.html", ctx)

    household = db.get(Household, hh_id)
    is_sole_member = db.query(HouseholdMember).filter_by(household_id=hh_id).count() == 1

    # Remove membership
    db.delete(my_membership)

    if is_sole_member:
        # Delete the empty household
        db.delete(household)

    db.commit()

    # Find another household for the user
    remaining = db.query(HouseholdMember).filter_by(user_id=user.id).first()

    if remaining:
        remaining_hh = db.get(Household, remaining.household_id)
        response = RedirectResponse("/settings", status_code=302)
        set_session(response, user.id, remaining.household_id, user.session_version)
        return response

    # No households left — redirect to setup (the route is /setup, not /auth/setup)
    response = RedirectResponse("/setup", status_code=302)
    clear_session(response)
    return response


# ---------------------------------------------------------------------------
# Categorisation rules
# ---------------------------------------------------------------------------

@router.post("/category-rules", response_class=HTMLResponse)
def create_category_rule(
    pattern: str = Form(...),
    category_id: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Add a "merchant contains X -> category Y" rule."""
    user, hh_id = auth
    rule = learn_rule(db, hh_id, pattern, category_id, created_by=user.id)
    if rule is None:
        raise HTTPException(
            status_code=400,
            detail="Enter at least 2 characters and pick a category from this household.",
        )
    db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/category-rules/{rule_id}/delete", response_class=HTMLResponse)
def delete_category_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    rule = db.get(CategoryRule, rule_id)
    if not rule or rule.household_id != hh_id:
        raise HTTPException(status_code=404)
    db.delete(rule)
    db.commit()
    return RedirectResponse("/settings", status_code=302)

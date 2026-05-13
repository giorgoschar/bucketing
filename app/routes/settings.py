"""
Settings routes: household, members, invites, profile, categories.
"""
from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth, hash_password
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
        "currencies": ["EUR", "USD", "GBP", "CHF", "JPY", "AUD", "CAD"],
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

    from app.auth import set_session
    response = RedirectResponse("/dashboard", status_code=302)
    set_session(response, user.id, household.id)
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
    from app.auth import verify_password
    user, hh_id = auth
    if not verify_password(current_password, user.password_hash):
        ctx = _ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "Current password is incorrect."})
        return templates.TemplateResponse("settings/index.html", ctx)
    if len(new_password) < 6:
        ctx = _ctx(db, user, hh_id)
        ctx.update({"request": request, "user": user, "pw_error": "Password must be at least 6 characters."})
        return templates.TemplateResponse("settings/index.html", ctx)
    user.password_hash = hash_password(new_password)
    db.commit()
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
        expires_at=datetime.utcnow() + timedelta(days=7),
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

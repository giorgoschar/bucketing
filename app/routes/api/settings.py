"""
API settings routes — profile, household, members, categories.
"""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.auth import verify_password, hash_password, security_logger
from app.database import get_db
from app.models import (
    User, Household, HouseholdMember, Invitation, Category, MemberRole,
)
from app.config import settings
from app.seed import seed_categories

router = APIRouter(prefix="/settings", tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProfileIn(BaseModel):
    display_name: str
    email:        str | None = None
    avatar_color: str        = "#6366f1"


class PasswordIn(BaseModel):
    current_password: str
    new_password:     str


class HouseholdIn(BaseModel):
    name:             str
    default_currency: str = "EUR"


class CategoryIn(BaseModel):
    name:  str
    color: str = "#6366f1"
    icon:  str = "📦"


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile")
def get_profile(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return {
        "id":           user.id,
        "username":     user.username,
        "display_name": user.display_name,
        "email":        user.email,
        "avatar_color": user.avatar_color,
        "totp_enabled": user.totp_enabled,
        "household_id": hh_id,
    }


@router.put("/profile")
def update_profile(
    body: ProfileIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    email_clean = body.email.strip().lower() if body.email else None
    if email_clean:
        conflict = db.query(User).filter(User.email == email_clean, User.id != user.id).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Email already registered to another account")
    user.display_name = body.display_name.strip()
    user.email        = email_clean
    user.avatar_color = body.avatar_color
    db.commit()
    return {"id": user.id, "display_name": user.display_name, "email": user.email, "avatar_color": user.avatar_color}


@router.post("/profile/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters")
    user.password_hash   = hash_password(body.new_password)
    user.session_version = (user.session_version or 0) + 1  # invalidates all existing tokens
    db.commit()
    security_logger.info("API password changed for '%s'", user.username)


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------

@router.get("/household")
def get_household(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    household = db.get(Household, hh_id)
    members   = db.query(HouseholdMember).filter_by(household_id=hh_id).all()

    def _member(m: HouseholdMember):
        u = db.get(User, m.user_id)
        return {
            "user_id":      m.user_id,
            "role":         m.role.value,
            "joined_at":    m.joined_at.isoformat() if m.joined_at else None,
            "display_name": u.display_name if u else None,
            "username":     u.username     if u else None,
            "avatar_color": u.avatar_color if u else None,
        }

    return {
        "id":               household.id,
        "name":             household.name,
        "default_currency": household.default_currency,
        "members":          [_member(m) for m in members],
    }


@router.put("/household")
def update_household(
    body: HouseholdIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    my_membership = db.query(HouseholdMember).filter_by(user_id=user.id, household_id=hh_id).first()
    if not my_membership or my_membership.role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="Only the household owner can update household settings")
    household = db.get(Household, hh_id)
    household.name             = body.name.strip()
    household.default_currency = body.default_currency
    db.commit()
    return {"id": household.id, "name": household.name, "default_currency": household.default_currency}


@router.post("/household/invite")
def create_invite(
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Generate a single-use invite token (expires in `invite_expiry_days` days)."""
    user, hh_id = auth
    expires_at = datetime.utcnow() + timedelta(days=settings.invite_expiry_days)
    invitation = Invitation(
        household_id=hh_id,
        created_by=user.id,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    return {
        "token":      invitation.token,
        "expires_at": invitation.expires_at.isoformat(),
    }


@router.delete("/household/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_user_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    my_membership = db.query(HouseholdMember).filter_by(user_id=user.id, household_id=hh_id).first()
    if not my_membership or my_membership.role != MemberRole.owner:
        raise HTTPException(status_code=403, detail="Only the owner can remove members")
    if member_user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    membership = db.query(HouseholdMember).filter_by(user_id=member_user_id, household_id=hh_id).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(membership)
    db.commit()


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

@router.get("/categories")
def list_categories(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    cats = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .order_by(Category.is_default.desc(), Category.name)
        .all()
    )
    return [
        {"id": c.id, "name": c.name, "color": c.color, "icon": c.icon, "is_default": c.is_default}
        for c in cats
    ]


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    cat = Category(household_id=hh_id, name=body.name.strip(), color=body.color, icon=body.icon)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "color": cat.color, "icon": cat.icon, "is_default": cat.is_default}


@router.put("/categories/{category_id}")
def update_category(
    category_id: str,
    body: CategoryIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    cat = db.query(Category).filter_by(id=category_id, household_id=hh_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.name  = body.name.strip()
    cat.color = body.color
    cat.icon  = body.icon
    db.commit()
    return {"id": cat.id, "name": cat.name, "color": cat.color, "icon": cat.icon, "is_default": cat.is_default}


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    cat = db.query(Category).filter_by(id=category_id, household_id=hh_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if cat.is_default:
        raise HTTPException(status_code=400, detail="Cannot delete a default category")

    # Detach references first — category_id FKs have no ON DELETE rule, so a
    # referenced category cannot be deleted outright.
    from app.models import RecurringBill, Transaction
    db.query(Transaction).filter_by(category_id=category_id).update(
        {"category_id": None}, synchronize_session=False
    )
    db.query(RecurringBill).filter_by(category_id=category_id).update(
        {"category_id": None}, synchronize_session=False
    )
    db.delete(cat)
    db.commit()

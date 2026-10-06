"""
Template context shared by every page.
"""

from sqlalchemy.orm import Session

from app.models import (
    FUEL_SYSTEM_KEY,
    Bucket,
    BucketStatus,
    Category,
    Household,
    HouseholdMember,
    User,
)


def base_ctx(db: Session, user, hh_id: str) -> dict:
    """Minimal context shared by every page: current household + switcher list."""
    household = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]
    households = [h for h in households if h is not None and h.archived_at is None]
    return {"household": household, "households": households}


def full_ctx(db: Session, user, hh_id: str) -> dict:
    """Extended context including members, categories and active buckets."""
    ctx = base_ctx(db, user, hh_id)
    ctx["members"] = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .all()
    )
    ctx["categories"] = db.query(Category).filter_by(household_id=hh_id).all()
    # Picking this category unlocks the price per litre in the expense forms.
    ctx["fuel_category_id"] = next(
        (c.id for c in ctx["categories"] if c.system_key == FUEL_SYSTEM_KEY), ""
    )
    ctx["buckets"] = (
        db.query(Bucket).filter_by(household_id=hh_id, status=BucketStatus.active).all()
    )
    return ctx

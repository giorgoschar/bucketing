"""
Seed system-default categories into a household.
Called after household creation.

Two kinds: the editable defaults (SYSTEM_CATEGORIES) and the built-in ones the
app relies on (SYSTEM_KEYED_CATEGORIES, ``Category.system_key`` set, locked).
"""
from sqlalchemy.orm import Session

from app.models import FUEL_SYSTEM_KEY, Category

SYSTEM_CATEGORIES = [
    {"name": "Food & Groceries",   "color": "#f59e0b", "icon": "🛒"},
    {"name": "Eating Out",         "color": "#ef4444", "icon": "🍽️"},
    {"name": "Transport",          "color": "#3b82f6", "icon": "🚗"},
    {"name": "Housing & Rent",     "color": "#8b5cf6", "icon": "🏠"},
    {"name": "Utilities",          "color": "#06b6d4", "icon": "💡"},
    {"name": "Health",             "color": "#10b981", "icon": "💊"},
    {"name": "Entertainment",      "color": "#f97316", "icon": "🎬"},
    {"name": "Travel",             "color": "#6366f1", "icon": "✈️"},
    {"name": "Shopping",           "color": "#ec4899", "icon": "🛍️"},
    {"name": "Subscriptions",      "color": "#14b8a6", "icon": "📺"},
    {"name": "Education",          "color": "#84cc16", "icon": "📚"},
    {"name": "Personal Care",      "color": "#a78bfa", "icon": "🧴"},
    {"name": "Savings",            "color": "#22c55e", "icon": "🏦"},
    {"name": "Income",             "color": "#4ade80", "icon": "💰"},
    {"name": "Other",              "color": "#9ca3af", "icon": "📦"},
]


# Built-in categories: exactly one per household, found by system_key.
SYSTEM_KEYED_CATEGORIES = [
    {"system_key": FUEL_SYSTEM_KEY, "name": "Fuel", "color": "#ea580c", "icon": "⛽"},
]

# Names (lowercased) of a category a household may already keep fuel under,
# most preferred first. Such a category becomes the built-in one instead of
# getting a twin; the migration that introduced system_key uses the same list.
# No "gas": it is as often the natural-gas utility, and an adopted category is
# locked for good.
FUEL_LIKE_NAMES = (
    "fuel", "καύσιμα", "καυσιμα",
    "petrol", "gasoline", "diesel", "βενζίνη", "βενζινη",
)


def ensure_system_categories(db: Session, household_id: str) -> None:
    """Give the household each built-in category, adopting a fuel-like one
    it already has (see FUEL_LIKE_NAMES). Idempotent; the caller commits."""
    cats = db.query(Category).filter_by(household_id=household_id).all()
    keyed = {c.system_key for c in cats if c.system_key}
    for spec in SYSTEM_KEYED_CATEGORIES:
        if spec["system_key"] in keyed:
            continue
        adopt = None
        if spec["system_key"] == FUEL_SYSTEM_KEY:
            adopt = min(
                (c for c in cats
                 if not c.system_key and c.name.strip().lower() in FUEL_LIKE_NAMES),
                key=lambda c: (FUEL_LIKE_NAMES.index(c.name.strip().lower()), c.name, c.id),
                default=None,
            )
        if adopt is not None:
            adopt.system_key = spec["system_key"]
        else:
            db.add(Category(household_id=household_id, is_default=True, **spec))
    db.flush()


def seed_categories(db: Session, household_id: str):
    for cat in SYSTEM_CATEGORIES:
        exists = (
            db.query(Category)
            .filter_by(household_id=household_id, name=cat["name"])
            .first()
        )
        if not exists:
            db.add(Category(
                household_id=household_id,
                name=cat["name"],
                color=cat["color"],
                icon=cat["icon"],
                is_default=True,
            ))
    ensure_system_categories(db, household_id)
    db.commit()

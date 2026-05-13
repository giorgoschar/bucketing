"""
Seed system-default categories into a household.
Called after household creation.
"""
from sqlalchemy.orm import Session
from app.models import Category

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
    db.commit()

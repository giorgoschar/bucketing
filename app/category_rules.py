"""
User-defined categorisation rules.

Resolution order when categorising a scanned receipt:

  1. Household rules  — "merchant contains LIDL" → Groceries
  2. Built-in keywords — the Greek/English list in receipt_parser
  3. Fuzzy name match  — hint against category names

Rules win because they are the household's own correction of the guess, and
they can be learned: fixing a category once teaches the rule for next time.
"""
import logging
import unicodedata

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Category, CategoryRule

logger = logging.getLogger(__name__)

MAX_PATTERN_LENGTH = 200
MIN_PATTERN_LENGTH = 2


def fold(text: str | None) -> str:
    """Case-fold, strip accents, and normalise Greek final sigma.

    Two Greek-specific hazards this avoids:

      * "ΣΚΛΑΒΕΝΙΤΗΣ".lower() ends in the final sigma "ς", while the same word
        typed mid-sentence ends in "σ" — the two would not match as substrings.
      * OCR on thermal receipts is unreliable about accents, so "ΚΑΦΕ" and
        "ΚΑΦΈ" must fold together.
    """
    if not text:
        return ""
    lowered = unicodedata.normalize("NFD", str(text).casefold())
    stripped = "".join(c for c in lowered if not unicodedata.combining(c))
    return " ".join(stripped.replace("ς", "σ").split())


def normalise_pattern(text: str | None) -> str | None:
    """Fold a pattern for storage, or None if it is not usable."""
    cleaned = fold(text)
    if len(cleaned) < MIN_PATTERN_LENGTH:
        return None
    return cleaned[:MAX_PATTERN_LENGTH]


def apply_rules(db: Session, household_id: str, *texts: str | None) -> str | None:
    """Return the category id of the first rule matching any given text.

    Longer patterns win: "lidl express" is more specific than "lidl", so a
    household can special-case without deleting the general rule.
    """
    # Haystacks fold the same way patterns do, or a stored pattern would
    # never match text that differs only by accent or final sigma.
    haystacks = [fold(t) for t in texts if t]
    if not haystacks:
        return None

    rules = (
        db.query(CategoryRule)
        .filter(CategoryRule.household_id == household_id)
        .all()
    )
    if not rules:
        return None

    best = None
    for rule in sorted(rules, key=lambda r: -len(r.pattern)):
        if any(rule.pattern in hay for hay in haystacks):
            best = rule
            break
    if best is None:
        return None

    best.match_count = (best.match_count or 0) + 1
    return best.category_id


def learn_rule(
    db: Session,
    household_id: str,
    pattern: str | None,
    category_id: str,
    *,
    created_by: str | None = None,
) -> CategoryRule | None:
    """Teach (or re-point) a rule. Returns None when the pattern is unusable.

    Caller commits. An existing rule for the same pattern is updated rather
    than duplicated, so re-categorising the same merchant corrects the rule.
    """
    cleaned = normalise_pattern(pattern)
    if not cleaned or not category_id:
        return None

    category = db.get(Category, category_id)
    if not category or category.household_id != household_id:
        # Never let a rule point at another household's category.
        return None

    existing = (
        db.query(CategoryRule)
        .filter(
            CategoryRule.household_id == household_id,
            CategoryRule.pattern == cleaned,
        )
        .first()
    )
    if existing:
        existing.category_id = category_id
        return existing

    rule = CategoryRule(
        household_id=household_id,
        pattern=cleaned,
        category_id=category_id,
        created_by=created_by,
    )
    try:
        with db.begin_nested():
            db.add(rule)
            db.flush()
    except IntegrityError:
        # Raced with another writer; the other row is equally valid.
        return (
            db.query(CategoryRule)
            .filter(
                CategoryRule.household_id == household_id,
                CategoryRule.pattern == cleaned,
            )
            .first()
        )
    return rule


def list_rules(db: Session, household_id: str) -> list[CategoryRule]:
    """Rules for a household, most-used first."""
    return (
        db.query(CategoryRule)
        .filter(CategoryRule.household_id == household_id)
        .order_by(CategoryRule.match_count.desc(), CategoryRule.pattern)
        .all()
    )


def resolve_category(
    db: Session,
    household_id: str,
    *,
    merchant: str | None,
    hint: str | None,
    raw_text: str | None = None,
) -> str | None:
    """Full resolution chain: household rules, then the built-in guess."""
    from app.receipt_parser import match_category

    matched = apply_rules(db, household_id, merchant, raw_text)
    if matched:
        return matched

    categories = db.query(Category).filter_by(household_id=household_id).all()
    return match_category(hint, categories)

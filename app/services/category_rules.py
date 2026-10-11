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

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow_naive
from app.models import (
    Category,
    CategoryRule,
    CategoryRuleDismissal,
    Transaction,
    TransactionType,
)

logger = logging.getLogger(__name__)

MAX_PATTERN_LENGTH = 200
MIN_PATTERN_LENGTH = 2
# "Not now" this many times and a pattern is never offered again (spec §3.1).
MAX_DISMISSALS = 2
# Entries with this merchant and category that make a rule worth offering.
SUGGEST_AFTER = 2


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


def _best_rule(rules: list[CategoryRule], haystacks: list[str]) -> CategoryRule | None:
    """The longest rule pattern found in any (already folded) haystack."""
    for rule in sorted(rules, key=lambda r: -len(r.pattern)):
        if any(rule.pattern in hay for hay in haystacks):
            return rule
    return None


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

    rules = db.query(CategoryRule).filter(CategoryRule.household_id == household_id).all()
    best = _best_rule(rules, haystacks)
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

    clear_dismissal(db, household_id, cleaned)

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
    from app.services.receipt_parser import match_category

    matched = apply_rules(db, household_id, merchant, raw_text)
    if matched:
        return matched

    categories = db.query(Category).filter_by(household_id=household_id).all()
    return match_category(hint, categories)


def clear_dismissal(db: Session, household_id: str, pattern: str) -> None:
    """Forget "Not now" for a folded pattern: it now has a rule. Caller commits."""
    db.query(CategoryRuleDismissal).filter_by(household_id=household_id, pattern=pattern).delete(
        synchronize_session=False
    )


def dismiss_suggestion(db: Session, household_id: str, pattern: str) -> int:
    """Count one more "Not now" for a folded pattern; returns the new total.
    Caller commits. The increment is one UPDATE, so two taps cannot lose one."""
    where = (
        CategoryRuleDismissal.household_id == household_id,
        CategoryRuleDismissal.pattern == pattern,
    )
    bump = update(CategoryRuleDismissal).where(*where).values(
        times=CategoryRuleDismissal.times + 1, updated_at=utcnow_naive()
    )
    if db.execute(bump).rowcount == 0:
        try:
            with db.begin_nested():
                db.add(
                    CategoryRuleDismissal(
                        household_id=household_id, pattern=pattern, times=1, updated_at=utcnow_naive()
                    )
                )
                db.flush()
        except IntegrityError:
            db.execute(bump)  # raced with another first tap
    return db.query(CategoryRuleDismissal.times).filter(*where).scalar() or 0


def suggest_rule(db: Session, txn: Transaction) -> dict | None:
    """The rule to offer after ``txn`` was saved, or None (spec §3.1)."""
    pattern = normalise_pattern(txn.merchant)
    if txn.type != TransactionType.expense or not pattern or not txn.category_id:
        return None
    hh = txn.household_id

    # A rule already sends this merchant to this category: nothing to teach.
    rules = db.query(CategoryRule).filter(CategoryRule.household_id == hh).all()
    best = _best_rule(rules, [fold(txn.merchant)])
    if best is not None and best.category_id == txn.category_id:
        return None

    dismissed = (
        db.query(CategoryRuleDismissal.times).filter_by(household_id=hh, pattern=pattern).scalar()
    )
    if dismissed is not None and dismissed >= MAX_DISMISSALS:
        return None

    # Entries (this one included) with the same folded merchant and category.
    # Folding is not SQL, so group by the raw spelling and fold the groups.
    groups = (
        db.query(Transaction.merchant, func.count(Transaction.id))
        .filter(
            Transaction.household_id == hh,
            Transaction.active(),
            Transaction.type == TransactionType.expense,
            Transaction.category_id == txn.category_id,
            Transaction.merchant.isnot(None),
        )
        .group_by(Transaction.merchant)
        .all()
    )
    seen = sum(n for merchant, n in groups if normalise_pattern(merchant) == pattern)
    if seen < SUGGEST_AFTER:
        return None

    category = db.get(Category, txn.category_id)
    return {
        "pattern": pattern,
        "label": txn.merchant.strip(),
        "category_id": txn.category_id,
        "category_name": category.name if category else "",
    }

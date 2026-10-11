"""/api/v1/settings/category-rules: the household's "merchant contains X →
category" rules (2d spec §7.4).

2d owns this API. 2b's composer reads the list (to match merchants as the
server does) and POSTs to remember a merchant; POST is an upsert by folded
pattern, so a queued or repeated POST is harmless. The old form routes in
app/routes/settings.py keep working on the same table.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.models import Category, CategoryRule, Transaction
from app.services.category_rules import (
    clear_dismissal,
    dismiss_suggestion,
    learn_rule,
    list_rules,
    normalise_pattern,
    suggest_rule,
)

router = APIRouter(prefix="/settings/category-rules", tags=["settings"])
# Phase C spec §3.1: the suggestion lives beside, not under, Settings.
suggestion_router = APIRouter(prefix="/category-rules", tags=["settings"])

INVALID_RULE_MSG = "Enter at least 2 characters and pick a category from this household."
PATTERN_TAKEN_MSG = "Another rule already uses this pattern."


class CategoryRuleIn(BaseModel):
    pattern: str
    category_id: str


class CategoryRuleOut(BaseModel):
    id: str
    pattern: str  # as stored: folded (case, accents, final sigma)
    category_id: str
    match_count: int
    created_at: datetime | None


def _out(rule: CategoryRule) -> CategoryRuleOut:
    return CategoryRuleOut(
        id=rule.id,
        pattern=rule.pattern,
        category_id=rule.category_id,
        match_count=rule.match_count or 0,
        created_at=rule.created_at,
    )


def _validated(db: Session, hh_id: str, body: CategoryRuleIn) -> tuple[str, str]:
    """(folded pattern, category id), or 400 with the one message the spec gives."""
    pattern = normalise_pattern(body.pattern)
    category = db.get(Category, body.category_id) if body.category_id else None
    if not pattern or category is None or category.household_id != hh_id:
        raise HTTPException(status_code=400, detail=INVALID_RULE_MSG)
    return pattern, category.id


def _by_pattern(db: Session, hh_id: str, pattern: str) -> CategoryRule | None:
    return db.query(CategoryRule).filter_by(household_id=hh_id, pattern=pattern).first()


def _rule_or_404(db: Session, rule_id: str, hh_id: str) -> CategoryRule:
    rule = db.get(CategoryRule, rule_id)
    if rule is None or rule.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.get("", response_model=list[CategoryRuleOut])
def list_category_rules(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """The household's rules, most used first."""
    user, hh_id = auth
    return [_out(r) for r in list_rules(db, hh_id)]


@router.post(
    "",
    response_model=CategoryRuleOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": CategoryRuleOut, "description": "The pattern had a rule; re-pointed"}
    },
)
def upsert_category_rule(
    body: CategoryRuleIn,
    response: Response,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Teach a rule, or re-point the one with the same folded pattern (kept
    match_count). 201 when new, 200 when it existed."""
    user, hh_id = auth
    pattern, category_id = _validated(db, hh_id, body)
    existed = _by_pattern(db, hh_id, pattern) is not None
    rule = learn_rule(db, hh_id, pattern, category_id, created_by=user.id)
    if rule is None:  # _validated already ruled this out
        raise HTTPException(status_code=400, detail=INVALID_RULE_MSG)
    try:
        db.commit()
    except IntegrityError:
        # Another request inserted this pattern between our check and our
        # commit: it is the same upsert, so re-point that rule and answer 200.
        db.rollback()
        rule = _by_pattern(db, hh_id, pattern)
        if rule is None:  # the winner was deleted meanwhile; let the client retry
            raise HTTPException(status_code=409, detail=PATTERN_TAKEN_MSG) from None
        rule.category_id = category_id
        db.commit()
        existed = True
    db.refresh(rule)
    if existed:
        response.status_code = status.HTTP_200_OK
    return _out(rule)


@router.put("/{rule_id}", response_model=CategoryRuleOut)
def update_category_rule(
    rule_id: str,
    body: CategoryRuleIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Edit a rule's pattern and category; match_count is kept. A pattern
    another rule already folds to is a 409 (no silent merge on edit)."""
    user, hh_id = auth
    rule = _rule_or_404(db, rule_id, hh_id)
    pattern, category_id = _validated(db, hh_id, body)
    other = _by_pattern(db, hh_id, pattern)
    if other is not None and other.id != rule.id:
        raise HTTPException(status_code=409, detail=PATTERN_TAKEN_MSG)
    rule.pattern = pattern
    rule.category_id = category_id
    clear_dismissal(db, hh_id, pattern)
    try:
        db.commit()
    except IntegrityError:
        # Another request took this pattern between the check and the commit.
        db.rollback()
        raise HTTPException(status_code=409, detail=PATTERN_TAKEN_MSG) from None
    db.refresh(rule)
    return _out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category_rule(
    rule_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    user, hh_id = auth
    db.delete(_rule_or_404(db, rule_id, hh_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class RuleSuggestionOut(BaseModel):
    pattern: str  # folded, as a rule would store it
    label: str  # the merchant as typed on this entry
    category_id: str
    category_name: str


class DismissIn(BaseModel):
    pattern: str


class DismissOut(BaseModel):
    pattern: str
    times: int


@suggestion_router.get("/suggestion", response_model=RuleSuggestionOut | None)
def rule_suggestion(
    transaction_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Whether to offer "always use this category for this merchant" after the
    entry was saved: a suggestion, or null. Another household's entry is 404."""
    user, hh_id = auth
    txn = db.get(Transaction, transaction_id)
    if txn is None or txn.household_id != hh_id or txn.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return suggest_rule(db, txn)


@suggestion_router.post("/suggestion/dismiss", response_model=DismissOut)
def dismiss_rule_suggestion(
    body: DismissIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    """"Not now": one more dismissal for this pattern (two stop the offer)."""
    user, hh_id = auth
    pattern = normalise_pattern(body.pattern)
    if not pattern:
        raise HTTPException(status_code=400, detail="Enter at least 2 characters.")
    times = dismiss_suggestion(db, hh_id, pattern)
    db.commit()
    return DismissOut(pattern=pattern, times=times)

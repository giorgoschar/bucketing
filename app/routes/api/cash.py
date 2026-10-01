"""
API cash ledger routes: movements (list/add/delete) and the monthly summary.

Movements are in the household currency (no FX source for cash): a different
``currency`` is rejected. Members manage only their own movements; the owner
may log or delete for anyone in the household.
"""
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.clock import local_today
from app.database import get_db
from app.models import CashMovement, Household
from app.money import quantize
from app.schemas import _checked
from app.services import (
    add_movement,
    can_manage_for,
    cash_comparison,
    delete_movement,
    list_movements,
    member_balances,
    parse_month,
)
from app.validators import household_member_ids, parse_amount, require_category, require_member

router = APIRouter(prefix="/cash", tags=["cash"])


class MovementIn(BaseModel):
    kind: Literal["in", "out"]
    amount: Decimal
    movement_date: date | None = None  # blank means today
    currency: str | None = None        # must equal the household currency if given
    category_id: str | None = None
    note: str | None = None
    user_id: str | None = None         # defaults to the caller; owner may set others

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> Decimal:
        return _checked(parse_amount, v, field="Amount")

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if len(v) > 500:
            raise ValueError("Note must be at most 500 characters.")
        return v or None


def _dict(m: CashMovement) -> dict:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "kind": m.kind,
        "amount": quantize(m.amount),
        "currency": m.currency,
        "category_id": m.category_id,
        "note": m.note,
        "movement_date": m.movement_date.isoformat() if m.movement_date else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/movements")
def get_movements(
    member_id: str | None = Query(default=None),
    month: str | None = Query(default=None, description="YYYY-MM; omit for all time"),
    limit: int = Query(100, ge=1, le=500),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    start = end = None
    if month:
        try:
            start, end, _ = parse_month(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    require_member(db, member_id, hh_id)
    items = list_movements(db, hh_id, member_id=member_id, start=start, end=end, limit=limit)
    return {
        "items": [_dict(m) for m in items],
        "balances": {uid: quantize(v) for uid, v in member_balances(db, hh_id).items()},
    }


@router.post("/movements", status_code=status.HTTP_201_CREATED)
def create_movement(
    body: MovementIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    household = db.get(Household, hh_id)
    currency = household.default_currency
    if body.currency and body.currency.upper() != currency:
        raise HTTPException(
            status_code=400,
            detail=f"Cash is tracked in the household currency ({currency}).",
        )
    target = body.user_id or user.id
    if target not in household_member_ids(db, hh_id):
        raise HTTPException(status_code=400, detail="That person is not a member of this household.")
    if not can_manage_for(db, user.id, hh_id, target):
        raise HTTPException(status_code=403, detail="Only the owner can log cash for another member.")
    category_id = require_category(db, body.category_id, hh_id)
    mv = add_movement(
        db, hh_id, target, body.kind, body.amount, currency,
        body.movement_date or local_today(), category_id, body.note,
    )
    return _dict(mv)


@router.delete("/movements/{movement_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_movement(
    movement_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    mv = (
        db.query(CashMovement)
        .filter(CashMovement.id == movement_id, CashMovement.household_id == hh_id,
                CashMovement.active())
        .first()
    )
    if not mv:
        raise HTTPException(status_code=404, detail="Cash movement not found")
    if not can_manage_for(db, user.id, hh_id, mv.user_id):
        raise HTTPException(status_code=403, detail="You can only delete your own cash movements.")
    delete_movement(db, mv)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary")
def summary(
    month: str | None = Query(default=None, description="YYYY-MM; default current month"),
    member_id: str | None = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    try:
        start, end, norm = parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    target = require_member(db, member_id, hh_id) or user.id
    comparison = cash_comparison(db, hh_id, target, start, end)
    return {
        "month": norm,
        "member_id": target,
        "balances": {uid: quantize(v) for uid, v in member_balances(db, hh_id).items()},
        "comparison": {k: quantize(v) for k, v in comparison.items()},
    }

"""
API cash routes: your movements (list/add/delete), your stash and the
monthly wallet summary.

Movements are in the household currency (no FX source for cash): a different
``currency`` is rejected. Everyone logs and deletes only their own movements.
A stash is its owner's alone: its balance and history are only ever returned
to them (with other members' takes from it); others may take from it without
seeing either, and a take bigger than it holds is refused without saying how
much is there. Household owners get no special access. See app.services.cash
for the model.

Responses are typed (``*Out`` below). Money is a JSON number, as it was before
the models (``planning_models.Money``); ``/summary`` keeps its older shape: a
``labelled_out`` term, and no ``put_back`` key at all on another member's
wallet (``/wallets`` sends it as null instead).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ValidationError, ValidationInfo, field_validator, model_validator
from sqlalchemy.orm import Session

from app.api.planning_models import Money
from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.core.money import quantize
from app.models import CashMovement, Household, HouseholdMember, User
from app.schemas import _checked
from app.services import (
    delete_own_movement,
    list_movements,
    parse_month,
    record_movement,
    record_stash_count,
    stash_balance,
    wallet_summaries,
    wallet_summary,
    withdraw_and_spend,
)
from app.services.cash import FROM_BANK, FROM_STASH, STASH_COUNT, TAKE
from app.validators import (
    parse_amount,
    require_bucket,
    require_category,
    require_member,
)

router = APIRouter(prefix="/cash", tags=["cash"])


class MovementIn(BaseModel):
    # ``stash_count``: a recount of your own stash; ``amount`` is what you
    # counted (0 or more) and the server stores the signed correction.
    kind: Literal["stash_in", "take", "put_back", "still_have", "stash_count"]
    amount: Decimal
    movement_date: date | None = None  # blank means today
    currency: str | None = None  # must equal the household currency if given
    note: str | None = None
    # A take only: whose stash it comes out of (any member's, yours
    # included); null takes it from the bank (an ATM).
    stash_owner_id: str | None = None
    # A take only, from your own stash or the bank: also log the cash expense
    # in this bucket, with category_id and note as its category/notes.
    spend_bucket_id: str | None = None
    category_id: str | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any, info: ValidationInfo) -> Decimal:
        kind = info.data.get("kind")
        if kind == STASH_COUNT:
            try:
                negative = Decimal(str(v).strip().replace(",", ".")) < 0
            except (ArithmeticError, ValueError, TypeError):
                negative = False  # parse_amount below says what is wrong
            if negative:
                raise ValueError("Count can't be negative")
        # An empty wallet is a valid "still have"; an empty stash a valid count.
        return _checked(
            parse_amount, v, field="Amount", allow_zero=kind in ("still_have", STASH_COUNT)
        )

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if len(v) > 500:
            raise ValueError("Note must be at most 500 characters.")
        return v or None

    @model_validator(mode="after")
    def _count_is_plain(self) -> "MovementIn":
        if self.kind == STASH_COUNT and (
            self.stash_owner_id or self.spend_bucket_id or self.category_id
        ):
            raise ValueError("A stash count is just the amount you counted.")
        return self


CashKindName = Literal["stash_in", "take", "put_back", "still_have", "out", "stash_count"]


class CashMovementOut(BaseModel):
    id: str
    user_id: str
    # ``out`` is legacy (read only); a ``stash_count`` amount is the signed
    # correction, so it may be negative or zero.
    kind: CashKindName
    stash_owner_id: str | None
    amount: Money
    currency: str
    category_id: str | None
    note: str | None
    movement_date: date
    transaction_id: str | None
    created_at: str | None  # ISO, naive UTC
    # Only ever true on another member's take from the viewer's stash.
    deleted: bool


class CashMovementsOut(BaseModel):
    items: list[CashMovementOut]
    stash: Money  # the viewer's own


class WalletOut(BaseModel):
    """A member's wallet for a month (app.services.cash.wallet_summaries).
    For anyone but the member, ``taken`` is net of put backs and
    ``put_back`` is null."""

    carried: Money
    taken: Money
    put_back: Money | None
    still_have: Money | None  # null: none entered
    spent: Money
    logged: Money
    outs: Money
    not_yet_logged: Money


class SummaryWalletOut(WalletOut):
    """``/summary``'s wallet, in its pre-model shape: plus ``labelled_out``,
    and ``put_back`` left out altogether (not null) for another member."""

    put_back: Money | None = None
    labelled_out: Money


class CashSummaryOut(BaseModel):
    month: str  # YYYY-MM
    member_id: str
    stash: Money  # the viewer's own
    wallet: SummaryWalletOut


class CashWalletMemberOut(BaseModel):
    member_id: str
    name: str
    is_me: bool
    wallet: WalletOut


class CashWalletsOut(BaseModel):
    month: str  # YYYY-MM
    stash: Money  # the viewer's own
    members: list[CashWalletMemberOut]


def _dict(m: CashMovement) -> dict:
    return {
        "id": m.id,
        "user_id": m.user_id,
        "kind": m.kind,
        "stash_owner_id": m.stash_owner_id,
        "amount": quantize(m.amount),
        "currency": m.currency,
        "category_id": m.category_id,
        "note": m.note,
        "movement_date": m.movement_date.isoformat() if m.movement_date else None,
        "transaction_id": m.transaction_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        # Only ever set on another member's take from the viewer's stash.
        "deleted": m.deleted_at is not None,
    }


@router.get("/movements", response_model=CashMovementsOut)
def get_movements(
    member_id: str | None = Query(default=None),
    month: str | None = Query(default=None, description="YYYY-MM; omit for all time"),
    limit: int = Query(100, ge=1, le=500),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Your movements and other members' takes from your stash (``member_id``
    narrows them to one member's), plus your stash balance."""
    user, hh_id = auth
    start = end = None
    if month:
        try:
            start, end, _ = parse_month(month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    require_member(db, member_id, hh_id)
    items = list_movements(
        db, hh_id, user.id, member_id=member_id, start=start, end=end, limit=limit
    )
    return {
        "items": [_dict(m) for m in items],
        "stash": stash_balance(db, hh_id, user.id),
    }


@router.post("/movements", status_code=status.HTTP_201_CREATED, response_model=CashMovementOut)
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
    when = body.movement_date or local_today()
    if body.kind == STASH_COUNT:
        mv = record_stash_count(
            db,
            household_id=hh_id,
            actor_id=user.id,
            counted=body.amount,
            when=when,
            note=body.note,
            currency=currency,
        )
        return _dict(mv)
    if body.spend_bucket_id:
        if body.kind != TAKE or body.stash_owner_id not in (None, user.id):
            raise HTTPException(
                status_code=400,
                detail="Spending it straight away is a take from your own stash or the bank.",
            )
        bucket = require_bucket(db, body.spend_bucket_id, hh_id)
        try:
            txn = withdraw_and_spend(
                db,
                user=user,
                household_id=hh_id,
                bucket=bucket,
                amount=body.amount,
                source=FROM_STASH if body.stash_owner_id else FROM_BANK,
                when=when,
                category_id=require_category(db, body.category_id, hh_id),
                notes=body.note,
                currency=currency,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from None
        mv = (
            db.query(CashMovement)
            .filter(CashMovement.transaction_id == txn.id, CashMovement.active())
            .one()
        )
        return _dict(mv)
    mv = record_movement(
        db,
        household_id=hh_id,
        actor_id=user.id,
        kind=body.kind,
        amount=body.amount,
        currency=currency,
        when=when,
        note=body.note,
        stash_owner_id=body.stash_owner_id,
    )
    return _dict(mv)


@router.delete("/movements/{movement_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_movement(
    movement_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    delete_own_movement(db, hh_id, user.id, movement_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _month_or_400(month: str | None) -> tuple[date, date, str]:
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


# exclude_unset: another member's wallet has no put_back key (not null).
@router.get("/summary", response_model=CashSummaryOut, response_model_exclude_unset=True)
def summary(
    month: str | None = Query(default=None, description="YYYY-MM; default current month"),
    member_id: str | None = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """A member's wallet for the month (anyone's: it is household-visible)
    and your own stash balance."""
    user, hh_id = auth
    start, end, norm = _month_or_400(month)
    target = require_member(db, member_id, hh_id) or user.id
    wallet = wallet_summary(db, hh_id, target, start, end, viewer_id=user.id)
    return {
        "month": norm,
        "member_id": target,
        "stash": stash_balance(db, hh_id, user.id),
        "wallet": {k: (quantize(v) if v is not None else None) for k, v in wallet.items()},
    }


@router.get("/wallets", response_model=CashWalletsOut)
def wallets(
    month: str | None = Query(default=None, description="YYYY-MM; default current month"),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Every household member's wallet for the month (household-visible):
    you first, then the others by name; plus your own stash balance."""
    user, hh_id = auth
    start, end, norm = _month_or_400(month)
    # The same members and names as the cash page's (services.context.full_ctx).
    members = (
        db.query(User.id, User.display_name)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .all()
    )
    members.sort(key=lambda m: (m.id != user.id, (m.display_name or "").casefold(), m.id))
    found = wallet_summaries(db, hh_id, [m.id for m in members], start, end, viewer_id=user.id)
    rows = []
    for m in members:
        wallet = dict(found[m.id])
        wallet.setdefault("put_back", None)  # someone else's: stash activity
        rows.append(
            {
                "member_id": m.id,
                "name": m.display_name or "",
                "is_me": m.id == user.id,
                "wallet": {k: (quantize(v) if v is not None else None) for k, v in wallet.items()},
            }
        )
    return {"month": norm, "stash": stash_balance(db, hh_id, user.id), "members": rows}

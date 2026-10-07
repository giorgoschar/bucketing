"""
/api/v1/recurring — recurring items (in and out) on schedule rules, and their
expected entries (spec §3, §6.3). The new app's only way to change them.
"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.planning_models import EntryOut, RecurringItemOut
from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.core.schedule import MAX_INTERVAL_MONTHS, MAX_INTERVAL_WEEKS, RuleError, validate_rule
from app.models import (
    BillOccurrence,
    BucketKind,
    ItemDirection,
    PayerMode,
    RecurringBill,
    RecurringBillSplit,
    default_payment_method,
)
from app.schemas import parse_payer_mode
from app.services.bills import (
    BILL_HAS_HISTORY_MSG,
    PAST_NONE,
    EntryStateError,
    bill_has_payment_history,
    complete_entry,
    delete_future_occurrences,
    generate_occurrences,
    horizon_end,
    item_rule,
    set_entry_amount,
    skip_entry,
    undo_occurrence,
)
from app.services.planning import entry_for, list_entries
from app.validators import (
    check_split_sum,
    parse_amount,
    payment_method_or_400,
    require_bucket,
    require_category,
    require_member,
    validate_currency,
    validate_split_users,
)

router = APIRouter(prefix="/recurring", tags=["recurring"])

MAX_RANGE_DAYS = 400


class SplitIn(BaseModel):
    user_id: str
    amount: Decimal


class RecurringItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    direction: str = ItemDirection.out.value
    amount: Decimal | None = None  # None: variable
    currency: str = "EUR"
    category_id: str | None = None
    bucket_id: str | None = None  # out items only; a monthly bucket
    rule_kind: str = "monthly_day"
    interval_months: int = 1
    rule_day: int | None = None
    rule_month: int | None = None
    rule_adjust: str = "none"
    rule_days: int | None = None
    rule_weekday: int | None = None
    rule_interval_weeks: int | None = None
    start_date: date
    end_date: date | None = None
    total_occurrences: int | None = Field(default=None, ge=1)
    contract_end_date: date | None = None
    paid_by_default: str | None = None  # in items: received by
    payer_mode: str = PayerMode.single.value
    is_auto_pay: bool = False
    is_active: bool = True
    notes: str | None = None
    splits: list[SplitIn] = []
    payment_method: str | None = None  # None: create → by direction; update → unchanged

    @field_validator("payer_mode", mode="before")
    @classmethod
    def _payer_mode(cls, v):
        return parse_payer_mode(v)


class EntryDoneIn(BaseModel):
    amount: Decimal | None = None
    person: str | None = None  # payer (out) or recipient (in); None: the item's default
    payment_method: str | None = None  # None: the item's


class EntryUndoIn(BaseModel):
    delete_transaction: bool = False


class EntryAmountIn(BaseModel):
    amount: Decimal


def _apply(db: Session, item: RecurringBill, body: RecurringItemIn, hh_id: str) -> None:
    """Validate ``body`` against the household and copy it onto ``item``."""
    try:
        direction = ItemDirection(body.direction).value
    except ValueError:
        raise HTTPException(status_code=400, detail="direction must be 'out' or 'in'.") from None
    income = direction == ItemDirection.in_.value
    method = payment_method_or_400(body.payment_method)
    if method is not None:
        item.payment_method = method
    elif not item.id or direction != item.direction:
        # New item, or it changed direction: that direction's default.
        item.payment_method = default_payment_method(direction)
    if income and (body.bucket_id or body.is_auto_pay or body.splits):
        raise HTTPException(status_code=400, detail="Income has no bucket, auto-pay or shares.")
    if income and body.payer_mode != PayerMode.single.value:
        raise HTTPException(status_code=400, detail="Income has one recipient.")
    bucket = require_bucket(db, body.bucket_id, hh_id, optional=True)
    if bucket is not None and bucket.kind != BucketKind.monthly.value:
        raise HTTPException(
            status_code=400, detail="A recurring item can use a monthly bucket only."
        )
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="The end date is before the start date.")
    if not 1 <= body.interval_months <= MAX_INTERVAL_MONTHS:
        raise HTTPException(
            status_code=400, detail=f"The interval must be 1 to {MAX_INTERVAL_MONTHS} months."
        )
    if body.rule_interval_weeks is not None and not (
        1 <= body.rule_interval_weeks <= MAX_INTERVAL_WEEKS
    ):
        raise HTTPException(
            status_code=400, detail=f"The interval must be 1 to {MAX_INTERVAL_WEEKS} weeks."
        )
    amount = parse_amount(body.amount, field="Amount", allow_blank=True)
    split_amounts = [parse_amount(s.amount, field="Split amount") for s in body.splits]
    if body.splits:
        ids = [s.user_id for s in body.splits]
        if len(set(ids)) != len(ids):
            raise HTTPException(status_code=400, detail="A member can have one share only.")
        validate_split_users(ids, hh_id, db)
        check_split_sum(split_amounts, amount)
    if body.payer_mode == PayerMode.own_share.value and not body.splits:
        raise HTTPException(
            status_code=400, detail="payer_mode own_share needs splits (each member's share)."
        )
    currency = validate_currency(body.currency)
    if item.id and (direction != item.direction or currency != (item.currency or "EUR")):
        if bill_has_payment_history(db, item.id):
            raise HTTPException(
                status_code=409,
                detail="This item has payments, so its direction and currency can't change.",
            )
    item.direction = direction
    item.name = body.name.strip()
    item.amount = amount
    item.currency = currency
    item.category_id = require_category(db, body.category_id, hh_id)
    item.bucket_id = bucket.id if bucket else None
    item.rule_kind = body.rule_kind
    item.interval_months = body.interval_months
    item.rule_day = body.rule_day
    item.rule_month = body.rule_month
    item.rule_adjust = body.rule_adjust
    item.rule_days = body.rule_days
    item.rule_weekday = body.rule_weekday
    item.rule_interval_weeks = body.rule_interval_weeks
    try:
        validate_rule(item_rule(item))
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    item.start_date = body.start_date
    item.end_date = body.end_date
    item.total_occurrences = body.total_occurrences
    item.contract_end_date = body.contract_end_date
    item.payer_mode = body.payer_mode
    item.paid_by_default = (
        None
        if body.payer_mode == PayerMode.own_share.value
        else require_member(db, body.paid_by_default, hh_id)
    )
    item.is_auto_pay = body.is_auto_pay
    item.is_active = body.is_active
    item.notes = (body.notes or "").strip() or None


def _replace_splits(db: Session, item: RecurringBill, body: RecurringItemIn) -> None:
    db.query(RecurringBillSplit).filter_by(bill_id=item.id).delete(synchronize_session=False)
    db.expire(item, ["splits"])
    for s in body.splits:
        db.add(
            RecurringBillSplit(bill_id=item.id, user_id=s.user_id, amount=parse_amount(s.amount))
        )


def _item_out(item: RecurringBill, next_entry) -> RecurringItemOut:
    return RecurringItemOut(
        id=item.id,
        name=item.name,
        direction=item.direction,
        amount=item.amount,
        currency=item.currency or "EUR",
        category_id=item.category_id,
        bucket_id=item.bucket_id,
        rule_kind=item.rule_kind,
        interval_months=item.interval_months or 1,
        rule_day=item.rule_day,
        rule_month=item.rule_month,
        rule_adjust=item.rule_adjust,
        rule_days=item.rule_days,
        rule_weekday=item.rule_weekday,
        rule_interval_weeks=item.rule_interval_weeks,
        start_date=item.start_date,
        end_date=item.end_date,
        total_occurrences=item.total_occurrences,
        contract_end_date=item.contract_end_date,
        paid_by_default=item.paid_by_default,
        payer_mode=item.payer_mode,
        payment_method=item.payment_method,
        is_auto_pay=item.is_auto_pay,
        is_active=item.is_active is not False,
        notes=item.notes,
        splits=[{"user_id": s.user_id, "amount": s.amount} for s in item.splits],
        next_entry=next_entry,
    )


def _next_entries(db: Session, hh_id: str) -> dict:
    """item id -> its first expected entry from today (active items only)."""
    today = local_today()
    first: dict = {}
    for e in list_entries(db, hh_id, today, horizon_end(today), today=today):
        if e.status == "expected":
            first.setdefault(e.item_id, e)
    return first


def _item_or_404(db: Session, item_id: str, hh_id: str) -> RecurringBill:
    item = db.get(RecurringBill, item_id)
    if not item or item.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return item


def _entry_or_404(db: Session, entry_id: str, hh_id: str) -> BillOccurrence:
    occ = db.get(BillOccurrence, entry_id)
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    return occ


# --------------------------------------------------------------- entries
# Declared before /{item_id}, or FastAPI would read "entries" as an item id.


@router.get("/entries", response_model=list[EntryOut])
def entries(
    from_: date = Query(alias="from"),
    to: date = Query(),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Entries of active items due in [from, to] (Upcoming, Year, history)."""
    user, hh_id = auth
    if to < from_ or (to - from_) > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=400, detail=f"'to' must be 0 to {MAX_RANGE_DAYS} days after 'from'."
        )
    return list_entries(db, hh_id, from_, to)


@router.post("/entries/{entry_id}/done", response_model=EntryOut)
def entry_done(
    entry_id: str,
    body: EntryDoneIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Pay (out: always an expense, a Fixed cost without a bucket) or Mark
    received (in: an income). Either creates and links the transaction."""
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    amount = parse_amount(body.amount, allow_blank=True)
    try:
        complete_entry(
            db,
            occ,
            user_id=user.id,
            amount=amount,
            person=require_member(db, body.person, hh_id),
            payment_method=payment_method_or_400(body.payment_method),
        )
    except EntryStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/entries/{entry_id}/undo", response_model=EntryOut)
def entry_undo(
    entry_id: str,
    body: EntryUndoIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Done -> expected (unlinks; ``delete_transaction`` deletes it too), or
    skipped -> expected."""
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    try:
        undo_occurrence(db, occ, delete_transaction=body.delete_transaction)
    except EntryStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/entries/{entry_id}/skip", response_model=EntryOut)
def entry_skip(entry_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    try:
        skip_entry(occ)
    except EntryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/entries/{entry_id}/amount", response_model=EntryOut)
def entry_amount(
    entry_id: str,
    body: EntryAmountIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    try:
        set_entry_amount(occ, parse_amount(body.amount))
    except EntryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


# ----------------------------------------------------------------- items


@router.get("", response_model=list[RecurringItemOut])
def list_items(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Every item, paused ones included, each with its next expected entry."""
    user, hh_id = auth
    items = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id)
        .order_by(RecurringBill.direction, RecurringBill.name)
        .all()
    )
    nxt = _next_entries(db, hh_id)
    return [_item_out(i, nxt.get(i.id)) for i in items]


@router.post("", response_model=RecurringItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    body: RecurringItemIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    """Create an item. Nothing is created before today (spec §3.4.4)."""
    user, hh_id = auth
    item = RecurringBill(household_id=hh_id)
    _apply(db, item, body, hh_id)
    db.add(item)
    db.flush()
    _replace_splits(db, item, body)
    generate_occurrences(db, item, past=PAST_NONE)
    db.commit()
    db.refresh(item)
    return _item_out(item, _next_entries(db, hh_id).get(item.id))


@router.get("/{item_id}", response_model=RecurringItemOut)
def get_item(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    item = _item_or_404(db, item_id, hh_id)
    return _item_out(item, _next_entries(db, hh_id).get(item.id))


@router.put("/{item_id}", response_model=RecurringItemOut)
def update_item(
    item_id: str,
    body: RecurringItemIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Edit an item. Only future expected entries with no amount set are
    regenerated (spec §3.4.3); resuming fills the horizon at once."""
    user, hh_id = auth
    item = _item_or_404(db, item_id, hh_id)
    _apply(db, item, body, hh_id)
    _replace_splits(db, item, body)
    delete_future_occurrences(db, item.id)
    generate_occurrences(db, item, past=PAST_NONE)
    db.commit()
    db.refresh(item)
    return _item_out(item, _next_entries(db, hh_id).get(item.id))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    item = _item_or_404(db, item_id, hh_id)
    if bill_has_payment_history(db, item.id):
        raise HTTPException(status_code=409, detail=BILL_HAS_HISTORY_MSG)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

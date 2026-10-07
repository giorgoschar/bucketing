"""
API bills routes — CRUD for recurring bills + pay/skip occurrences.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.clock import utcnow_naive
from app.core.database import get_db
from app.core.money import quantize
from app.models import (
    BillFrequency,
    BillOccurrence,
    ItemDirection,
    OccurrenceStatus,
    PayerMode,
    RecurringBill,
    RecurringBillSplit,
)
from app.schemas import parse_payer_mode, parse_payment_method
from app.services import get_overdue_bills, get_upcoming_bills
from app.services.bills import (
    BILL_HAS_HISTORY_MSG,
    EDIT_IN_NEW_APP_MSG,
    PAST_SKIPPED,
    backfill_bill_payer,
    bill_has_payment_history,
    delete_future_occurrences,
    effective_overrides,
    generate_occurrences,
    normalise_interval_months,
    resolve_bill_payment,
    settle_occurrence,
)
from app.validators import (
    check_split_sum,
    parse_amount,
    require_bucket,
    require_category,
    require_member,
    validate_split_users,
)

router = APIRouter(prefix="/bills", tags=["bills"])


def _validate_bill_refs(body, hh_id: str, db: Session) -> None:
    """Assert every id in the payload belongs to the caller's household.

    Without this, an authenticated client could point a bill at another
    household's bucket or split it onto users outside the household.
    """
    require_bucket(db, body.bucket_id, hh_id, optional=True)
    require_category(db, body.category_id, hh_id)
    require_member(db, body.paid_by_default, hh_id)
    if body.splits:
        validate_split_users([s.user_id for s in body.splits], hh_id, db)
    if body.payer_mode == PayerMode.own_share.value:
        if not body.splits:
            raise HTTPException(
                status_code=400,
                detail="payer_mode own_share needs splits (each member's share).",
            )
        # Own share has no single payer.
        body.paid_by_default = None


def _parse_bill_date(value: str | None, field: str, *, required: bool = False):
    if not value:
        if required:
            raise HTTPException(status_code=400, detail=f"{field} is required")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{field} must be an ISO date (YYYY-MM-DD)"
        ) from None


def _parse_frequency(value: str) -> BillFrequency:
    try:
        return BillFrequency(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown frequency '{value}'") from None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class BillSplitIn(BaseModel):
    user_id: str
    amount: Decimal


class BillIn(BaseModel):
    name: str
    amount: Decimal | None = None
    currency: str = "EUR"
    category_id: str | None = None
    bucket_id: str | None = None
    frequency: str = "monthly"
    interval_months: int = 1
    start_date: str  # ISO date required
    end_date: str | None = None
    contract_end_date: str | None = None
    total_occurrences: int | None = None
    paid_by_default: str | None = None
    notes: str | None = None
    is_auto_pay: bool = False
    splits: list[BillSplitIn] = []
    # "single" (paid_by_default pays) or "own_share" (each member pays their
    # split directly; needs splits).
    payer_mode: str = PayerMode.single.value
    # Update only: also give past payments with no payer this bill's payer.
    apply_to_past: bool = False

    @field_validator("payer_mode", mode="before")
    @classmethod
    def _payer_mode(cls, v):
        return parse_payer_mode(v)


class PayOccurrenceIn(BaseModel):
    amount: Decimal | None = None
    paid_by: str | None = None
    # None: paid_by if given, else the bill's payer mode.
    payer_mode: str | None = None
    payment_method: str = "card"
    splits: list[BillSplitIn] = []

    @field_validator("payment_method", mode="before")
    @classmethod
    def _payment_method(cls, v):
        return parse_payment_method(v)

    @field_validator("payer_mode", mode="before")
    @classmethod
    def _payer_mode(cls, v):
        return None if v is None or v == "" else parse_payer_mode(v)


def _bill_dict(b: RecurringBill) -> dict:
    return {
        "id": b.id,
        "household_id": b.household_id,
        "name": b.name,
        "amount": quantize(b.amount) if b.amount is not None else None,
        "currency": b.currency,
        "category_id": b.category_id,
        "bucket_id": b.bucket_id,
        "frequency": b.frequency.value,
        "interval_months": b.interval_months,
        "start_date": b.start_date.isoformat() if b.start_date else None,
        "end_date": b.end_date.isoformat() if b.end_date else None,
        "contract_end_date": b.contract_end_date.isoformat() if b.contract_end_date else None,
        "total_occurrences": b.total_occurrences,
        "paid_by_default": b.paid_by_default,
        "payer_mode": b.payer_mode,
        "notes": b.notes,
        "is_auto_pay": b.is_auto_pay,
        "is_active": b.is_active,
        "splits": [{"user_id": s.user_id, "amount": quantize(s.amount)} for s in b.splits],
    }


def _occ_dict(o: BillOccurrence) -> dict:
    return {
        "id": o.id,
        "bill_id": o.bill_id,
        "due_date": o.due_date.isoformat(),
        "amount": quantize(o.amount) if o.amount is not None else None,
        "status": o.status.value,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        "paid_by": o.paid_by,
        "transaction_id": o.transaction_id,
    }


def _assert_bill_in_household(bill: RecurringBill | None, hh_id: str):
    # Income items belong to /recurring; this older API only knows bills.
    if not bill or bill.household_id != hh_id or bill.direction != ItemDirection.out.value:
        raise HTTPException(status_code=404, detail="Bill not found")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
def list_bills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    q = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id, direction=ItemDirection.out.value)
        .order_by(RecurringBill.created_at)
    )
    total = q.count()
    bills = q.offset((page - 1) * page_size).limit(page_size).all()

    overdue = get_overdue_bills(db, hh_id)
    upcoming = get_upcoming_bills(db, hh_id, days=60)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_bill_dict(b) for b in bills],
        "overdue_occurrences": [_occ_dict(o) for o in overdue],
        "upcoming_occurrences": [_occ_dict(o) for o in upcoming],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_bill(
    body: BillIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    _validate_bill_refs(body, hh_id, db)
    amount = parse_amount(body.amount, field="Bill amount", allow_blank=True)

    bill = RecurringBill(
        household_id=hh_id,
        name=body.name.strip(),
        amount=amount,
        currency=body.currency,
        category_id=body.category_id,
        bucket_id=body.bucket_id,
        frequency=_parse_frequency(body.frequency),
        interval_months=normalise_interval_months(body.interval_months),
        start_date=_parse_bill_date(body.start_date, "start_date", required=True),
        end_date=_parse_bill_date(body.end_date, "end_date"),
        contract_end_date=_parse_bill_date(body.contract_end_date, "contract_end_date"),
        total_occurrences=body.total_occurrences,
        paid_by_default=body.paid_by_default,
        payer_mode=body.payer_mode,
        notes=body.notes,
        is_auto_pay=body.is_auto_pay,
    )
    db.add(bill)
    db.flush()

    if body.splits:
        check_split_sum([s.amount for s in body.splits], amount)
        for s in body.splits:
            db.add(RecurringBillSplit(bill_id=bill.id, user_id=s.user_id, amount=s.amount))

    generate_occurrences(db, bill, past=PAST_SKIPPED)
    db.commit()
    db.refresh(bill)
    return _bill_dict(bill)


@router.get("/{bill_id}")
def get_bill(
    bill_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bill = db.query(RecurringBill).filter_by(id=bill_id).first()
    _assert_bill_in_household(bill, hh_id)

    occurrences = (
        db.query(BillOccurrence)
        .filter_by(bill_id=bill_id)
        .order_by(BillOccurrence.due_date.desc())
        .all()
    )
    return {**_bill_dict(bill), "occurrences": [_occ_dict(o) for o in occurrences]}


@router.put("/{bill_id}")
def update_bill(
    bill_id: str,
    body: BillIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bill = db.query(RecurringBill).filter_by(id=bill_id).first()
    _assert_bill_in_household(bill, hh_id)
    if not bill.old_app_editable:
        raise HTTPException(status_code=409, detail=EDIT_IN_NEW_APP_MSG)
    _validate_bill_refs(body, hh_id, db)
    amount = parse_amount(body.amount, field="Bill amount", allow_blank=True)

    if body.splits:
        check_split_sum([s.amount for s in body.splits], amount)

    delete_future_occurrences(db, bill_id)

    bill.name = body.name.strip()
    bill.amount = amount
    bill.currency = body.currency
    bill.category_id = body.category_id
    bill.bucket_id = body.bucket_id
    bill.frequency = _parse_frequency(body.frequency)
    bill.interval_months = normalise_interval_months(body.interval_months)
    bill.start_date = _parse_bill_date(body.start_date, "start_date", required=True)
    bill.end_date = _parse_bill_date(body.end_date, "end_date")
    bill.contract_end_date = _parse_bill_date(body.contract_end_date, "contract_end_date")
    bill.total_occurrences = body.total_occurrences
    bill.paid_by_default = body.paid_by_default
    bill.payer_mode = body.payer_mode
    bill.notes = body.notes
    bill.is_auto_pay = body.is_auto_pay

    # Replace splits
    for s in bill.splits:
        db.delete(s)
    db.flush()
    for s in body.splits:
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=s.user_id, amount=s.amount))

    generate_occurrences(db, bill, past=PAST_SKIPPED)
    backfilled = None
    if body.apply_to_past:
        db.flush()
        db.expire(bill, ["splits"])
        backfilled = backfill_bill_payer(db, bill)
    db.commit()
    db.refresh(bill)
    out = _bill_dict(bill)
    if backfilled is not None:
        # resplit: own-share rows whose splits did not add up and were replaced
        # by the bill's (see backfill_bill_payer).
        out["backfilled"] = backfilled.updated
        out["resplit"] = backfilled.resplit
    return out


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(
    bill_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bill = db.query(RecurringBill).filter_by(id=bill_id).first()
    _assert_bill_in_household(bill, hh_id)
    if not bill.old_app_editable:
        raise HTTPException(status_code=409, detail=EDIT_IN_NEW_APP_MSG)
    if bill_has_payment_history(db, bill.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=BILL_HAS_HISTORY_MSG)
    db.delete(bill)
    db.commit()


@router.post("/occurrences/{occ_id}/pay")
def pay_occurrence(
    occ_id: str,
    body: PayOccurrenceIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    occ = db.get(BillOccurrence, occ_id)
    if not occ or occ.bill.household_id != hh_id or occ.bill.direction != ItemDirection.out.value:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    bill = occ.bill

    # Idempotency: a retried request must not create a second transaction and
    # orphan the first by overwriting occ.transaction_id.
    if occ.status == OccurrenceStatus.paid:
        return _occ_dict(occ)

    explicit_amount = parse_amount(body.amount, field="Amount", allow_blank=True)
    # Occurrence amount (standing-order mode) takes precedence over the bill
    # default, matching how the scheduler resolves it.
    pay_amount = explicit_amount if explicit_amount is not None else (occ.amount or bill.amount)
    if pay_amount is None:
        raise HTTPException(status_code=400, detail="Amount required for variable bills")

    if body.splits:
        validate_split_users([s.user_id for s in body.splits], hh_id, db)
    payer, payer_mode = resolve_bill_payment(
        db,
        bill,
        paid_by=require_member(db, body.paid_by, hh_id),
        payer_mode=body.payer_mode,
        fallback_user_id=user.id,
    )

    try:
        paid = settle_occurrence(
            db,
            occ,
            amount=pay_amount,
            paid_by=payer,
            payer_mode=payer_mode,
            paid_on=utcnow_naive(),
            payment_method=body.payment_method,
            split_overrides=effective_overrides(
                bill, {s.user_id: Decimal(str(s.amount)) for s in body.splits}
            ),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if paid and explicit_amount is not None:
        occ.amount = explicit_amount

    db.commit()
    return _occ_dict(occ)


@router.post("/occurrences/{occ_id}/skip")
def skip_occurrence(
    occ_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    occ = db.get(BillOccurrence, occ_id)
    if not occ or occ.bill.household_id != hh_id or occ.bill.direction != ItemDirection.out.value:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    if occ.status == OccurrenceStatus.paid:
        raise HTTPException(
            status_code=400, detail="Cannot skip an occurrence that is already paid"
        )

    occ.status = OccurrenceStatus.skipped
    db.commit()
    return _occ_dict(occ)

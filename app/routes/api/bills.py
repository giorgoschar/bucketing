"""
API bills routes — CRUD for recurring bills + pay/skip occurrences.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.models import (
    RecurringBill, RecurringBillSplit, BillOccurrence, OccurrenceStatus,
    BillFrequency, Transaction, TransactionSplit, TransactionType,
)
from app.bills_service import generate_occurrences, delete_future_occurrences
from app.services import get_upcoming_bills, get_overdue_bills

router = APIRouter(prefix="/bills", tags=["bills"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BillSplitIn(BaseModel):
    user_id: str
    amount:  float


class BillIn(BaseModel):
    name:              str
    amount:            float | None = None
    currency:          str          = "EUR"
    category_id:       str | None   = None
    bucket_id:         str | None   = None
    frequency:         str          = "monthly"
    interval_months:   int          = 1
    start_date:        str                       # ISO date required
    end_date:          str | None   = None
    contract_end_date: str | None   = None
    total_occurrences: int | None   = None
    paid_by_default:   str | None   = None
    notes:             str | None   = None
    is_auto_pay:       bool         = False
    splits:            list[BillSplitIn] = []


class PayOccurrenceIn(BaseModel):
    amount:   float | None = None
    paid_by:  str | None   = None
    splits:   list[BillSplitIn] = []


def _bill_dict(b: RecurringBill) -> dict:
    return {
        "id":               b.id,
        "household_id":     b.household_id,
        "name":             b.name,
        "amount":           float(b.amount) if b.amount is not None else None,
        "currency":         b.currency,
        "category_id":      b.category_id,
        "bucket_id":        b.bucket_id,
        "frequency":        b.frequency.value,
        "interval_months":  b.interval_months,
        "start_date":       b.start_date.isoformat() if b.start_date else None,
        "end_date":         b.end_date.isoformat() if b.end_date else None,
        "contract_end_date": b.contract_end_date.isoformat() if b.contract_end_date else None,
        "total_occurrences": b.total_occurrences,
        "paid_by_default":  b.paid_by_default,
        "notes":            b.notes,
        "is_auto_pay":      b.is_auto_pay,
        "is_active":        b.is_active,
        "splits": [
            {"user_id": s.user_id, "amount": float(s.amount)} for s in b.splits
        ],
    }


def _occ_dict(o: BillOccurrence) -> dict:
    return {
        "id":             o.id,
        "bill_id":        o.bill_id,
        "due_date":       o.due_date.isoformat(),
        "amount":         float(o.amount) if o.amount is not None else None,
        "status":         o.status.value,
        "paid_at":        o.paid_at.isoformat() if o.paid_at else None,
        "paid_by":        o.paid_by,
        "transaction_id": o.transaction_id,
    }


def _assert_bill_in_household(bill: RecurringBill | None, hh_id: str):
    if not bill or bill.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Bill not found")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_bills(
    page:      int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    q = db.query(RecurringBill).filter_by(household_id=hh_id).order_by(RecurringBill.created_at)
    total = q.count()
    bills = q.offset((page - 1) * page_size).limit(page_size).all()

    overdue  = get_overdue_bills(db, hh_id)
    upcoming = get_upcoming_bills(db, hh_id, days=60)

    return {
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "items":     [_bill_dict(b) for b in bills],
        "overdue_occurrences":  [_occ_dict(o) for o in overdue],
        "upcoming_occurrences": [_occ_dict(o) for o in upcoming],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_bill(
    body: BillIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bill = RecurringBill(
        household_id=hh_id,
        name=body.name.strip(),
        amount=body.amount,
        currency=body.currency,
        category_id=body.category_id,
        bucket_id=body.bucket_id,
        frequency=BillFrequency(body.frequency),
        interval_months=body.interval_months,
        start_date=date.fromisoformat(body.start_date),
        end_date=date.fromisoformat(body.end_date) if body.end_date else None,
        contract_end_date=date.fromisoformat(body.contract_end_date) if body.contract_end_date else None,
        total_occurrences=body.total_occurrences,
        paid_by_default=body.paid_by_default,
        notes=body.notes,
        is_auto_pay=body.is_auto_pay,
    )
    db.add(bill)
    db.flush()

    if body.splits:
        split_total = sum(s.amount for s in body.splits)
        if bill.amount is not None and round(split_total, 4) != round(float(bill.amount), 4):
            raise HTTPException(
                status_code=400,
                detail=f"Split amounts ({split_total:.2f}) must sum to the bill amount ({bill.amount:.2f})",
            )
        for s in body.splits:
            db.add(RecurringBillSplit(bill_id=bill.id, user_id=s.user_id, amount=s.amount))

    generate_occurrences(db, bill)
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

    delete_future_occurrences(db, bill_id)

    bill.name              = body.name.strip()
    bill.amount            = body.amount
    bill.currency          = body.currency
    bill.category_id       = body.category_id
    bill.bucket_id         = body.bucket_id
    bill.frequency         = BillFrequency(body.frequency)
    bill.interval_months   = body.interval_months
    bill.start_date        = date.fromisoformat(body.start_date)
    bill.end_date          = date.fromisoformat(body.end_date) if body.end_date else None
    bill.contract_end_date = date.fromisoformat(body.contract_end_date) if body.contract_end_date else None
    bill.total_occurrences = body.total_occurrences
    bill.paid_by_default   = body.paid_by_default
    bill.notes             = body.notes
    bill.is_auto_pay       = body.is_auto_pay

    # Replace splits
    for s in bill.splits:
        db.delete(s)
    db.flush()
    for s in body.splits:
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=s.user_id, amount=s.amount))

    generate_occurrences(db, bill)
    db.commit()
    db.refresh(bill)
    return _bill_dict(bill)


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(
    bill_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    bill = db.query(RecurringBill).filter_by(id=bill_id).first()
    _assert_bill_in_household(bill, hh_id)
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
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    bill = occ.bill
    pay_amount = body.amount if body.amount is not None else (float(bill.amount) if bill.amount else None)
    if pay_amount is None:
        raise HTTPException(status_code=400, detail="Amount required for variable bills")

    payer = body.paid_by or bill.paid_by_default or user.id

    if bill.bucket_id:
        txn = Transaction(
            bucket_id=bill.bucket_id,
            household_id=hh_id,
            amount=pay_amount,
            currency=bill.currency,
            type=TransactionType.expense,
            paid_by=payer,
            category_id=bill.category_id,
            notes=f"Bill: {bill.name}",
            transaction_date=occ.due_date,
        )
        db.add(txn)
        db.flush()
        occ.transaction_id = txn.id

        # Apply splits: body overrides first, then bill default splits
        split_map = {s.user_id: s.amount for s in body.splits}
        if bill.splits:
            for s in bill.splits:
                amt = split_map.get(s.user_id, float(s.amount))
                db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=amt))
        elif split_map:
            for uid, amt in split_map.items():
                db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=amt))

    occ.status  = OccurrenceStatus.paid
    occ.paid_at = datetime.utcnow()
    occ.paid_by = payer
    if body.amount is not None:
        occ.amount = body.amount

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
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Occurrence not found")

    occ.status = OccurrenceStatus.skipped
    db.commit()
    return _occ_dict(occ)

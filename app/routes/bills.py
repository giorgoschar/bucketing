"""
Bills routes: recurring bills + occurrences.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth
from app.models import (
    RecurringBill, RecurringBillSplit, BillOccurrence, OccurrenceStatus,
    BillFrequency, Transaction, TransactionSplit, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.bills_service import generate_occurrences, delete_future_occurrences
from app.services import get_upcoming_bills, get_overdue_bills
from app.config import settings
from app.templates import templates

router = APIRouter(prefix="/bills")


def _ctx(db, user, hh_id):
    household = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]
    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .all()
    )
    categories = db.query(Category).filter_by(household_id=hh_id).all()
    buckets = db.query(Bucket).filter_by(household_id=hh_id, status=BucketStatus.active).all()
    return {
        "household": household,
        "households": households,
        "members": members,
        "categories": categories,
        "buckets": buckets,
    }


@router.get("", response_class=HTMLResponse)
def bills_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _ctx(db, user, hh_id)

    overdue = get_overdue_bills(db, hh_id)
    upcoming = get_upcoming_bills(db, hh_id, days=settings.upcoming_bills_days)
    all_bills = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id)
        .order_by(RecurringBill.created_at)
        .all()
    )

    ctx.update({
        "request": request,
        "user": user,
        "overdue": overdue,
        "upcoming": upcoming,
        "all_bills": all_bills,
        "today": date.today(),
    })
    return templates.TemplateResponse("bills/list.html", ctx)


@router.post("", response_class=HTMLResponse)
async def create_bill(
    request: Request,
    name: str = Form(...),
    amount: str = Form(""),
    currency: str = Form("EUR"),
    category_id: str = Form(""),
    bucket_id: str = Form(""),
    frequency: str = Form("monthly"),
    interval_months: int = Form(1),
    start_date: str = Form(...),
    end_date: str = Form(""),
    contract_end_date: str = Form(""),
    total_occurrences: str = Form(""),
    paid_by_default: str = Form(""),
    notes: str = Form(""),
    is_auto_pay: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth

    bill = RecurringBill(
        household_id=hh_id,
        name=name.strip(),
        amount=float(amount) if amount.strip() else None,
        currency=currency,
        category_id=category_id or None,
        bucket_id=bucket_id or None,
        frequency=BillFrequency(frequency),
        interval_months=interval_months,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date) if end_date.strip() else None,
        contract_end_date=date.fromisoformat(contract_end_date) if contract_end_date.strip() else None,
        total_occurrences=int(total_occurrences) if total_occurrences.strip() else None,
        paid_by_default=paid_by_default or None,
        notes=notes.strip() or None,
        is_auto_pay=bool(is_auto_pay),
    )
    db.add(bill)
    db.flush()

    # Shared bill splits — fields named split_{user_id}
    form_data = await request.form()
    for key, value in form_data.items():
        if key.startswith("split_") and value.strip():
            uid = key[6:]
            try:
                split_amount = float(value)
            except ValueError:
                continue
            if split_amount > 0:
                db.add(RecurringBillSplit(bill_id=bill.id, user_id=uid, amount=split_amount))

    generate_occurrences(db, bill)
    db.commit()

    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/occurrences/{occ_id}/pay", response_class=HTMLResponse)
async def mark_paid(
    bill_id: str,
    occ_id: str,
    request: Request,
    amount: str = Form(""),
    paid_by: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    occ = db.get(BillOccurrence, occ_id)
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404)

    bill = occ.bill
    pay_amount = float(amount) if amount.strip() else bill.amount
    if not pay_amount:
        raise HTTPException(status_code=400, detail="Amount required for variable bills")

    payer = paid_by or bill.paid_by_default or user.id

    # Auto-create transaction
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

        # Create per-member splits — from form overrides first, then bill.splits defaults
        form_data = await request.form()
        split_overrides = {}
        for key, value in form_data.items():
            if key.startswith("split_") and value.strip():
                uid = key[6:]
                try:
                    split_overrides[uid] = float(value)
                except ValueError:
                    pass

        if bill.splits:
            for s in bill.splits:
                split_amt = split_overrides.get(s.user_id, s.amount)
                db.add(TransactionSplit(
                    transaction_id=txn.id,
                    user_id=s.user_id,
                    amount=split_amt,
                ))
        elif split_overrides:
            for uid, split_amt in split_overrides.items():
                db.add(TransactionSplit(
                    transaction_id=txn.id,
                    user_id=uid,
                    amount=split_amt,
                ))

    occ.status = OccurrenceStatus.paid
    occ.paid_at = datetime.utcnow()
    occ.paid_by = payer
    if amount.strip():
        occ.amount = float(amount)

    db.commit()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/bill_occurrence_row.html",
            {"request": request, "occ": occ, "bill": bill},
        )
    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/occurrences/{occ_id}/set-amount", response_class=HTMLResponse)
async def set_occurrence_amount(
    bill_id: str,
    occ_id: str,
    request: Request,
    amount: str = Form(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Save an amount on a variable-bill occurrence without marking it paid.

    This supports "standing order" mode: user pre-sets the amount so the
    scheduler can auto-mark it paid on the due date.
    """
    user, hh_id = auth
    occ = db.get(BillOccurrence, occ_id)
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404)

    try:
        occ.amount = float(amount)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid amount")

    db.commit()

    bill = occ.bill
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/bill_occurrence_row.html",
            {"request": request, "occ": occ, "bill": bill},
        )
    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/occurrences/{occ_id}/skip", response_class=HTMLResponse)
def skip_occurrence(
    bill_id: str,
    occ_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    occ = db.get(BillOccurrence, occ_id)
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404)

    occ.status = OccurrenceStatus.skipped
    db.commit()

    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return RedirectResponse("/bills", status_code=302)


@router.get("/{bill_id}/edit", response_class=HTMLResponse)
def edit_bill_page(
    bill_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id:
        raise HTTPException(status_code=404)
    ctx = _ctx(db, user, hh_id)
    ctx.update({"request": request, "user": user, "bill": bill})
    return templates.TemplateResponse("bills/edit.html", ctx)


@router.post("/{bill_id}/edit", response_class=HTMLResponse)
async def edit_bill(
    bill_id: str,
    request: Request,
    name: str = Form(...),
    amount: str = Form(""),
    currency: str = Form("EUR"),
    category_id: str = Form(""),
    bucket_id: str = Form(""),
    frequency: str = Form("monthly"),
    interval_months: int = Form(1),
    start_date: str = Form(...),
    end_date: str = Form(""),
    contract_end_date: str = Form(""),
    total_occurrences: str = Form(""),
    paid_by_default: str = Form(""),
    notes: str = Form(""),
    is_auto_pay: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id:
        raise HTTPException(status_code=404)

    bill.name = name.strip()
    bill.amount = float(amount) if amount.strip() else None
    bill.currency = currency
    bill.category_id = category_id or None
    bill.bucket_id = bucket_id or None
    bill.frequency = BillFrequency(frequency)
    bill.interval_months = interval_months
    bill.start_date = date.fromisoformat(start_date)
    bill.end_date = date.fromisoformat(end_date) if end_date.strip() else None
    bill.contract_end_date = date.fromisoformat(contract_end_date) if contract_end_date.strip() else None
    bill.total_occurrences = int(total_occurrences) if total_occurrences.strip() else None
    bill.paid_by_default = paid_by_default or None
    bill.notes = notes.strip() or None
    bill.is_auto_pay = bool(is_auto_pay)

    # Replace splits
    db.query(RecurringBillSplit).filter_by(bill_id=bill.id).delete()
    form_data = await request.form()
    for key, value in form_data.items():
        if key.startswith("split_") and value.strip():
            uid = key[6:]
            try:
                split_amount = float(value)
            except ValueError:
                continue
            if split_amount > 0:
                db.add(RecurringBillSplit(bill_id=bill.id, user_id=uid, amount=split_amount))

    # Regenerate future occurrences
    delete_future_occurrences(db, bill.id)
    generate_occurrences(db, bill)
    db.commit()

    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/toggle", response_class=HTMLResponse)
def toggle_bill(
    bill_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id:
        raise HTTPException(status_code=404)
    bill.is_active = not bill.is_active
    db.commit()
    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/delete", response_class=HTMLResponse)
def delete_bill(
    bill_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id:
        raise HTTPException(status_code=404)
    db.delete(bill)
    db.commit()
    return RedirectResponse("/bills", status_code=302)

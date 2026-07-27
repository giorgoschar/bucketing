"""
Bills routes: recurring bills + occurrences.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_auth, require_csrf
from app.models import (
    RecurringBill, RecurringBillSplit, BillOccurrence, OccurrenceStatus,
    BillFrequency, Transaction, TransactionSplit, TransactionType,
    Bucket, BucketStatus, Category, User, HouseholdMember, Household,
)
from app.bills_service import generate_occurrences, delete_future_occurrences, normalise_interval_months
from app.services import get_upcoming_bills, get_overdue_bills, full_ctx
from app.validators import (
    parse_amount, require_bucket, require_category, require_member, validate_split_users,
)
from app.config import settings
from app.templates import templates

router = APIRouter(prefix="/bills", dependencies=[Depends(require_csrf)])


def _checkbox(value: str) -> bool:
    """Interpret an HTML checkbox value.

    Unchecked boxes submit nothing; checked ones submit "on". bool() alone was
    wrong because any non-empty string — including "false" and "off", which some
    clients send — evaluates truthy.
    """
    return str(value).strip().lower() in {"on", "true", "1", "yes"}


def _parse_iso_date(value: str, field: str, *, required: bool = True):
    """Parse an ISO date from a form field, returning HTTP 400 rather than a 500."""
    value = (value or "").strip()
    if not value:
        if required:
            raise HTTPException(status_code=400, detail=f"{field} is required.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be a valid date (YYYY-MM-DD).")


async def _collect_splits(request: Request, hh_id: str, db: Session) -> tuple[list[tuple[str, float]], float]:
    """Read split_{user_id} form fields, validating each user is in the household."""
    form_data = await request.form()
    splits: list[tuple[str, float]] = []
    total = 0.0
    for key, value in form_data.items():
        if not key.startswith("split_") or not str(value).strip():
            continue
        uid = key[6:]
        amount = parse_amount(value, field="Split amount", allow_blank=True)
        if amount is None or amount <= 0:
            continue
        splits.append((uid, float(amount)))
        total += float(amount)
    if splits:
        validate_split_users([uid for uid, _ in splits], hh_id, db)
    return splits, total



@router.get("", response_class=HTMLResponse)
def bills_page(
    request: Request,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = full_ctx(db, user, hh_id)

    overdue = get_overdue_bills(db, hh_id)
    upcoming = get_upcoming_bills(db, hh_id, days=settings.upcoming_bills_days)

    BILLS_PAGE_SIZE = 20
    bills_q = db.query(RecurringBill).filter_by(household_id=hh_id).order_by(RecurringBill.created_at)
    bills_total = bills_q.count()
    bills_total_pages = max(1, -(-bills_total // BILLS_PAGE_SIZE))
    page = min(page, bills_total_pages)
    all_bills = bills_q.offset((page - 1) * BILLS_PAGE_SIZE).limit(BILLS_PAGE_SIZE).all()

    ctx.update({
        "request": request,
        "user": user,
        "overdue": overdue,
        "upcoming": upcoming,
        "all_bills": all_bills,
        "today": date.today(),
        "bills_page": page,
        "bills_total_pages": bills_total_pages,
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

    bill_amount = parse_amount(amount, field="Bill amount", allow_blank=True)
    splits, split_total = await _collect_splits(request, hh_id, db)
    if splits and bill_amount is not None and round(split_total, 4) != round(float(bill_amount), 4):
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({split_total:.2f}) must sum to the bill amount ({float(bill_amount):.2f}).",
        )

    bill = RecurringBill(
        household_id=hh_id,
        name=name.strip(),
        amount=bill_amount,
        currency=currency,
        category_id=require_category(db, category_id, hh_id),
        bucket_id=require_bucket(db, bucket_id, hh_id, optional=True).id if bucket_id else None,
        frequency=BillFrequency(frequency),
        interval_months=normalise_interval_months(interval_months),
        start_date=_parse_iso_date(start_date, "Start date"),
        end_date=_parse_iso_date(end_date, "End date", required=False),
        contract_end_date=_parse_iso_date(contract_end_date, "Contract end date", required=False),
        total_occurrences=int(total_occurrences) if total_occurrences.strip().isdigit() else None,
        paid_by_default=require_member(db, paid_by_default, hh_id),
        notes=notes.strip() or None,
        is_auto_pay=_checkbox(is_auto_pay),
    )
    db.add(bill)
    db.flush()

    for uid, split_amount in splits:
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

    # Idempotency: a double-click (or a retried request) used to create a second
    # transaction and orphan the first by overwriting occ.transaction_id.
    if occ.status == OccurrenceStatus.paid:
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "partials/bill_occurrence_row.html",
                {"request": request, "occ": occ, "bill": bill},
            )
        return RedirectResponse("/bills", status_code=302)

    explicit_amount = parse_amount(amount, field="Amount", allow_blank=True)
    # Fall back to the occurrence's pre-set amount (standing-order mode) before
    # the bill default — the scheduler already resolves it in that order.
    pay_amount = explicit_amount if explicit_amount is not None else (occ.amount or bill.amount)
    if not pay_amount:
        raise HTTPException(status_code=400, detail="Amount required for variable bills")

    payer = require_member(db, paid_by, hh_id) or bill.paid_by_default or user.id

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
        overrides, _ = await _collect_splits(request, hh_id, db)
        split_overrides = dict(overrides)

        if bill.splits:
            for s in bill.splits:
                db.add(TransactionSplit(
                    transaction_id=txn.id,
                    user_id=s.user_id,
                    amount=split_overrides.get(s.user_id, s.amount),
                ))
        else:
            for uid, split_amt in split_overrides.items():
                db.add(TransactionSplit(
                    transaction_id=txn.id,
                    user_id=uid,
                    amount=split_amt,
                ))

    occ.status = OccurrenceStatus.paid
    occ.paid_at = datetime.utcnow()
    occ.paid_by = payer
    if explicit_amount is not None:
        occ.amount = explicit_amount

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

    if occ.status != OccurrenceStatus.unpaid:
        raise HTTPException(status_code=400, detail="This occurrence is already settled.")

    occ.amount = parse_amount(amount, field="Amount")
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

    # Skipping a paid occurrence would leave its transaction behind while the
    # bill history stops reporting it as paid.
    if occ.status == OccurrenceStatus.paid:
        raise HTTPException(status_code=400, detail="Cannot skip an occurrence that is already paid.")

    occ.status = OccurrenceStatus.skipped
    db.commit()

    bill = occ.bill
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/bill_occurrence_row.html",
            {"request": request, "occ": occ, "bill": bill},
        )
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
    ctx = full_ctx(db, user, hh_id)
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

    bill_amount = parse_amount(amount, field="Bill amount", allow_blank=True)
    splits, split_total = await _collect_splits(request, hh_id, db)
    if splits and bill_amount is not None and round(split_total, 4) != round(float(bill_amount), 4):
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({split_total:.2f}) must sum to the bill amount ({float(bill_amount):.2f}).",
        )

    bill.name = name.strip()
    bill.amount = bill_amount
    bill.currency = currency
    bill.category_id = require_category(db, category_id, hh_id)
    bill.bucket_id = require_bucket(db, bucket_id, hh_id, optional=True).id if bucket_id else None
    bill.frequency = BillFrequency(frequency)
    bill.interval_months = normalise_interval_months(interval_months)
    bill.start_date = _parse_iso_date(start_date, "Start date")
    bill.end_date = _parse_iso_date(end_date, "End date", required=False)
    bill.contract_end_date = _parse_iso_date(contract_end_date, "Contract end date", required=False)
    bill.total_occurrences = int(total_occurrences) if total_occurrences.strip().isdigit() else None
    bill.paid_by_default = require_member(db, paid_by_default, hh_id)
    bill.notes = notes.strip() or None
    bill.is_auto_pay = _checkbox(is_auto_pay)

    # Replace splits
    db.query(RecurringBillSplit).filter_by(bill_id=bill.id).delete(synchronize_session=False)
    for uid, split_amount in splits:
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


# ---------------------------------------------------------------------------
# Bill payment history
# ---------------------------------------------------------------------------

@router.get("/{bill_id}/history", response_class=HTMLResponse)
def bill_history(
    bill_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id:
        raise HTTPException(status_code=404)

    paid_occurrences = (
        db.query(BillOccurrence)
        .filter_by(bill_id=bill_id, status=OccurrenceStatus.paid)
        .order_by(BillOccurrence.due_date.desc())
        .all()
    )
    return templates.TemplateResponse(
        "bills/history_partial.html",
        {
            "request": request,
            "bill": bill,
            "occurrences": paid_occurrences,
        },
    )

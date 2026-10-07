"""
Bills routes: recurring bills + occurrences.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.core.clock import local_today, utcnow_naive
from app.core.config import settings
from app.core.database import get_db
from app.models import (
    BillFrequency,
    BillOccurrence,
    ItemDirection,
    OccurrenceStatus,
    PayerMode,
    RecurringBill,
    RecurringBillSplit,
)
from app.schemas import parse_payment_method, payer_choice
from app.services import full_ctx, get_overdue_bills, get_upcoming_bills
from app.services.bills import (
    BILL_HAS_HISTORY_MSG,
    EDIT_IN_NEW_APP_MSG,
    PAST_NONE,
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
from app.templates import templates
from app.validators import (
    parse_amount,
    require_bucket,
    require_category,
    require_member,
    validate_split_users,
)

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
        raise HTTPException(
            status_code=400, detail=f"{field} must be a valid date (YYYY-MM-DD)."
        ) from None


async def _collect_splits(
    request: Request, hh_id: str, db: Session
) -> tuple[list[tuple[str, float]], float]:
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


def _old_app_bill(db: Session, bill_id: str, hh_id: str) -> RecurringBill:
    """The bill if the old app may see it: this household's, and an out item.

    Income items do not exist for the old app (spec §6.2.1), so a stale page
    or bookmark gets a 404 and can never pay one as an expense.
    """
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id or bill.direction != ItemDirection.out.value:
        raise HTTPException(status_code=404)
    return bill


def _old_app_occurrence(db: Session, occ_id: str, hh_id: str) -> BillOccurrence:
    occ = db.get(BillOccurrence, occ_id)
    if not occ:
        raise HTTPException(status_code=404)
    _old_app_bill(db, occ.bill_id, hh_id)
    return occ


def _require_old_app_editable(bill: RecurringBill) -> None:
    """New schedule rules are read-only here (spec §6.2.2)."""
    if not bill.old_app_editable:
        raise HTTPException(status_code=409, detail=EDIT_IN_NEW_APP_MSG)


def _bill_payer(db: Session, hh_id: str, value: str, splits) -> tuple[str | None, str]:
    """Resolve the bill form's "Default payer" value to (paid_by_default, payer_mode).

    "Each paid their own share" records every payment as each member paying
    their split, so the bill needs those splits.
    """
    payer, mode = payer_choice(value)
    if mode == PayerMode.own_share.value and not splits:
        raise HTTPException(
            status_code=400,
            detail="Each paid their own share needs each member's share filled in.",
        )
    return require_member(db, payer, hh_id), mode


@router.get("", response_class=HTMLResponse)
def bills_page(
    request: Request,
    page: int = Query(1, ge=1),
    backfilled: int | None = Query(None, ge=0),
    resplit: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    notice = None
    if backfilled is not None:
        # Only a count is reflected, never free text.
        notice = (
            f"Updated {backfilled} past payment{'s' if backfilled != 1 else ''} that had no payer."
        )
        if resplit:
            notice += (
                f" {resplit} of them had splits that did not add up to its amount; "
                "they now use the bill's split."
            )
    return _render_bills(request, db, user, hh_id, page=page, notice=notice)


def _render_bills(
    request,
    db,
    user,
    hh_id,
    *,
    page: int = 1,
    error: str | None = None,
    notice: str | None = None,
    status_code: int = 200,
):
    ctx = full_ctx(db, user, hh_id)

    overdue = get_overdue_bills(db, hh_id)
    upcoming = get_upcoming_bills(db, hh_id, days=settings.upcoming_bills_days)

    BILLS_PAGE_SIZE = 20
    bills_q = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id, direction=ItemDirection.out.value)
        .order_by(RecurringBill.created_at)
    )
    bills_total = bills_q.count()
    bills_total_pages = max(1, -(-bills_total // BILLS_PAGE_SIZE))
    page = min(page, bills_total_pages)
    all_bills = bills_q.offset((page - 1) * BILLS_PAGE_SIZE).limit(BILLS_PAGE_SIZE).all()

    ctx.update(
        {
            "request": request,
            "user": user,
            "overdue": overdue,
            "upcoming": upcoming,
            "all_bills": all_bills,
            "today": local_today(),
            "bills_page": page,
            "bills_total_pages": bills_total_pages,
            "error": error,
            "notice": notice,
        }
    )
    return templates.TemplateResponse("bills/list.html", ctx, status_code=status_code)


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
    payer_default, payer_mode = _bill_payer(db, hh_id, paid_by_default, splits)

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
        paid_by_default=payer_default,
        payer_mode=payer_mode,
        notes=notes.strip() or None,
        is_auto_pay=_checkbox(is_auto_pay),
    )
    db.add(bill)
    db.flush()

    for uid, split_amount in splits:
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=uid, amount=split_amount))

    # Nothing before today becomes an expected entry (spec §3.4.4).
    generate_occurrences(db, bill, past=PAST_SKIPPED)
    db.commit()

    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/occurrences/{occ_id}/pay", response_class=HTMLResponse)
async def mark_paid(
    bill_id: str,
    occ_id: str,
    request: Request,
    amount: str = Form(""),
    paid_by: str = Form(""),
    payment_method: str = Form("card"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    occ = _old_app_occurrence(db, occ_id, hh_id)

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

    # Blank = the bill's default (its payer mode, then its default payer).
    chosen, chosen_mode = payer_choice(paid_by)
    payer, payer_mode = resolve_bill_payment(
        db,
        bill,
        paid_by=require_member(db, chosen, hh_id),
        payer_mode=chosen_mode if chosen_mode == PayerMode.own_share.value else None,
        fallback_user_id=user.id,
    )
    try:
        pm = parse_payment_method(payment_method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # Form overrides replace the bill's default (scaled) splits.
    overrides, _ = await _collect_splits(request, hh_id, db)
    try:
        paid = settle_occurrence(
            db,
            occ,
            amount=pay_amount,
            paid_by=payer,
            payer_mode=payer_mode,
            paid_on=utcnow_naive(),
            payment_method=pm,
            split_overrides=effective_overrides(
                bill, {uid: Decimal(str(a)) for uid, a in overrides}
            ),
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if paid and explicit_amount is not None:
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
    occ = _old_app_occurrence(db, occ_id, hh_id)

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
    occ = _old_app_occurrence(db, occ_id, hh_id)

    # Skipping a paid occurrence would leave its transaction behind while the
    # bill history stops reporting it as paid.
    if occ.status == OccurrenceStatus.paid:
        raise HTTPException(
            status_code=400, detail="Cannot skip an occurrence that is already paid."
        )

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
    bill = _old_app_bill(db, bill_id, hh_id)
    _require_old_app_editable(bill)
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
    apply_to_past: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = _old_app_bill(db, bill_id, hh_id)
    _require_old_app_editable(bill)

    bill_amount = parse_amount(amount, field="Bill amount", allow_blank=True)
    splits, split_total = await _collect_splits(request, hh_id, db)
    if splits and bill_amount is not None and round(split_total, 4) != round(float(bill_amount), 4):
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({split_total:.2f}) must sum to the bill amount ({float(bill_amount):.2f}).",
        )
    payer_default, payer_mode = _bill_payer(db, hh_id, paid_by_default, splits)

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
    bill.paid_by_default = payer_default
    bill.payer_mode = payer_mode
    bill.notes = notes.strip() or None
    bill.is_auto_pay = _checkbox(is_auto_pay)

    # Replace splits
    db.query(RecurringBillSplit).filter_by(bill_id=bill.id).delete(synchronize_session=False)
    db.expire(bill, ["splits"])
    for uid, split_amount in splits:
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=uid, amount=split_amount))

    # Regenerate the future entries nobody touched (spec §3.4.3-4).
    delete_future_occurrences(db, bill.id)
    generate_occurrences(db, bill, past=PAST_SKIPPED)

    # Optionally repair past payments saved without a payer, using the payer
    # (or own-share splits) just set.
    backfilled = None
    if _checkbox(apply_to_past):
        db.flush()
        backfilled = backfill_bill_payer(db, bill)
    db.commit()

    if backfilled is not None:
        query = f"backfilled={backfilled.updated}"
        if backfilled.resplit:
            query += f"&resplit={backfilled.resplit}"
        return RedirectResponse(f"/bills?{query}", status_code=302)
    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/toggle", response_class=HTMLResponse)
def toggle_bill(
    bill_id: str,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = _old_app_bill(db, bill_id, hh_id)
    _require_old_app_editable(bill)
    bill.is_active = not bill.is_active
    if bill.is_active:
        # Resumed: fill the horizon now rather than at the next nightly run.
        generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
    return RedirectResponse("/bills", status_code=302)


@router.post("/{bill_id}/delete", response_class=HTMLResponse)
def delete_bill(
    bill_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    bill = _old_app_bill(db, bill_id, hh_id)
    _require_old_app_editable(bill)
    if bill_has_payment_history(db, bill.id):
        return _render_bills(request, db, user, hh_id, error=BILL_HAS_HISTORY_MSG, status_code=409)
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
    bill = _old_app_bill(db, bill_id, hh_id)

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

"""
Cash ledger pages: per-member balances, the withdrawals-vs-cash-spend
comparison and the movements list. Adds/deletes swap #cash-list via HTMX.
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.clock import local_today
from app.database import get_db
from app.models import CashMovement, Household
from app.services import (
    add_movement,
    can_manage_for,
    cash_comparison,
    delete_movement,
    full_ctx,
    list_movements,
    member_balances,
    parse_month,
)
from app.templates import templates
from app.validators import household_member_ids, parse_amount, require_category, require_member

router = APIRouter(dependencies=[Depends(require_csrf)])


def _list_ctx(db: Session, user, hh_id: str, month: str | None, member: str | None) -> dict:
    """Context for the swappable #cash-list block (balances, comparison, rows)."""
    try:
        start, end, month_key = parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    ctx = full_ctx(db, user, hh_id)
    members = ctx["members"]
    filter_id = require_member(db, member, hh_id) if member else None
    target_id = filter_id or user.id
    movements = list_movements(db, hh_id, member_id=filter_id, start=start, end=end)
    balances = member_balances(db, hh_id)
    ctx.update({
        "user": user,
        "month": month_key,
        "member_filter": filter_id or "",
        "target_id": target_id,
        "target_name": next((m.display_name for m in members if m.id == target_id), ""),
        "names": {m.id: m.display_name for m in members},
        "colors": {m.id: m.avatar_color for m in members},
        "balances": [(m, balances.get(m.id, 0)) for m in members],
        "comparison": cash_comparison(db, hh_id, target_id, start, end),
        "movements": movements,
        "deletable": {mv.id for mv in movements if can_manage_for(db, user.id, hh_id, mv.user_id)},
        "cash_cats": {c.id: c.name for c in ctx["categories"]},
    })
    return ctx


def _respond(request: Request, db: Session, user, hh_id: str, month: str | None, member: str | None):
    if request.headers.get("HX-Request"):
        ctx = _list_ctx(db, user, hh_id, month, member)
        ctx["request"] = request
        return templates.TemplateResponse("cash/_list.html", ctx)
    qs = f"?month={month}" if month else ""
    return RedirectResponse(f"/cash{qs}", status_code=302)


@router.get("/cash", response_class=HTMLResponse)
def cash_page(
    request: Request,
    month: str = "",
    member: str = "",
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _list_ctx(db, user, hh_id, month or None, member or None)
    ctx["request"] = request
    ctx["today"] = local_today()
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "cash-list":
        return templates.TemplateResponse("cash/_list.html", ctx)
    return templates.TemplateResponse("cash/index.html", ctx)


@router.post("/cash/add", response_class=HTMLResponse)
def add_cash(
    request: Request,
    kind: str = Form(...),
    amount: str = Form(...),
    movement_date: str = Form(""),
    category_id: str = Form(""),
    note: str = Form(""),
    user_id: str = Form(""),
    month: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    if kind not in ("in", "out"):
        raise HTTPException(status_code=400, detail="Kind must be 'in' or 'out'.")
    value = parse_amount(amount, field="Amount")
    try:
        when = date.fromisoformat(movement_date.strip()) if movement_date.strip() else local_today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be a valid date (YYYY-MM-DD).") from None
    if len(note.strip()) > 500:
        raise HTTPException(status_code=400, detail="Note must be at most 500 characters.")
    target = user_id or user.id
    if target not in household_member_ids(db, hh_id):
        raise HTTPException(status_code=400, detail="That person is not a member of this household.")
    if not can_manage_for(db, user.id, hh_id, target):
        raise HTTPException(status_code=403, detail="Only the owner can log cash for another member.")
    cat = require_category(db, category_id, hh_id)

    currency = db.get(Household, hh_id).default_currency  # cash is household-currency only
    add_movement(db, hh_id, target, kind, value, currency, when, cat, note)
    return _respond(request, db, user, hh_id, month or None, None)


@router.post("/cash/{movement_id}/delete", response_class=HTMLResponse)
def delete_cash(
    movement_id: str,
    request: Request,
    month: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    mv = (
        db.query(CashMovement)
        .filter(CashMovement.id == movement_id, CashMovement.household_id == hh_id,
                CashMovement.active())
        .first()
    )
    if not mv:
        raise HTTPException(status_code=404)
    if not can_manage_for(db, user.id, hh_id, mv.user_id):
        raise HTTPException(status_code=403, detail="You can only delete your own cash movements.")
    delete_movement(db, mv)
    return _respond(request, db, user, hh_id, month or None, None)

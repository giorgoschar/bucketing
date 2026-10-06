"""
Cash page: your private stash, every member's wallet this month and your cash
history. Adds/deletes swap #cash-list via HTMX.

The stash is its owner's alone: only they see its balance and history (which
includes other members' takes from it). Others may take from it into their
own wallet without ever seeing the balance; household owners get no special
access. Each member logs and deletes only their own movements (a hidden one
answers 404, as if it did not exist). See app.services.cash for the model.
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.clock import local_today
from app.database import get_db
from app.models import Household
from app.services import (
    delete_own_movement,
    full_ctx,
    list_movements,
    parse_month,
    record_movement,
    stash_balance,
    wallet_summaries,
    withdraw_and_spend,
)
from app.services.cash import FROM_BANK, FROM_STASH, LOGGABLE, STILL_HAVE, TAKE
from app.templates import templates
from app.validators import parse_amount, require_bucket, require_category

router = APIRouter(dependencies=[Depends(require_csrf)])


def _list_ctx(db: Session, user, hh_id: str, month: str | None) -> dict:
    """Context for the swappable #cash-list block."""
    try:
        start, end, month_key = parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    ctx = full_ctx(db, user, hh_id)
    members = ctx["members"]
    # You first, then everyone else: your card carries the "Still have" form.
    ordered = sorted(members, key=lambda m: m.id != user.id)
    wallets = wallet_summaries(db, hh_id, [m.id for m in ordered], start, end, viewer_id=user.id)
    ctx.update({
        "user": user,
        "month": month_key,
        "today": local_today(),
        "names": {m.id: m.display_name for m in members},
        "others": [m for m in members if m.id != user.id],
        "stash": stash_balance(db, hh_id, user.id),
        "wallets": [(m, wallets[m.id]) for m in ordered],
        "movements": list_movements(db, hh_id, user.id, start=start, end=end),
    })
    return ctx


def _private(response):
    """The page carries the viewer's stash: never stored, not even by the
    service worker's offline copy (static/sw.js), for the next user."""
    response.headers["Cache-Control"] = "no-store"
    return response


def _respond(request: Request, db: Session, user, hh_id: str, month: str | None):
    if request.headers.get("HX-Request"):
        ctx = _list_ctx(db, user, hh_id, month)
        ctx["request"] = request
        return _private(templates.TemplateResponse("cash/_list.html", ctx))
    qs = f"?month={month}" if month else ""
    return RedirectResponse(f"/cash{qs}", status_code=302)


@router.get("/cash", response_class=HTMLResponse)
def cash_page(
    request: Request,
    month: str = "",
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _list_ctx(db, user, hh_id, month or None)
    ctx["request"] = request
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "cash-list":
        return _private(templates.TemplateResponse("cash/_list.html", ctx))
    return _private(templates.TemplateResponse("cash/index.html", ctx))


@router.post("/cash/add", response_class=HTMLResponse)
def add_cash(
    request: Request,
    kind: str = Form(...),
    amount: str = Form(...),
    movement_date: str = Form(""),
    note: str = Form(""),
    source: str = Form(""),
    spend: str = Form(""),
    spend_bucket_id: str = Form(""),
    category_id: str = Form(""),
    month: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Log one of your movements. A ``take``'s ``source`` is a member's id
    (their stash, or your own) or "bank". A take with ``spend_bucket_id`` also
    records the cash expense it was for (category, note), in one step;
    ``spend`` (the "Spent it straight away" box) without a bucket is refused
    rather than quietly recorded as a plain take."""
    user, hh_id = auth
    if kind not in LOGGABLE:
        raise HTTPException(status_code=400, detail=f"Kind must be one of: {', '.join(LOGGABLE)}.")
    # An empty wallet is a valid "still have".
    value = parse_amount(amount, field="Amount", allow_zero=(kind == STILL_HAVE))
    try:
        when = date.fromisoformat(movement_date.strip()) if movement_date.strip() else local_today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be a valid date (YYYY-MM-DD).") from None
    if len(note.strip()) > 500:
        raise HTTPException(status_code=400, detail="Note must be at most 500 characters.")
    stash_owner = None if source.strip() in ("", FROM_BANK) else source.strip()
    household = db.get(Household, hh_id)

    if kind == TAKE and spend and not spend_bucket_id.strip():
        raise HTTPException(status_code=400, detail="Choose the bucket the cash was spent on.")
    if kind == TAKE and spend_bucket_id.strip():
        if stash_owner not in (None, user.id):
            raise HTTPException(status_code=400,
                                detail="Spending it straight away works from your own stash or the bank.")
        bucket = require_bucket(db, spend_bucket_id.strip(), hh_id)
        try:
            withdraw_and_spend(
                db, user=user, household_id=hh_id, bucket=bucket, amount=value,
                source=FROM_STASH if stash_owner else FROM_BANK, when=when,
                category_id=require_category(db, category_id, hh_id), notes=note,
                currency=household.default_currency,
            )
        except ValidationError as exc:
            msg = exc.errors()[0]["msg"].removeprefix("Value error, ")
            raise HTTPException(status_code=400, detail=msg) from None
    else:
        # cash is household-currency only
        record_movement(
            db, household_id=hh_id, actor_id=user.id, kind=kind, amount=value,
            currency=household.default_currency, when=when, note=note,
            stash_owner_id=stash_owner,
        )
    return _respond(request, db, user, hh_id, month or None)


@router.post("/cash/{movement_id}/delete", response_class=HTMLResponse)
def delete_cash(
    movement_id: str,
    request: Request,
    month: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    delete_own_movement(db, hh_id, user.id, movement_id)
    return _respond(request, db, user, hh_id, month or None)

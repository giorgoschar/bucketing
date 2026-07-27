"""
Household-wide settle up.

Per-bucket settlement answers "who owes whom for the Florence trip". This
answers "who owes whom, full stop" — nets every settlement-enabled bucket
together so members square up once instead of bucket by bucket.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.database import get_db
from app.models import Bucket
from app.services import (
    base_ctx,
    get_household_settlement,
    get_household_settlement_history,
    get_member_balances,
    record_household_settlement,
)
from app.templates import templates
from app.validators import parse_amount, require_member

router = APIRouter(dependencies=[Depends(require_csrf)])


@router.get("/settlement", response_class=HTMLResponse)
def settlement_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = base_ctx(db, user, hh_id)

    enabled_buckets = (
        db.query(Bucket)
        .filter(Bucket.household_id == hh_id, Bucket.enable_settlement.is_(True))
        .order_by(Bucket.created_at)
        .all()
    )

    ctx.update({
        "request":     request,
        "user":        user,
        "settlement":  get_household_settlement(db, hh_id),
        "balances":    get_member_balances(db, hh_id),
        "history":     get_household_settlement_history(db, hh_id),
        "enabled_buckets": enabled_buckets,
    })
    return templates.TemplateResponse("settlement.html", ctx)


@router.post("/settlement/settle", response_class=HTMLResponse)
def settle_household(
    from_user_id: str = Form(""),
    to_user_id: str = Form(""),
    amount: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Record a household-wide payment.

    No arguments clears everything outstanding; from/to (with an optional
    amount) records one possibly-partial payment.
    """
    user, hh_id = auth

    payer = require_member(db, from_user_id, hh_id) if from_user_id else None
    payee = require_member(db, to_user_id, hh_id) if to_user_id else None
    if bool(payer) != bool(payee):
        raise HTTPException(status_code=400, detail="Both payer and payee are required.")
    if payer and payer == payee:
        raise HTTPException(status_code=400, detail="Payer and payee must differ.")

    value = parse_amount(amount, field="Amount", allow_blank=True)

    record_household_settlement(
        db, hh_id,
        created_by=user.id,
        from_user_id=payer,
        to_user_id=payee,
        amount=float(value) if value is not None else None,
        note=note.strip() or None,
    )
    db.commit()
    return RedirectResponse("/settlement", status_code=302)

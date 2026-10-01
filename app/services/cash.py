"""
Cash wallet ledger.

The ledger is independent of expenses: ``in`` is cash taken into the wallet (an
ATM withdrawal), ``out`` is cash given away or spent untracked. A cash-paid
*expense* (``transactions.payment_method = 'cash'``) never touches the wallet
balance; it only shows up in :func:`cash_comparison`, which sets what a member
withdrew against what they logged as cash spending.

Currency: movements live in the household currency. There is no FX source for
cash, so the routes force ``currency`` to the household default (the API rejects
a different one) and balances are plain sums of the stored amounts.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.clock import utcnow_naive
from app.models import CashMovement, PaymentMethod, Transaction, TransactionType
from app.money import ZERO, quantize
from app.services.money import base_amount_expr

KINDS = ("in", "out")


def add_movement(
    db: Session,
    household_id: str,
    user_id: str,
    kind: str,
    amount: Decimal,
    currency: str,
    movement_date: date,
    category_id: str | None = None,
    note: str | None = None,
) -> CashMovement:
    """Record a cash movement and commit. Callers validate membership/amount."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    mv = CashMovement(
        household_id=household_id, user_id=user_id, kind=kind,
        amount=amount, currency=currency, movement_date=movement_date,
        category_id=category_id or None, note=(note or "").strip() or None,
    )
    db.add(mv)
    db.commit()
    db.refresh(mv)
    return mv


def delete_movement(db: Session, movement: CashMovement) -> None:
    """Soft delete: the row stays, it just stops counting."""
    movement.deleted_at = utcnow_naive()
    db.commit()


def member_balances(db: Session, household_id: str) -> dict[str, Decimal]:
    """Cash on hand per member: sum(in) - sum(out), household currency."""
    rows = (
        db.query(CashMovement.user_id, CashMovement.kind, func.sum(CashMovement.amount))
        .filter(CashMovement.household_id == household_id, CashMovement.active())
        .group_by(CashMovement.user_id, CashMovement.kind)
        .all()
    )
    out: dict[str, Decimal] = {}
    for uid, kind, total in rows:
        total = Decimal(total or 0)
        out[uid] = out.get(uid, ZERO) + (total if kind == "in" else -total)
    return {uid: quantize(v) for uid, v in out.items()}


def list_movements(
    db: Session,
    household_id: str,
    member_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
) -> list[CashMovement]:
    q = db.query(CashMovement).filter(
        CashMovement.household_id == household_id, CashMovement.active()
    )
    if member_id:
        q = q.filter(CashMovement.user_id == member_id)
    if start:
        q = q.filter(CashMovement.movement_date >= start)
    if end:
        q = q.filter(CashMovement.movement_date <= end)
    return (
        q.order_by(CashMovement.movement_date.desc(), CashMovement.created_at.desc())
        .limit(limit)
        .all()
    )


def cash_comparison(
    db: Session,
    household_id: str,
    member_id: str,
    start: date | None,
    end: date | None,
) -> dict[str, Decimal]:
    """Withdrawals vs cash-paid expenses for one member over [start, end].

    ``unaccounted = withdrawn - ledger_out - cash_expenses``: cash that went in
    but is neither logged as given away nor as a cash-paid expense.
    """
    mq = db.query(func.coalesce(func.sum(CashMovement.amount), 0)).filter(
        CashMovement.household_id == household_id,
        CashMovement.user_id == member_id,
        CashMovement.active(),
    )
    if start:
        mq = mq.filter(CashMovement.movement_date >= start)
    if end:
        mq = mq.filter(CashMovement.movement_date <= end)
    withdrawn = Decimal(mq.filter(CashMovement.kind == "in").scalar() or 0)
    ledger_out = Decimal(mq.filter(CashMovement.kind == "out").scalar() or 0)

    eq = db.query(func.coalesce(func.sum(base_amount_expr()), 0)).filter(
        Transaction.household_id == household_id,
        Transaction.active(),
        Transaction.type == TransactionType.expense,
        Transaction.payment_method == PaymentMethod.cash.value,
        Transaction.paid_by == member_id,
    )
    if start:
        eq = eq.filter(Transaction.transaction_date >= start)
    if end:
        eq = eq.filter(Transaction.transaction_date <= end)
    cash_expenses = Decimal(eq.scalar() or 0)

    return {
        "withdrawn": quantize(withdrawn),
        "ledger_out": quantize(ledger_out),
        "cash_expenses": quantize(cash_expenses),
        "unaccounted": quantize(withdrawn - ledger_out - cash_expenses),
    }


def parse_month(raw: str | None) -> tuple[date, date, str]:
    """``YYYY-MM`` (default: the current local month) -> (first day, last day, normalised)."""
    from calendar import monthrange

    from app.clock import local_today

    if raw:
        try:
            y, m = (int(p) for p in raw.split("-"))
            first = date(y, m, 1)
        except (ValueError, TypeError):
            raise ValueError("Month must be YYYY-MM.") from None
    else:
        today = local_today()
        first = today.replace(day=1)
    last = first.replace(day=monthrange(first.year, first.month)[1])
    return first, last, first.strftime("%Y-%m")


def is_owner(db: Session, user_id: str, household_id: str) -> bool:
    from app.models import HouseholdMember, MemberRole

    return (
        db.query(HouseholdMember)
        .filter_by(user_id=user_id, household_id=household_id, role=MemberRole.owner)
        .first()
        is not None
    )


def can_manage_for(db: Session, actor_id: str, household_id: str, target_user_id: str) -> bool:
    """Members manage only their own movements; the owner manages anyone's."""
    return actor_id == target_user_id or is_owner(db, actor_id, household_id)

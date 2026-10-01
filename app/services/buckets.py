"""
Bucket summaries and typed bucket behaviour (trip/savings).
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.clock import local_today
from app.models import (
    Bucket,
    BucketType,
    HouseholdMember,
    Transaction,
    TransactionType,
    User,
)
from app.money import ZERO, percent, quantize, to_decimal
from app.services.insights import _month_range
from app.services.money import base_amount_expr, shares_for, split_to_base, to_base


def get_bucket_month_summary(db: Session, bucket_id: str, year: int, month: int) -> dict:
    """
    Who-paid breakdown for a single bucket in a given month.
    Returns total_spent, paid_by_detail, balances (same shape as get_month_summary).
    Members are derived from the bucket's household.
    """
    from app.models import Bucket
    bucket = db.get(Bucket, bucket_id)
    if not bucket:
        return {"total_spent": 0, "paid_by": {}, "balances": []}

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    txns = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.bucket_id == bucket_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .options(joinedload(Transaction.splits))
        .all()
    )

    total_spent = sum(to_base(t.amount, t.exchange_rate) for t in txns)

    # Amount paid by each user — use splits when present, else paid_by
    paid_by: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            paid_by[t.paid_by] += to_base(t.amount, t.exchange_rate)

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == bucket.household_id)
        .all()
    )
    member_map = {m.id: m for m in members}

    paid_by_detail = {}
    for uid, amount in paid_by.items():
        user = member_map.get(uid)
        if user:
            paid_by_detail[uid] = {
                "name": user.display_name,
                "color": user.avatar_color,
                "amount": quantize(amount),
            }

    return {
        "total_spent": quantize(total_spent),
        "paid_by": paid_by_detail,
        "period_start": start,
        "period_end": end,
    }


def get_bucket_balance(db: Session, bucket_id: str) -> dict:
    """Total income, expenses, and net for a bucket — single SQL aggregation query."""
    income_sum = func.coalesce(
        func.sum(case((Transaction.type == TransactionType.income, base_amount_expr()), else_=0)), 0
    )
    expense_sum = func.coalesce(
        func.sum(case((Transaction.type == TransactionType.expense, base_amount_expr()), else_=0)), 0
    )
    row = (
        db.query(income_sum, expense_sum)
        .filter(Transaction.active(), Transaction.bucket_id == bucket_id)
        .one()
    )
    income = to_decimal(row[0])
    expenses = to_decimal(row[1])
    return {
        "income": quantize(income),
        "expenses": quantize(expenses),
        "net": quantize(income - expenses),
    }


def get_bucket_spend_this_month(db: Session, household_id: str, year: int, month: int) -> dict[str, Decimal]:
    """Return {bucket_id: spend} for all active buckets in the given month."""
    start, end = _month_range(year, month)
    rows = (
        db.query(Transaction.bucket_id, func.sum(base_amount_expr()))
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .group_by(Transaction.bucket_id)
        .all()
    )
    return {bid: quantize(total) for bid, total in rows}


# ---------------------------------------------------------------------------
# Typed bucket behaviour
#
# BucketType.trip and BucketType.savings previously existed only as filter
# labels with no behaviour attached. These give each one the summary that makes
# the type worth choosing.
# ---------------------------------------------------------------------------

def get_trip_summary(db: Session, bucket: Bucket) -> dict:
    """Trip-shaped view of a bucket: duration, burn rate, per-person totals.

    Falls back to the first and last transaction dates when the trip has no
    explicit range, so an existing trip bucket is useful without being edited.
    """
    if bucket.type != BucketType.trip:
        return {}

    txns = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.bucket_id == bucket.id,
            Transaction.type == TransactionType.expense,
        )
        .options(joinedload(Transaction.splits))
        .all()
    )

    total = sum((to_base(t.amount, t.exchange_rate) for t in txns), ZERO)
    txn_dates = [t.transaction_date for t in txns if t.transaction_date]

    start = bucket.start_date or (min(txn_dates) if txn_dates else None)
    end = bucket.end_date or (max(txn_dates) if txn_dates else None)

    # Inclusive day count: 7 Aug to 15 Aug is 9 days and 8 nights. Both are
    # reported because "how long was the trip" is genuinely ambiguous, and the
    # per-day figure below divides by days.
    days = nights = None
    if start and end:
        days = (end - start).days + 1
        nights = max(days - 1, 0)

    today = local_today()
    status, days_until, days_remaining = "none", None, None
    if bucket.start_date and bucket.end_date:
        if today < bucket.start_date:
            status = "upcoming"
            days_until = (bucket.start_date - today).days
        elif today > bucket.end_date:
            status = "past"
        else:
            status = "active"
            days_remaining = (bucket.end_date - today).days + 1

    # Per-person share, using splits when present and the payer otherwise.
    # shares_for() accounts for the whole amount, so these add up to the trip
    # total even when splits only cover part of an expense.
    per_person: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        for uid, share in shares_for(t).items():
            per_person[uid] += share

    users = {}
    if per_person:
        users = {u.id: u for u in db.query(User).filter(User.id.in_(per_person)).all()}

    return {
        "total":          quantize(total),
        "start":          start,
        "end":            end,
        "days":           days,
        "nights":         nights,
        "per_day":        quantize(total / days) if days and days > 0 else None,
        "status":         status,
        "days_until":     days_until,
        "days_remaining": days_remaining,
        "budget":         to_decimal(bucket.budget) if bucket.budget else None,
        "remaining":      quantize(to_decimal(bucket.budget) - total) if bucket.budget else None,
        "transaction_count": len(txns),
        "per_person": sorted(
            (
                {
                    "user_id": uid,
                    "name":    users[uid].display_name if uid in users else "Unknown",
                    "color":   users[uid].avatar_color if uid in users else "#9ca3af",
                    "amount":  quantize(amount),
                }
                for uid, amount in per_person.items()
            ),
            key=lambda r: -r["amount"],
        ),
    }


def get_savings_summary(db: Session, bucket: Bucket) -> dict:
    """Savings-goal view: progress toward goal_amount and what it takes to get there."""
    if bucket.type != BucketType.savings:
        return {}

    balance = get_bucket_balance(db, bucket.id)
    saved = balance["net"]          # income minus expenses in this bucket
    goal = to_decimal(bucket.goal_amount) if bucket.goal_amount else None

    result = {
        "saved":     saved,
        "goal":      goal,
        "target_date": bucket.end_date,
        "income":    balance["income"],
        "expenses":  balance["expenses"],
    }
    if not goal or goal <= 0:
        result.update({"pct": None, "remaining": None, "per_month": None,
                       "months_left": None, "on_track": None, "reached": False})
        return result

    remaining = quantize(goal - saved)
    result["pct_actual"] = percent(saved, goal)
    result["pct"] = min(max(result["pct_actual"], 0), 100)
    result["remaining"] = remaining
    result["reached"] = saved >= goal

    months_left = None
    if bucket.end_date:
        today = local_today()
        months_left = max(
            (bucket.end_date.year - today.year) * 12 + (bucket.end_date.month - today.month),
            0,
        )
    result["months_left"] = months_left
    result["per_month"] = (
        quantize(remaining / months_left)
        if months_left and remaining > 0 else None
    )
    # Without a deadline there is nothing to be on track against.
    result["on_track"] = None if not bucket.end_date else (remaining <= 0 or bool(months_left))
    return result

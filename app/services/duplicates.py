"""
Duplicate transaction detection.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.clock import local_today
from app.core.money import quantize, to_decimal
from app.models import (
    Transaction,
    TransactionType,
)
from app.validators import parse_amount

# ---------------------------------------------------------------------------
# Duplicate detection
#
# The most common data-quality problem in a shared household tracker is both
# people logging the same dinner. These surface likely repeats rather than
# blocking them: a genuine repeat (two coffees the same day) is legitimate, so
# the decision stays with the user.
# ---------------------------------------------------------------------------

DUPLICATE_WINDOW_DAYS = 3
DUPLICATE_AMOUNT_TOLERANCE = Decimal("0.01")


def find_duplicate_candidates(
    db: Session,
    household_id: str,
    *,
    amount,
    transaction_date: date,
    bucket_id: str | None = None,
    exclude_id: str | None = None,
    window_days: int = DUPLICATE_WINDOW_DAYS,
) -> list[Transaction]:
    """Existing transactions that look like the one being entered.

    Same household, near-identical amount, within a few days. Bucket is a
    signal but not a requirement — two people often file the same expense in
    different buckets, which is exactly the case worth catching.
    """
    if amount is None or transaction_date is None:
        return []

    target = to_decimal(amount)
    lo, hi = target - DUPLICATE_AMOUNT_TOLERANCE, target + DUPLICATE_AMOUNT_TOLERANCE

    q = db.query(Transaction).filter(
        Transaction.active(),
        Transaction.household_id == household_id,
        Transaction.type == TransactionType.expense,
        Transaction.amount >= lo,
        Transaction.amount <= hi,
        Transaction.transaction_date >= transaction_date - timedelta(days=window_days),
        Transaction.transaction_date <= transaction_date + timedelta(days=window_days),
    )
    if exclude_id:
        q = q.filter(Transaction.id != exclude_id)
    if bucket_id:
        # Same-bucket matches first: a stronger signal than a cross-bucket one.
        q = q.order_by(
            (Transaction.bucket_id == bucket_id).desc(), Transaction.transaction_date.desc()
        )
    else:
        q = q.order_by(Transaction.transaction_date.desc())

    return (
        q.options(joinedload(Transaction.bucket), joinedload(Transaction.paid_by_user))
        .limit(5)
        .all()
    )


def find_household_duplicates(
    db: Session,
    household_id: str,
    *,
    since_days: int = 90,
    window_days: int = DUPLICATE_WINDOW_DAYS,
) -> list[dict]:
    """Scan recent history for clusters of transactions that look duplicated.

    Groups by rounded amount and walks each group by date, so a pair logged
    days apart is caught without comparing every row to every other row.
    """
    cutoff = local_today() - timedelta(days=since_days)
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= cutoff,
        )
        .options(joinedload(Transaction.bucket), joinedload(Transaction.paid_by_user))
        .order_by(Transaction.transaction_date)
        .all()
    )

    by_amount: dict[Decimal, list[Transaction]] = defaultdict(list)
    for t in txns:
        by_amount[quantize(t.amount)].append(t)

    groups: list[dict] = []
    for amount, rows in by_amount.items():
        if len(rows) < 2:
            continue
        cluster: list[Transaction] = []
        for t in rows:
            if cluster and (t.transaction_date - cluster[-1].transaction_date).days > window_days:
                if len(cluster) > 1:
                    groups.append({"amount": amount, "transactions": list(cluster)})
                cluster = []
            cluster.append(t)
        if len(cluster) > 1:
            groups.append({"amount": amount, "transactions": list(cluster)})

    groups.sort(key=lambda g: max(t.transaction_date for t in g["transactions"]), reverse=True)
    return groups


def duplicate_check(
    db: Session,
    household_id: str,
    *,
    amount: str,
    transaction_date: str,
    bucket_id: str = "",
    exclude_id: str = "",
) -> list[dict]:
    """The advisory "looks like one you already logged" check behind the
    add-expense form and the composer. Blank or malformed input gives no
    matches rather than an error: this check must never block a save."""
    try:
        value = parse_amount(amount, field="Amount", allow_blank=True)
        when = date.fromisoformat((transaction_date or "").strip())
    except (HTTPException, ValueError):
        return []
    if value is None:
        return []

    matches = find_duplicate_candidates(
        db,
        household_id,
        amount=value,
        transaction_date=when,
        bucket_id=bucket_id or None,
        exclude_id=exclude_id or None,
    )
    return [
        {
            "id": t.id,
            "amount": float(t.amount),
            "currency": t.currency,
            "date": t.transaction_date.isoformat(),
            "notes": t.notes,
            "merchant": t.merchant,
            "bucket": t.bucket.name if t.bucket else None,
            "paid_by": t.paid_by_user.display_name if t.paid_by_user else None,
            "same_bucket": bool(bucket_id) and t.bucket_id == bucket_id,
        }
        for t in matches
    ]

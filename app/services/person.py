"""
Per-person spending summary.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.models import (
    Bucket,
    Category,
    Transaction,
    TransactionType,
)
from app.money import TENTH, ZERO, quantize
from app.services.money import shares_for, to_base
from app.services.settlement import get_member_balances


def get_person_summary(
    db: Session,
    household_id: str,
    user_id: str,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """One member's own financial picture within the household.

    "My share" is what this person is actually responsible for: their split
    amount where the expense is shared, the full amount where they paid an
    unsplit expense. That differs from "what I paid out", and the gap between
    the two is what settlement resolves.
    """
    q = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
        )
        .options(joinedload(Transaction.splits), joinedload(Transaction.bucket))
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    txns = q.all()

    paid_out = ZERO      # money this person actually fronted
    my_share = ZERO      # what they are responsible for
    shared_count = 0
    by_bucket: dict[str, Decimal] = defaultdict(Decimal)
    by_category: dict[str | None, Decimal] = defaultdict(Decimal)
    by_month: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    household_total = ZERO
    largest = None

    for t in txns:
        amount = to_base(t.amount, t.exchange_rate)
        household_total += amount
        if t.paid_by == user_id:
            paid_out += amount

        # Splits win where they exist; an expense whose splits do not cover the
        # full amount leaves the remainder with whoever paid. Note this is not
        # identical to the settlement view, which additionally treats an unsplit
        # expense in a settlement-enabled bucket as shared equally — that is the
        # household convention there, and "net" below comes from that maths.
        share = shares_for(t).get(user_id, ZERO)
        if t.splits and any(s.user_id == user_id for s in t.splits):
            shared_count += 1

        if share:
            my_share += share
            by_bucket[t.bucket_id] += share
            by_category[t.category_id] += share
            if t.transaction_date:
                by_month[(t.transaction_date.year, t.transaction_date.month)] += share
            if largest is None or share > largest["amount"]:
                largest = {
                    "amount": share,
                    "notes":  t.notes,
                    "date":   t.transaction_date,
                }

    buckets = {}
    if by_bucket:
        buckets = {
            b.id: b for b in db.query(Bucket).filter(Bucket.id.in_(by_bucket)).all()
        }
    cat_ids = [c for c in by_category if c]
    categories = (
        {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}
        if cat_ids else {}
    )

    # Household-wide net position, reusing the settlement maths.
    net = next(
        (b["net"] for b in get_member_balances(db, household_id) if b["user_id"] == user_id),
        ZERO,
    )

    if largest:
        largest["amount"] = quantize(largest["amount"])

    return {
        "paid_out":  quantize(paid_out),
        "my_share":  quantize(my_share),
        # The gap between the two headline figures, for this period only. This
        # is what makes them legible: fronting EUR 600 against a EUR 400 share
        # means EUR 200 went out on someone else's behalf.
        "balance":   quantize(paid_out - my_share),
        # Positive: fronted more than their share. This is the settlement view.
        "net":       net,
        "household_total": quantize(household_total),
        # How much of the household's spending this person carries.
        "share_pct": quantize(my_share / household_total * 100, TENTH) if household_total else None,
        "largest":   largest,
        "trend": [
            {"label": date(y, m, 1).strftime("%b"), "total": quantize(v)}
            for (y, m), v in sorted(by_month.items())
        ],
        "shared_count": shared_count,
        "transaction_count": len(txns),
        "by_bucket": sorted(
            (
                {
                    "name":   buckets[bid].name if bid in buckets else "Unknown",
                    "icon":   buckets[bid].icon if bid in buckets else "🪣",
                    "color":  buckets[bid].color if bid in buckets else "#9ca3af",
                    "amount": quantize(amount),
                }
                for bid, amount in by_bucket.items()
            ),
            key=lambda r: -r["amount"],
        ),
        "by_category": sorted(
            (
                {
                    "name":   categories[cid].name if cid in categories else "Uncategorised",
                    "icon":   categories[cid].icon if cid in categories else "📦",
                    "color":  categories[cid].color if cid in categories else "#9ca3af",
                    "amount": quantize(amount),
                }
                for cid, amount in by_category.items()
            ),
            key=lambda r: -r["amount"],
        )[:8],
    }

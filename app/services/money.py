"""
Services-level money helpers: base-currency conversion and split shares.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from app.models import (
    Transaction,
)
from app.money import ZERO, to_decimal

# ---------------------------------------------------------------------------
# Currency normalisation
#
# Transaction.amount is stored in Transaction.currency; exchange_rate converts
# it to the household's default currency. The rate was captured and stored but
# never applied, so every total silently added raw amounts across currencies —
# a EUR 50 dinner and a USD 50 dinner summed to "100" of nothing. Aggregate
# base_amount, never amount.
# ---------------------------------------------------------------------------

def base_amount_expr():
    """SQL expression: transaction amount converted to the household currency."""
    return Transaction.amount * func.coalesce(Transaction.exchange_rate, 1)


def to_base(amount, exchange_rate) -> Decimal:
    """Python equivalent of :func:`base_amount_expr` for loaded ORM objects.

    Unrounded: callers sum first and :func:`app.money.quantize` the result.
    """
    if amount is None:
        return ZERO
    rate = 1 if exchange_rate is None else exchange_rate
    return to_decimal(amount) * to_decimal(rate)


def shares_for(txn, member_ids: set[str] | None = None) -> dict[str, Decimal]:
    """Who is responsible for how much of this expense, in household currency.

    Three cases, and the middle one is the reason this helper exists:

    * **Explicit splits covering the total** — each user takes their split.
    * **Explicit splits covering only part of it** — the payer absorbs the
      remainder. Logging a EUR 100 dinner as a single EUR 50 split for the
      other person is the natural way to record "you owe me half", but the
      other EUR 50 used to be attributed to nobody. Balances then failed to sum
      to zero, inflating the payer's credit and making the settle-up figures
      wrong.
    * **No splits** — divided equally among ``member_ids`` when given (the
      shared-bucket convention), otherwise borne entirely by the payer.

    The returned shares always sum to the transaction total, which is what
    guarantees household balances net to zero.
    """
    total = to_base(txn.amount, txn.exchange_rate)
    shares: dict[str, Decimal] = defaultdict(Decimal)

    if txn.splits:
        assigned = ZERO
        for s in txn.splits:
            value = split_to_base(s, txn)
            shares[s.user_id] += value
            assigned += value
        remainder = total - assigned
        if abs(remainder) > Decimal("0.005"):
            if txn.paid_by:
                shares[txn.paid_by] += remainder
            elif member_ids:
                per = remainder / len(member_ids)
                for uid in member_ids:
                    shares[uid] += per
        return dict(shares)

    if member_ids:
        per = total / len(member_ids)
        for uid in member_ids:
            shares[uid] += per
    elif txn.paid_by:
        shares[txn.paid_by] += total
    return dict(shares)


def split_to_base(split, txn) -> Decimal:
    """A split share converted to the household currency.

    Splits are denominated in the parent transaction's currency, so they take
    that transaction's rate.
    """
    return to_base(split.amount, txn.exchange_rate)

"""
Services-level money helpers: base-currency conversion and split shares.
"""

from collections import defaultdict
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func

from app.core.money import CENT, ZERO, to_decimal
from app.models import (
    PayerMode,
    Transaction,
)

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

    Unrounded: callers sum first and :func:`app.core.money.quantize` the result.
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


def shared_between(txn, split_members: dict | None) -> set[str] | None:
    """The ``member_ids`` settle-up passes to :func:`shares_for` / :func:`paid_for`
    for this expense, or None outside settle-up.

    ``split_members`` is :func:`app.services.settlement.settlement_members`.
    An expense takes part when its bucket settles up and it can create a debt
    (it has a payer or is own share, and is not excluded); there, an unsplit
    expense is shared equally, so every view that passes this agrees with
    settle-up about whose share it is.
    """
    if not split_members or getattr(txn, "exclude_from_settlement", False):
        return None
    if not (txn.paid_by or getattr(txn, "payer_mode", None) == PayerMode.own_share.value):
        return None
    return split_members.get(txn.bucket_id)


def share_of(txn, user_id: str, split_members: dict | None = None) -> Decimal:
    """One person's share of an expense (see :func:`shares_for`), zero if none.

    The single definition of "my share" used by the /me page and by the
    insights Person filter, so the two always report the same figures. Pass
    ``split_members`` (:func:`app.services.settlement.settlement_members`) to
    share unsplit expenses in settlement buckets as settle-up does.
    """
    return shares_for(txn, shared_between(txn, split_members)).get(user_id, ZERO)


def equal_split(total: Decimal, member_ids, payer: str | None = None) -> dict[str, Decimal]:
    """Divide ``total`` equally across ``member_ids``, to the cent.

    Each member gets ``total / n`` rounded down to the cent; the leftover cents
    go to the payer when they are one of the members, otherwise to the first
    member in id order, so the shares always add up to ``total`` exactly and
    the same input always gives the same split.
    """
    members = sorted(set(member_ids))
    if not members:
        return {}
    total = to_decimal(total)
    per = (total / len(members)).quantize(CENT, rounding=ROUND_DOWN)
    shares = {uid: per for uid in members}
    taker = payer if payer in shares else members[0]
    shares[taker] += total - per * len(members)
    return shares


def paid_for(txn, member_ids: set[str] | None = None) -> dict[str, Decimal]:
    """Who actually handed over how much of this expense, in household currency.

    The counterpart of :func:`shares_for` (who is *responsible* for what):

    * **single** — the payer fronted the whole amount. With no payer recorded
      nobody is credited, and the result is empty; callers report that money
      as "Unassigned".
    * **own_share** — every member paid their own split directly (rent paid
      800 / 300 straight to the landlord), so what each person paid *is* their
      share. ``member_ids`` is passed through so any unsplit remainder is
      spread exactly as :func:`shares_for` spreads it, which is what keeps
      settle-up at zero for these expenses.
    """
    if getattr(txn, "payer_mode", None) == PayerMode.own_share.value:
        return shares_for(txn, member_ids)
    if not txn.paid_by:
        return {}
    return {txn.paid_by: to_base(txn.amount, txn.exchange_rate)}


def split_to_base(split, txn) -> Decimal:
    """A split share converted to the household currency.

    Splits are denominated in the parent transaction's currency, so they take
    that transaction's rate.
    """
    return to_base(split.amount, txn.exchange_rate)

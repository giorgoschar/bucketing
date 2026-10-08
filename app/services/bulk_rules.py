"""Per-row rules of a bulk change (2c spec §5.4). Nothing here writes.

A row that can't take every requested change is skipped whole, with a code
and a reason (the bulk_set_payer pattern); a row that already holds the
targets is unchanged. app.services.bulk applies the plans.
"""

from dataclasses import dataclass

from app.models import PayerMode, PaymentMethod, Transaction, TransactionType
from app.schemas import own_share_problem

FIELDS = ("bucket", "category", "payer", "method")

CASH = PaymentMethod.cash.value
SINGLE = PayerMode.single.value
OWN_SHARE = PayerMode.own_share.value

BILL_KEEPS_BUCKET = "Bill payments keep a bucket; move the bill instead"
REASONS = {
    "deleted": "Deleted",
    "needs_bucket": "Expenses and transfers need a bucket",
    "income_bucket": "This bucket doesn't track income",
    "fuel_data": "Has fuel litres; edit it to change the category",
    "own_share_type": "Each paid their own share is only for expenses",
    "cash_take": "Cash was taken for it, so it stays cash and paid by whoever took it",
    "no_split": "Its shares don't add up to the amount",
    "cash_needs_payer": "Cash needs a payer; choose who paid too",
    # Undo (U1-U5)
    "deleted_since": "Deleted since",
    "changed_since": "Changed since",
    "target_gone": "Its old bucket, category or payer no longer exists",
}


@dataclass(frozen=True)
class Payer:
    mode: str  # a PayerMode value
    user_id: str | None = None


@dataclass(frozen=True)
class Changes:
    """What a bulk change sets. ``has_*`` tells "set to none" from "leave"."""

    has_bucket: bool = False
    bucket_id: str | None = None
    has_category: bool = False
    category_id: str | None = None
    payer: Payer | None = None
    payment_method: str | None = None

    @property
    def fields(self) -> tuple[str, ...]:
        on = (
            self.has_bucket,
            self.has_category,
            self.payer is not None,
            self.payment_method is not None,
        )
        return tuple(f for f, set_ in zip(FIELDS, on, strict=True) if set_)


@dataclass(frozen=True)
class RowContext:
    """What the rules need beyond the row, loaded once per batch."""

    takers: dict[str, str]  # transaction id -> whose wallet its active linked take went to
    fuel_category_id: str | None
    target_takes_income: bool  # the target bucket is active with "Track income" on


@dataclass(frozen=True)
class Skip:
    code: str
    reason: str


@dataclass(frozen=True)
class RowPlan:
    bucket_id: str | None
    category_id: str | None
    paid_by: str | None
    payer_mode: str
    payment_method: str
    changed: bool
    absorb_cent: bool = False  # own share: give the rounding cent to a split (R17)


def skip(code: str, reason: str | None = None) -> Skip:
    return Skip(code, reason or REASONS[code])


def plan_row(t: Transaction, ch: Changes, ctx: RowContext) -> RowPlan | Skip:
    """The new values for ``t``, or why it is skipped. Pure: reads only ``t``,
    ``ch`` and ``ctx``."""
    if t.deleted_at is not None:
        return skip("deleted")  # R2
    expense = t.type == TransactionType.expense
    income = t.type == TransactionType.income
    taker = ctx.takers.get(t.id)

    bucket_id = t.bucket_id
    if ch.has_bucket:
        bucket_id = ch.bucket_id
        if bucket_id is None and not income:
            fixed_cost = expense and t.recurring_bill_id is not None and t.bucket_id is None
            if not fixed_cost:
                if expense and t.recurring_bill_id is not None:
                    return skip("needs_bucket", BILL_KEEPS_BUCKET)  # R7
                return skip("needs_bucket")  # R6
        if (
            income
            and bucket_id is not None
            and bucket_id != t.bucket_id
            and not ctx.target_takes_income
        ):
            return skip("income_bucket")  # R4 (R5: income to None is fine)

    category_id = t.category_id
    if ch.has_category:
        category_id = ch.category_id
        if t.fuel_litres is not None and category_id != ctx.fuel_category_id:
            return skip("fuel_data")  # R19

    paid_by, payer_mode = t.paid_by, t.payer_mode or SINGLE
    absorb = False
    if ch.payer is not None:
        if ch.payer.mode == OWN_SHARE:
            if not expense:
                return skip("own_share_type")  # R16
            if taker is not None:
                return skip("cash_take")  # R13
            if payer_mode != OWN_SHARE:
                if own_share_problem(t.amount, (s.amount for s in t.splits)):
                    return skip("no_split")  # R17
                absorb = True
            paid_by, payer_mode = None, OWN_SHARE
        else:
            if taker is not None and taker != ch.payer.user_id:
                return skip("cash_take")  # R13
            paid_by, payer_mode = ch.payer.user_id, SINGLE

    method = t.payment_method
    if ch.payment_method is not None:
        method = ch.payment_method
        if taker is not None and method != CASH:
            return skip("cash_take")  # R14: the take is never dropped
        if method == CASH and t.payment_method != CASH and payer_mode == SINGLE and not paid_by:
            return skip("cash_needs_payer")  # R15

    changed = (bucket_id, category_id, paid_by, payer_mode, method) != (
        t.bucket_id,
        t.category_id,
        t.paid_by,
        t.payer_mode or SINGLE,
        t.payment_method,
    )
    return RowPlan(bucket_id, category_id, paid_by, payer_mode, method, changed, absorb)


# ---------------------------------------------------------------------- undo


@dataclass(frozen=True)
class UndoContext:
    takers: dict[str, str]
    bucket_ids: set[str]  # the household's buckets, archived included
    category_ids: set[str]
    member_ids: set[str]


def undo_problem(t: Transaction, row, fields: tuple[str, ...], ctx: UndoContext) -> Skip | None:
    """Why ``row`` (a BulkBatchRow) can't be restored on ``t``, if it can't.
    ``require_takes_income`` is not re-checked (U6)."""
    if t.deleted_at is not None:
        return skip("deleted_since")  # U1
    holds_new = {
        "bucket": t.bucket_id == row.new_bucket_id,
        "category": t.category_id == row.new_category_id,
        "payer": (t.paid_by, t.payer_mode) == (row.new_paid_by, row.new_payer_mode),
        "method": t.payment_method == row.new_payment_method,
    }
    if not all(holds_new[f] for f in fields):
        return skip("changed_since")  # U2
    if (
        ("bucket" in fields and row.old_bucket_id and row.old_bucket_id not in ctx.bucket_ids)
        or (
            "category" in fields
            and row.old_category_id
            and row.old_category_id not in ctx.category_ids
        )
        or ("payer" in fields and row.old_paid_by and row.old_paid_by not in ctx.member_ids)
    ):
        return skip("target_gone")  # U3
    if (
        "bucket" in fields
        and row.old_bucket_id is None
        and t.type != TransactionType.income
        and t.recurring_bill_id is None
    ):
        return skip("needs_bucket")  # U4: the item was deleted since (FK SET NULL)
    taker = ctx.takers.get(t.id)
    if taker is not None:  # U5 with R13 and R14
        if "payer" in fields and (row.old_payer_mode == OWN_SHARE or row.old_paid_by != taker):
            return skip("cash_take")
        if "method" in fields and row.old_payment_method != CASH:
            return skip("cash_take")
    if (
        "payer" in fields
        and row.old_payer_mode == OWN_SHARE
        and t.payer_mode != OWN_SHARE
        and own_share_problem(t.amount, (s.amount for s in t.splits))
    ):
        return skip("no_split")  # U5 with R17
    return None

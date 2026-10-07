"""
Recurring items: generating their expected entries (BillOccurrence rows) and
paying, receiving, undoing and skipping them.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import local_today
from app.core.schedule import MAX_INTERVAL_MONTHS, Rule, RuleKind, iter_entries, period_key
from app.models import (
    BillOccurrence,
    HouseholdMember,
    MemberRole,
    OccurrenceStatus,
    PayerMode,
    RecurringBill,
    Transaction,
    TransactionSplit,
    TransactionType,
)

# Entries exist from start_date to this many months from today; the daily
# planning job tops the window up (spec §3.3). Rows beyond it, left by the old
# 10-year generation, are kept.
HORIZON_MONTHS = 13

# What generate_occurrences does with a rule date before today:
PAST_UNPAID = "unpaid"  # an expected entry (the old behaviour; direct callers)
PAST_SKIPPED = "skipped"  # a skipped placeholder (the old app's forms)
PAST_NONE = "none"  # nothing (the new API and the daily top-up)

MAX_OCCURRENCES = 600  # hard ceiling on rows created per call


def normalise_interval_months(value: int | None) -> int:
    """Clamp interval_months into a sane range.

    A value of 0 or less would leave ``current`` unchanged on every iteration of
    the generation loop, hanging the worker in an infinite loop while inserting
    rows — reachable from any authenticated user via the bill form or the API.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1
    if value < 1:
        return 1
    return min(value, MAX_INTERVAL_MONTHS)


def horizon_end(today: date) -> date:
    """The last date the rolling horizon generates entries for."""
    return today + relativedelta(months=HORIZON_MONTHS)


def item_rule(bill: RecurringBill) -> Rule:
    """The schedule rule stored on ``bill`` (app.core.schedule)."""
    return Rule(
        kind=bill.rule_kind or "monthly_interval",
        interval_months=normalise_interval_months(bill.interval_months),
        day=bill.rule_day,
        month=bill.rule_month,
        adjust=bill.rule_adjust or "none",
        days=bill.rule_days,
        weekday=bill.rule_weekday,
        interval_weeks=bill.rule_interval_weeks or 1,
    )


def generate_occurrences(
    db: Session, bill: RecurringBill, *, today: date | None = None, past: str = PAST_UNPAID
) -> int:
    """Create the missing entries of ``bill`` from start_date to the horizon.

    Dates come from the shared rule engine, so both apps and the scheduler
    agree. end_date and total_occurrences count from start_date, whether or
    not a past date gets a row. Every entry carries its rule period (the
    month, ISO week or year before business-day adjustment, see
    app.core.schedule.period_key), and a period that already has a row of
    any status gets no second one (rows from before a change of rule kind
    block nothing, see _row_period). A rule edit therefore never doubles or
    drops a salary: paid on the 26th, the rule now says the 28th, that month
    stays as it is and the next month gets the 28th.
    ``past`` decides what a date before today becomes (PAST_UNPAID,
    PAST_SKIPPED or PAST_NONE); only PAST_UNPAID, kept for direct callers,
    creates expected entries before today. At most MAX_OCCURRENCES rows are
    created per call. Returns the rows created.

    Does not commit — the caller owns the transaction so that a bill and its
    occurrences are persisted atomically. Raises RuleError for a bad rule.
    """
    bill.interval_months = normalise_interval_months(bill.interval_months)
    today = today or local_today()
    rule = item_rule(bill)
    # The old app's forms generate through this same function, so its rows
    # get their period too; rows it wrote before the planning migration were
    # backfilled with their due month.
    taken = {
        _row_period(rule.kind, period, due)
        for due, period in db.query(BillOccurrence.due_date, BillOccurrence.period)
        .filter_by(bill_id=bill.id)
        .all()
    }
    taken.discard(None)  # rows of another kind's key format block nothing
    created = 0
    for due, period in iter_entries(
        rule,
        bill.start_date,
        end=bill.end_date,
        total=bill.total_occurrences,
        until=horizon_end(today),
    ):
        if created >= MAX_OCCURRENCES:
            break
        if period in taken:
            continue
        status = OccurrenceStatus.unpaid
        if due < today:
            if past == PAST_NONE:
                continue
            if past == PAST_SKIPPED:
                status = OccurrenceStatus.skipped
        # A SAVEPOINT keeps a duplicate-date collision from rolling back the
        # caller's whole transaction — a plain db.rollback() here used to
        # discard the not-yet-committed bill these rows point at.
        try:
            with db.begin_nested():
                db.add(
                    BillOccurrence(
                        bill_id=bill.id, due_date=due, amount=None, status=status, period=period
                    )
                )
                db.flush()
            created += 1
        except IntegrityError:
            pass
        taken.add(period)
    return created


def _key_format(kind_or_key: str) -> str:
    """ "week", "year" or "month": the format of a period key, or of the keys
    a rule kind produces (app.core.schedule.period_key)."""
    if kind_or_key == RuleKind.weekly.value or "-W" in kind_or_key:
        return "week"
    if kind_or_key in (RuleKind.yearly.value, RuleKind.easter_offset.value):
        return "year"
    if len(kind_or_key) == 4 and kind_or_key.isdigit():
        return "year"
    return "month"


def _row_period(kind: str, period: str | None, due: date) -> str | None:
    """The period an existing row blocks under a rule of ``kind``, or None.

    Rows the old app wrote have no key: they are monthly_interval entries,
    never adjusted, so their due month is their key. A row blocks only when
    its key has the format of the rule's keys. After a change of kind
    (monthly to yearly, weekly to monthly) the old rows block nothing: a
    missing future entry would go unnoticed, while a double is visible and
    can be skipped.
    """
    key = period or period_key(RuleKind.monthly_interval.value, due)
    return key if _key_format(key) == _key_format(kind) else None


def delete_future_occurrences(db: Session, bill_id: str) -> None:
    """Remove the future entries an edit may regenerate (spec §3.4.3).

    Only expected entries after today with no amount set and nothing linked:
    done and skipped entries, and entries whose amount the user set, are
    never touched. Does not commit — the caller owns the transaction.
    """
    today = local_today()
    db.query(BillOccurrence).filter(
        BillOccurrence.bill_id == bill_id,
        BillOccurrence.due_date > today,
        BillOccurrence.status == OccurrenceStatus.unpaid,
        BillOccurrence.amount.is_(None),
        BillOccurrence.transaction_id.is_(None),
    ).delete(synchronize_session=False)


def resolve_bill_payer(
    db: Session, bill: RecurringBill, fallback_user_id: str | None = None
) -> str | None:
    """Who pays a bill occurrence when no explicit payer was given.

    A bill expense without a payer is silently excluded from settle-up, so:
    the bill's default payer (if still a member) → ``fallback_user_id`` (the
    user paying it by hand) → the household owner. Bills have no creator
    column, so the owner stands in for "the bill's creator".
    """
    member_ids = {
        uid
        for (uid,) in db.query(HouseholdMember.user_id)
        .filter(HouseholdMember.household_id == bill.household_id)
        .all()
    }
    if bill.paid_by_default and bill.paid_by_default in member_ids:
        return bill.paid_by_default
    if fallback_user_id:
        return fallback_user_id
    owner = (
        db.query(HouseholdMember.user_id)
        .filter(
            HouseholdMember.household_id == bill.household_id,
            HouseholdMember.role == MemberRole.owner,
        )
        .order_by(HouseholdMember.joined_at)
        .first()
    )
    return owner[0] if owner else None


def bill_payer_mode(bill: RecurringBill) -> str:
    """The payer mode a payment of ``bill`` is recorded with by default.

    Own share needs the bill's default splits to say who paid what; a bill set
    to own share without any falls back to a single payer rather than saving a
    payment that nobody is credited with.
    """
    if bill.payer_mode == PayerMode.own_share.value and any(
        _dec(s.amount) > 0 for s in bill.splits
    ):
        return PayerMode.own_share.value
    return PayerMode.single.value


def resolve_bill_payment(
    db: Session,
    bill: RecurringBill,
    *,
    paid_by: str | None = None,
    payer_mode: str | None = None,
    fallback_user_id: str | None = None,
) -> tuple[str | None, str]:
    """``(paid_by, payer_mode)`` for paying an occurrence of ``bill``.

    An explicit ``payer_mode`` wins; an explicit payer means a single payer;
    otherwise the bill's own mode applies (see :func:`bill_payer_mode`). A
    single-payer payment without a payer goes through :func:`resolve_bill_payer`.
    Own share never has a payer.
    """
    mode = payer_mode or (PayerMode.single.value if paid_by else bill_payer_mode(bill))
    if mode == PayerMode.own_share.value:
        return None, mode
    return paid_by or resolve_bill_payer(db, bill, fallback_user_id), mode


BILL_HAS_HISTORY_MSG = (
    "This bill has payment history, so it can't be deleted — deleting it would "
    "erase those payments. Deactivate it instead (the pause toggle on the bill)."
)


def bill_has_payment_history(db: Session, bill_id: str) -> bool:
    """True if any occurrence was paid, or skipped with an amount recorded.

    Deleting such a bill would cascade away the only record of those payments
    (for bucketless bills the paid occurrence *is* the payment record).
    """
    return (
        db.query(BillOccurrence.id)
        .filter(
            BillOccurrence.bill_id == bill_id,
            (BillOccurrence.status == OccurrenceStatus.paid)
            | (
                (BillOccurrence.status == OccurrenceStatus.skipped)
                & BillOccurrence.amount.isnot(None)
            )
            | BillOccurrence.transaction_id.isnot(None),
        )
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Paying an occurrence
# ---------------------------------------------------------------------------

_CENT = Decimal("0.01")


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _q(value) -> Decimal:
    return _dec(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _scaled_splits(bill: RecurringBill, amount: Decimal, payer: str | None) -> dict[str, Decimal]:
    """Scale the bill's default splits to ``amount``; splits sum exactly to ``amount``.

    Each share is ``amount * share / sum(default shares)`` rounded half-up to the
    cent. The rounding remainder goes to the payer's split; if the payer has no
    default split it goes to the first split (ordered by user_id, so the result
    is deterministic).
    """
    rows = sorted(bill.splits, key=lambda s: s.user_id)
    total = sum((_dec(s.amount) for s in rows), Decimal(0))
    if not rows or total <= 0:
        return {}
    shares = {s.user_id: _q(amount * _dec(s.amount) / total) for s in rows}
    remainder = amount - sum(shares.values())
    if remainder:
        target = payer if payer in shares else rows[0].user_id
        shares[target] += remainder
    return shares


def claim_occurrence(
    db: Session, occ: BillOccurrence, *, paid_by: str | None, paid_on: datetime
) -> bool:
    """Atomically flip an unpaid occurrence to paid. False if someone else won.

    Does not commit. Callers that lose the claim should not write anything.
    """
    claimed = (
        db.query(BillOccurrence)
        .filter(
            BillOccurrence.id == occ.id,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.transaction_id.is_(None),
        )
        .update(
            {
                BillOccurrence.status: OccurrenceStatus.paid,
                BillOccurrence.paid_at: paid_on,
                BillOccurrence.paid_by: paid_by,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.refresh(occ)
        return False
    occ.status, occ.paid_at, occ.paid_by = OccurrenceStatus.paid, paid_on, paid_by
    return True


def pay_occurrence(
    db: Session,
    occ: BillOccurrence,
    *,
    amount,
    paid_by: str | None,
    paid_on: datetime,
    split_overrides: dict[str, Decimal] | None = None,
    note_prefix: str = "Bill",
    payment_method: str = "card",
    payer_mode: str = PayerMode.single.value,
) -> Transaction | None:
    """Mark ``occ`` paid and create its expense transaction, in one DB transaction.

    Returns None when the atomic claim fails (already paid). Raises ValueError
    if ``split_overrides`` do not sum to ``amount``, or for an own-share payment
    with no splits to record. Does not commit: the claim, the transaction and
    its splits succeed or fail together with the caller's commit. Bills without
    a bucket have no transaction — use settle_occurrence.

    ``payer_mode`` own_share records everyone as having paid their split (the
    overrides, else the bill's scaled defaults); the transaction and the
    occurrence then have no ``paid_by``.
    """
    bill = occ.bill
    amount = _q(amount)
    overrides = {uid: _q(v) for uid, v in (split_overrides or {}).items()}
    if overrides and sum(overrides.values()) != amount:
        raise ValueError(
            f"Split amounts ({sum(overrides.values())}) must sum to the amount paid ({amount})."
        )
    own_share = payer_mode == PayerMode.own_share.value
    if own_share:
        paid_by = None
    splits = overrides or _scaled_splits(bill, amount, paid_by)
    if own_share and not splits:
        raise ValueError(
            "Each paid their own share needs the bill's shares (or shares entered when paying)."
        )
    if not claim_occurrence(db, occ, paid_by=paid_by, paid_on=paid_on):
        return None

    txn = Transaction(
        bucket_id=bill.bucket_id,
        household_id=bill.household_id,
        amount=amount,
        currency=bill.currency,
        type=TransactionType.expense,
        paid_by=paid_by,
        payer_mode=PayerMode.own_share.value if own_share else PayerMode.single.value,
        category_id=bill.category_id,
        notes=f"{note_prefix}: {bill.name}",
        payment_method=payment_method,
        transaction_date=occ.due_date,
    )
    db.add(txn)
    db.flush()
    db.query(BillOccurrence).filter(BillOccurrence.id == occ.id).update(
        {BillOccurrence.transaction_id: txn.id}, synchronize_session=False
    )
    occ.transaction_id = txn.id

    for uid, share in splits.items():
        db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=share))
    return txn


def settle_occurrence(db: Session, occ: BillOccurrence, **kwargs) -> bool:
    """pay_occurrence for bills with a bucket, a bare claim for bills without.

    Returns False when the occurrence was already paid.
    """
    if occ.bill.bucket_id:
        return pay_occurrence(db, occ, **kwargs) is not None
    paid_by = None if kwargs.get("payer_mode") == PayerMode.own_share.value else kwargs["paid_by"]
    return claim_occurrence(db, occ, paid_by=paid_by, paid_on=kwargs["paid_on"])


def effective_overrides(bill: RecurringBill, submitted) -> dict[str, Decimal] | None:
    """Treat submitted shares identical to the bill's defaults as "no override".

    The pay form prefills the bill's default shares, so an untouched form
    submits them verbatim; those must be scaled to the amount actually paid
    rather than validated as an override. Returns None for "use defaults".
    """
    shares = {uid: _q(v) for uid, v in dict(submitted or {}).items()}
    if not shares:
        return None
    defaults = {s.user_id: _q(s.amount) for s in bill.splits}
    return None if shares == defaults else shares


# ---------------------------------------------------------------------------
# Repairing past payments
# ---------------------------------------------------------------------------


class PayerBackfill(NamedTuple):
    """What :func:`backfill_bill_payer` changed."""

    updated: int  # transactions given a payer (or made own share)
    resplit: int  # of those, own-share rows whose own splits were replaced


def backfill_bill_payer(db: Session, bill: RecurringBill) -> PayerBackfill:
    """Give this bill's past payments with no payer the bill's current payer.

    Payments made before bills recorded a payer were saved with ``paid_by``
    NULL, so insights showed them as "Unassigned" and settle-up skipped them.
    Only active expense transactions linked to one of *this* bill's
    occurrences, single mode and without a payer, are touched:

    * single bill — the payer becomes ``paid_by_default`` (if still a member),
      on the transaction and its occurrence. No default payer: nothing to do.
    * own-share bill — the transaction becomes own share. Splits that already
      add up to its amount are kept (a cent of rounding goes to the largest,
      see :func:`app.schemas.absorb_own_share_cent`); otherwise the bill's
      default splits, scaled to that amount, replace them. Own share needs
      splits that cover the whole amount, so splits that do not (the old
      "you owe me 300" pattern) cannot be kept as they are; those rows are
      counted in ``resplit`` so the caller can say so. A bill without splits:
      nothing to do.

    Does not commit.
    """
    own_share = bill.payer_mode == PayerMode.own_share.value
    payer = None
    if own_share:
        if bill_payer_mode(bill) != PayerMode.own_share.value:
            return PayerBackfill(0, 0)
    else:
        member_ids = {
            uid
            for (uid,) in db.query(HouseholdMember.user_id)
            .filter(HouseholdMember.household_id == bill.household_id)
            .all()
        }
        payer = bill.paid_by_default if bill.paid_by_default in member_ids else None
        if not payer:
            return PayerBackfill(0, 0)

    rows = (
        db.query(Transaction, BillOccurrence)
        .join(BillOccurrence, BillOccurrence.transaction_id == Transaction.id)
        .filter(
            BillOccurrence.bill_id == bill.id,
            Transaction.household_id == bill.household_id,
            Transaction.active(),
            Transaction.type == TransactionType.expense,
            Transaction.missing_payer(),
        )
        .all()
    )
    from app.schemas import absorb_own_share_cent

    resplit = 0
    for txn, occ in rows:
        if not own_share:
            txn.paid_by = payer
            if occ.paid_by is None:
                occ.paid_by = payer
            continue
        amount = _q(txn.amount)
        existing = sum((_dec(s.amount) for s in txn.splits), Decimal(0))
        if txn.splits and abs(existing - amount) <= _CENT:
            absorb_own_share_cent(amount, txn.splits)
        else:
            resplit += bool(txn.splits)
            db.query(TransactionSplit).filter_by(transaction_id=txn.id).delete(
                synchronize_session=False
            )
            db.expire(txn, ["splits"])
            for uid, share in _scaled_splits(bill, amount, None).items():
                db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=share))
        txn.payer_mode = PayerMode.own_share.value
    return PayerBackfill(len(rows), resplit)

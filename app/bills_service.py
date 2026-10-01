"""
Generate BillOccurrence rows for a RecurringBill.
Called when a bill is created or updated.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clock import local_today
from app.models import (
    BillOccurrence,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionSplit,
    TransactionType,
)

# Guard rails for open-ended bills.
MAX_INTERVAL_MONTHS = 120   # 10 years between occurrences
MAX_OCCURRENCES = 600       # hard ceiling on rows generated per bill
HORIZON_YEARS = 10


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


def generate_occurrences(db: Session, bill: RecurringBill) -> None:
    """
    Create all BillOccurrence rows for a bill from start_date going forward.
    Respects end_date and total_occurrences limits.
    Skips dates that already have an occurrence.

    Does not commit — the caller owns the transaction so that a bill and its
    occurrences are persisted atomically.
    """
    bill.interval_months = normalise_interval_months(bill.interval_months)

    existing_dates = {
        row.due_date for row in
        db.query(BillOccurrence.due_date).filter_by(bill_id=bill.id).all()
    }

    horizon = date(local_today().year + HORIZON_YEARS, 12, 31)
    current = bill.start_date
    count = 0

    while count < MAX_OCCURRENCES:
        # Stop conditions
        if bill.total_occurrences and count >= bill.total_occurrences:
            break
        if bill.end_date and current > bill.end_date:
            break
        # Don't generate more than HORIZON_YEARS out for open-ended bills
        if current > horizon:
            break

        if current not in existing_dates:
            # A SAVEPOINT keeps a duplicate-date collision from rolling back the
            # caller's whole transaction — a plain db.rollback() here used to
            # discard the not-yet-committed bill these rows point at.
            try:
                with db.begin_nested():
                    db.add(BillOccurrence(
                        bill_id=bill.id,
                        due_date=current,
                        amount=None,  # will use bill.amount unless variable
                        status=OccurrenceStatus.unpaid,
                    ))
                    db.flush()
            except IntegrityError:
                pass
            existing_dates.add(current)

        count += 1
        current = current + relativedelta(months=bill.interval_months)


def delete_future_occurrences(db: Session, bill_id: str) -> None:
    """Remove all unpaid future occurrences (used when editing a bill).

    Does not commit — the caller owns the transaction.
    """
    today = local_today()
    db.query(BillOccurrence).filter(
        BillOccurrence.bill_id == bill_id,
        BillOccurrence.due_date > today,
        BillOccurrence.status == OccurrenceStatus.unpaid,
    ).delete(synchronize_session=False)


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


def claim_occurrence(db: Session, occ: BillOccurrence, *, paid_by: str | None,
                     paid_on: datetime) -> bool:
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
) -> Transaction | None:
    """Mark ``occ`` paid and create its expense transaction, in one DB transaction.

    Returns None when the atomic claim fails (already paid). Raises ValueError
    if ``split_overrides`` do not sum to ``amount``. Does not commit: the claim,
    the transaction and its splits succeed or fail together with the caller's
    commit. Bills without a bucket have no transaction — use settle_occurrence.
    """
    bill = occ.bill
    amount = _q(amount)
    overrides = {uid: _q(v) for uid, v in (split_overrides or {}).items()}
    if overrides and sum(overrides.values()) != amount:
        raise ValueError(
            f"Split amounts ({sum(overrides.values())}) must sum to the amount paid ({amount})."
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

    for uid, share in (overrides or _scaled_splits(bill, amount, paid_by)).items():
        db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=share))
    return txn


def settle_occurrence(db: Session, occ: BillOccurrence, **kwargs) -> bool:
    """pay_occurrence for bills with a bucket, a bare claim for bills without.

    Returns False when the occurrence was already paid.
    """
    if occ.bill.bucket_id:
        return pay_occurrence(db, occ, **kwargs) is not None
    return claim_occurrence(db, occ, paid_by=kwargs["paid_by"], paid_on=kwargs["paid_on"])


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

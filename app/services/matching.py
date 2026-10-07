"""Match suggestions (spec §3.5): an expense or income that looks like an
expected entry of a recurring item.

Suggestions only: nothing is linked until someone taps Link. A suggestion
needs the same direction (expense <-> out, income <-> in), a transaction
date from 3 days before to 7 days after the due date, and either an amount
within 15% of a known amount (50% of a variable item's estimate) or a
merchant/description that contains the item's name (case- and
accent-insensitive). One open suggestion per transaction: the closest entry.
"""

import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.clock import utcnow_naive
from app.core.money import quantize, to_decimal
from app.models import (
    BillOccurrence,
    ItemDirection,
    MatchSuggestion,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionType,
)
from app.services.bills import (
    EntryStateError,
    _link_transaction,
    claim_occurrence,
    estimate_amount,
)
from app.services.money import to_base

EARLY_DAYS = 3  # paid up to 3 days before the due date
LATE_DAYS = 7  # ... or up to 7 days after it
FIXED_TOLERANCE = Decimal("0.15")
VARIABLE_TOLERANCE = Decimal("0.50")
RECENT_DAYS = 14  # the daily pass looks this far back
MIN_NAME_LENGTH = 3  # shorter names match too much


def normalise_text(value: str | None) -> str:
    """Case- and accent-insensitive form: "ΔΕΉ Online" -> "δεη online"."""
    decomposed = unicodedata.normalize("NFD", value or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(stripped.casefold().split())


def names_similar(item_name: str, txn: Transaction) -> bool:
    """The item's name appears in the merchant or notes, or the merchant in the name."""
    name = normalise_text(item_name)
    if len(name) < MIN_NAME_LENGTH:
        return False
    merchant = normalise_text(txn.merchant)
    text = normalise_text(f"{txn.merchant or ''} {txn.notes or ''}")
    return name in text or (len(merchant) >= MIN_NAME_LENGTH and merchant in name)


def _expected(db: Session, occ: BillOccurrence, estimates: dict) -> tuple[Decimal | None, Decimal]:
    """(amount the entry expects, tolerance) — the set amount, the item's, or the estimate."""
    if occ.amount is not None:
        return to_decimal(occ.amount), FIXED_TOLERANCE
    if occ.bill.amount is not None:
        return to_decimal(occ.bill.amount), FIXED_TOLERANCE
    if occ.bill_id not in estimates:
        estimates[occ.bill_id] = estimate_amount(db, occ.bill_id)
    return estimates[occ.bill_id], VARIABLE_TOLERANCE


def _is_linked(db: Session, txn: Transaction) -> bool:
    return (
        txn.recurring_bill_id is not None
        or db.query(BillOccurrence.id).filter(BillOccurrence.transaction_id == txn.id).first()
        is not None
    )


def find_match(db: Session, txn: Transaction) -> BillOccurrence | None:
    """The expected entry ``txn`` most likely pays or receives, or None.

    None too when ``txn`` is deleted, already linked, or already has a
    still-valid open suggestion (a stale one does not block). Pairs suggested before (dismissed or not) are not offered
    again. The closest due date wins, then the closest amount.
    """
    if txn.deleted_at is not None or txn.type not in (
        TransactionType.expense,
        TransactionType.income,
    ):
        return None
    if _is_linked(db, txn):
        return None
    tried = {
        occ_id: dismissed
        for occ_id, dismissed in db.query(
            MatchSuggestion.occurrence_id, MatchSuggestion.dismissed
        ).filter(MatchSuggestion.transaction_id == txn.id)
    }
    if _open_query(db).filter(MatchSuggestion.transaction_id == txn.id).first() is not None:
        return None  # a still-valid suggestion is already waiting for a tap
    direction = (
        ItemDirection.in_.value if txn.type == TransactionType.income else ItemDirection.out.value
    )
    candidates = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == txn.household_id,
            RecurringBill.active_filter(),
            RecurringBill.direction == direction,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.transaction_id.is_(None),
            BillOccurrence.due_date >= txn.transaction_date - timedelta(days=LATE_DAYS),
            BillOccurrence.due_date <= txn.transaction_date + timedelta(days=EARLY_DAYS),
        )
        .all()
    )
    actual = to_base(txn.amount, txn.exchange_rate)
    estimates: dict = {}
    scored = []
    for occ in candidates:
        if occ.id in tried:
            continue
        expected, tolerance = _expected(db, occ, estimates)
        amount_ok = (
            expected is not None and expected > 0 and abs(actual - expected) <= expected * tolerance
        )
        if not (amount_ok or names_similar(occ.bill.name, txn)):
            continue
        gap = abs((txn.transaction_date - occ.due_date).days)
        miss = abs(actual - expected) if expected is not None else actual
        scored.append((gap, miss, occ.due_date, occ.id, occ))
    return min(scored)[-1] if scored else None


def suggest_for_transaction(db: Session, txn: Transaction) -> MatchSuggestion | None:
    """Record a suggestion for ``txn`` when an expected entry fits. Does not commit."""
    occ = find_match(db, txn)
    if occ is None:
        return None
    suggestion = MatchSuggestion(
        household_id=txn.household_id, transaction_id=txn.id, occurrence_id=occ.id
    )
    try:
        with db.begin_nested():
            db.add(suggestion)
            db.flush()
    except IntegrityError:
        return None
    return suggestion


def suggest_recent(db: Session, today: date, *, household_id: str | None = None) -> int:
    """The daily pass over the last 14 days of unlinked transactions. Commits."""
    q = db.query(Transaction).filter(
        Transaction.active(),
        Transaction.type.in_([TransactionType.expense, TransactionType.income]),
        Transaction.recurring_bill_id.is_(None),
        Transaction.transaction_date >= today - timedelta(days=RECENT_DAYS),
    )
    if household_id:
        q = q.filter(Transaction.household_id == household_id)
    made = sum(suggest_for_transaction(db, txn) is not None for txn in q.all())
    db.commit()
    return made


def _open_query(db: Session):
    """Suggestions still waiting for a tap: not dismissed, the transaction
    still there and unlinked, the entry still expected on an active item."""
    return (
        db.query(MatchSuggestion)
        .join(Transaction, Transaction.id == MatchSuggestion.transaction_id)
        .join(BillOccurrence, BillOccurrence.id == MatchSuggestion.occurrence_id)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .filter(
            MatchSuggestion.dismissed.is_(False),
            Transaction.active(),
            Transaction.recurring_bill_id.is_(None),
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.transaction_id.is_(None),
            RecurringBill.active_filter(),
        )
    )


def open_suggestions(db: Session, household_id: str) -> list[MatchSuggestion]:
    """Suggestions still waiting for a tap (see ``_open_query``), by due date."""
    return (
        _open_query(db)
        .options(
            joinedload(MatchSuggestion.transaction),
            joinedload(MatchSuggestion.occurrence).joinedload(BillOccurrence.bill),
        )
        .filter(MatchSuggestion.household_id == household_id)
        .order_by(BillOccurrence.due_date, MatchSuggestion.created_at)
        .all()
    )


def link_suggestion(db: Session, suggestion: MatchSuggestion) -> BillOccurrence:
    """Link (spec §3.5): the entry becomes done with this transaction, which
    gets ``recurring_bill_id``. A variable item's entry takes the amount.

    Raises EntryStateError when either side has moved on (dismissed, deleted,
    linked elsewhere, done or skipped). Does not commit.
    """
    txn, occ = suggestion.transaction, suggestion.occurrence
    if suggestion.dismissed:
        raise EntryStateError("This suggestion was dismissed.")
    if txn.deleted_at is not None:
        raise EntryStateError("That transaction was deleted.")
    if _is_linked(db, txn):
        raise EntryStateError("That transaction is already linked to a recurring item.")
    if not claim_occurrence(db, occ, paid_by=txn.paid_by, paid_on=utcnow_naive()):
        raise EntryStateError("That entry is already done or skipped.")
    _link_transaction(db, occ, txn)
    txn.recurring_bill_id = occ.bill_id
    if occ.amount is None and occ.bill.amount is None:
        occ.amount = quantize(to_base(txn.amount, txn.exchange_rate))
    return occ


def dismiss_suggestion(suggestion: MatchSuggestion) -> None:
    """Not this: the pair is never suggested again. Does not commit."""
    suggestion.dismissed = True

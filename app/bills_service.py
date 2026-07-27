"""
Generate BillOccurrence rows for a RecurringBill.
Called when a bill is created or updated.
"""
from datetime import date
from dateutil.relativedelta import relativedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import BillOccurrence, RecurringBill, OccurrenceStatus

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

    horizon = date(date.today().year + HORIZON_YEARS, 12, 31)
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
    today = date.today()
    db.query(BillOccurrence).filter(
        BillOccurrence.bill_id == bill_id,
        BillOccurrence.due_date > today,
        BillOccurrence.status == OccurrenceStatus.unpaid,
    ).delete(synchronize_session=False)

"""
Generate BillOccurrence rows for a RecurringBill.
Called when a bill is created or updated.
"""
from datetime import date
from dateutil.relativedelta import relativedelta

from sqlalchemy.orm import Session

from app.models import BillOccurrence, RecurringBill, OccurrenceStatus


def generate_occurrences(db: Session, bill: RecurringBill):
    """
    Create all BillOccurrence rows for a bill from start_date going forward.
    Respects end_date and total_occurrences limits.
    Skips dates that already have an occurrence.
    """
    existing_dates = {
        o.due_date for o in
        db.query(BillOccurrence.due_date).filter_by(bill_id=bill.id).all()
    }

    current = bill.start_date
    count = 0

    while True:
        # Stop conditions
        if bill.total_occurrences and count >= bill.total_occurrences:
            break
        if bill.end_date and current > bill.end_date:
            break
        # Don't generate more than 10 years out for open-ended bills
        if current > date(date.today().year + 10, 12, 31):
            break

        if current not in existing_dates:
            db.add(BillOccurrence(
                bill_id=bill.id,
                due_date=current,
                amount=None,  # will use bill.amount unless variable
                status=OccurrenceStatus.unpaid,
            ))

        count += 1
        current = current + relativedelta(months=bill.interval_months)

    db.commit()


def delete_future_occurrences(db: Session, bill_id: str):
    """Remove all unpaid future occurrences (used when editing a bill)."""
    today = date.today()
    db.query(BillOccurrence).filter(
        BillOccurrence.bill_id == bill_id,
        BillOccurrence.due_date > today,
        BillOccurrence.status == OccurrenceStatus.unpaid,
    ).delete()
    db.commit()

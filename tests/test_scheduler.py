"""
Scheduler regression tests.

These cover the duplicate auto-pay bug: `entrypoint.sh` runs
`uvicorn --workers 2`, and every worker starts its own BackgroundScheduler, so
the daily job and the startup catch-up job can run concurrently and repeatedly.
"""
import threading
from datetime import date, timedelta

import pytest

from app.models import (
    BillOccurrence, Notification, OccurrenceStatus, Transaction,
)


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    """Run the real scheduler job against the test database."""
    import app.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def test_autopay_creates_one_transaction(db, make_household, make_bill, run_job):
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)

    run_job()

    txns = db.query(Transaction).all()
    assert len(txns) == 1
    assert float(txns[0].amount) == 45.0
    occ = db.query(BillOccurrence).one()
    assert occ.status == OccurrenceStatus.paid
    assert occ.transaction_id == txns[0].id


def test_autopay_is_idempotent_across_reruns(db, make_household, make_bill, run_job):
    """Server restarts fire the catch-up job again; it must not re-charge."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)

    for _ in range(5):
        run_job()

    assert db.query(Transaction).count() == 1
    assert db.query(Notification).count() == 1


def test_autopay_is_safe_under_concurrent_workers(db, make_household, make_bill, run_job):
    """The regression: two workers entering the job simultaneously.

    Before the fix this produced two transactions and double-charged the
    household.
    """
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=800, paid_by=hh.user_id)

    barrier = threading.Barrier(2)
    errors = []

    def worker():
        try:
            barrier.wait()
            run_job()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    txns = db.query(Transaction).all()
    assert len(txns) == 1, f"double-charged: {[float(t.amount) for t in txns]}"
    assert sum(float(t.amount) for t in txns) == 800.0


def test_variable_bill_without_amount_is_not_paid(db, make_household, make_bill, run_job):
    """A variable bill with no amount anywhere needs manual entry."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=None, paid_by=hh.user_id)

    run_job()

    assert db.query(Transaction).count() == 0
    assert db.query(BillOccurrence).one().status == OccurrenceStatus.unpaid


def test_variable_bill_uses_preset_occurrence_amount(db, make_household, make_bill, run_job):
    """Standing-order mode: the amount set on the occurrence is used."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=None, occ_amount=73.5,
              paid_by=hh.user_id)

    run_job()

    txn = db.query(Transaction).one()
    assert float(txn.amount) == 73.5


def test_future_bills_are_not_paid_early(db, make_household, make_bill, run_job):
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45,
              due=date.today() + timedelta(days=5), paid_by=hh.user_id)

    run_job()

    assert db.query(Transaction).count() == 0


def test_inactive_bill_is_skipped(db, make_household, make_bill, run_job):
    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)
    bill.is_active = False
    db.commit()

    run_job()

    assert db.query(Transaction).count() == 0


def test_overdue_reminder_does_not_repeat(db, make_household, make_bill, run_job):
    """An overdue bill used to re-notify on every run, forever."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=30, auto_pay=False,
              due=date.today() - timedelta(days=3))

    for _ in range(4):
        run_job()

    overdue = db.query(Notification).filter(
        Notification.title.like("Overdue%")
    ).all()
    assert len(overdue) == 1


def test_overdue_reminder_repeats_at_next_milestone(db, make_household, make_bill, run_job):
    """Distinct milestones (3 then 7 days late) are separate reminders."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=30, auto_pay=False,
              due=date.today() - timedelta(days=3))
    run_job()

    # Move the due date so "today" is now 7 days past it.
    occ = db.query(BillOccurrence).one()
    occ.due_date = date.today() - timedelta(days=7)
    db.commit()
    run_job()

    overdue = db.query(Notification).filter(Notification.title.like("Overdue%")).all()
    assert len(overdue) == 2


def test_due_soon_notification_is_sent_once(db, make_household, make_bill, run_job):
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=30, auto_pay=False,
              due=date.today() + timedelta(days=3))

    run_job()
    run_job()

    due = db.query(Notification).filter(Notification.title.like("Bill due%")).all()
    assert len(due) == 1


def test_job_survives_a_bill_with_no_amount_in_notification(db, make_household, make_bill, run_job):
    """A None amount used to raise TypeError formatting the notification body."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=None, auto_pay=False,
              due=date.today() + timedelta(days=3))

    run_job()  # must not raise

    due = db.query(Notification).filter(Notification.title.like("Bill due%")).all()
    assert len(due) == 1
    assert "Amount not set" in (due[0].body or "")


def test_bill_splits_are_copied_onto_the_transaction(db, make_household, make_bill, run_job):
    from app.models import RecurringBillSplit, TransactionSplit

    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=100, paid_by=hh.user_id)
    db.add(RecurringBillSplit(bill_id=bill.id, user_id=hh.user_id, amount=100))
    db.commit()

    run_job()

    splits = db.query(TransactionSplit).all()
    assert len(splits) == 1
    assert float(splits[0].amount) == 100.0

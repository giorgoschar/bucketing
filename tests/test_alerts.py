"""Bill drift and budget threshold alerts."""
from datetime import date, timedelta

import pytest

from app.models import (
    BillOccurrence, Bucket, Notification, NotificationType, OccurrenceStatus,
    RecurringBill, Transaction, TransactionType,
)


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _variable_bill(db, household_id, bucket_id, amounts, *, name="Electricity",
                   currency="EUR"):
    """A variable bill with one paid occurrence per amount, monthly, most recent last."""
    bill = RecurringBill(
        household_id=household_id, bucket_id=bucket_id, name=name,
        amount=None, currency=currency, start_date=date.today(),
        interval_months=1, is_auto_pay=False, is_active=True,
    )
    db.add(bill)
    db.flush()
    n = len(amounts)
    for i, amount in enumerate(amounts):
        db.add(BillOccurrence(
            bill_id=bill.id,
            due_date=date.today() - timedelta(days=30 * (n - 1 - i)),
            amount=amount,
            status=OccurrenceStatus.paid,
        ))
    db.commit()
    return bill


def _drift_notifications(db):
    return db.query(Notification).filter(
        Notification.type == NotificationType.bill_drift
    ).all()


def _budget_notifications(db):
    return db.query(Notification).filter(
        Notification.type == NotificationType.budget_warning
    ).all()


# ---------------------------------------------------------------------------
# Bill drift
# ---------------------------------------------------------------------------

def test_spike_is_reported(db, authed, run_job):
    _variable_bill(db, authed.household_id, authed.bucket_id, [50, 52, 48, 90])
    run_job()

    notes = _drift_notifications(db)
    assert len(notes) == 1
    assert "up" in notes[0].title
    assert "Electricity" in notes[0].title


def test_drop_is_reported(db, authed, run_job):
    _variable_bill(db, authed.household_id, authed.bucket_id, [100, 98, 102, 40])
    run_job()

    notes = _drift_notifications(db)
    assert len(notes) == 1
    assert "down" in notes[0].title


def test_stable_bill_is_quiet(db, authed, run_job):
    _variable_bill(db, authed.household_id, authed.bucket_id, [50, 51, 49, 52])
    run_job()
    assert _drift_notifications(db) == []


def test_small_absolute_change_is_quiet(db, authed, run_job):
    """A 40% jump on a tiny bill is noise, not signal."""
    _variable_bill(db, authed.household_id, authed.bucket_id, [3, 3, 3, 4.2])
    run_job()
    assert _drift_notifications(db) == []


def test_insufficient_history_is_quiet(db, authed, run_job):
    _variable_bill(db, authed.household_id, authed.bucket_id, [50, 200])
    run_job()
    assert _drift_notifications(db) == []


def test_fixed_bill_never_drifts(db, authed, run_job):
    """A fixed bill has no per-occurrence amounts, so there is nothing to compare."""
    bill = RecurringBill(
        household_id=authed.household_id, bucket_id=authed.bucket_id,
        name="Rent", amount=800, currency="EUR", start_date=date.today(),
        interval_months=1, is_active=True, is_auto_pay=False,
    )
    db.add(bill)
    db.flush()
    for i in range(5):
        db.add(BillOccurrence(bill_id=bill.id,
                              due_date=date.today() - timedelta(days=30 * i),
                              status=OccurrenceStatus.paid))
    db.commit()

    run_job()
    assert _drift_notifications(db) == []


def test_stale_charge_is_not_reanalysed(db, authed, run_job):
    """A bill that last charged months ago must not be re-flagged forever.

    The whole series is aged, not just the newest row — moving one occurrence
    back would reorder the history and change which charge counts as latest.
    """
    bill = _variable_bill(db, authed.household_id, authed.bucket_id, [50, 52, 48, 90])
    for occ in db.query(BillOccurrence).filter_by(bill_id=bill.id).all():
        occ.due_date -= timedelta(days=200)
    db.commit()

    run_job()
    assert _drift_notifications(db) == []


def test_drift_alert_does_not_repeat(db, authed, run_job):
    _variable_bill(db, authed.household_id, authed.bucket_id, [50, 52, 48, 90])
    for _ in range(4):
        run_job()
    assert len(_drift_notifications(db)) == 1


def test_inactive_bill_is_skipped(db, authed, run_job):
    bill = _variable_bill(db, authed.household_id, authed.bucket_id, [50, 52, 48, 90])
    bill.is_active = False
    db.commit()

    run_job()
    assert _drift_notifications(db) == []


# ---------------------------------------------------------------------------
# Budget thresholds
# ---------------------------------------------------------------------------

def _spend(db, authed, amount):
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date.today(),
    ))
    db.commit()


def test_no_warning_below_threshold(db, authed, run_job):
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    _spend(db, authed, 50)

    run_job()
    assert _budget_notifications(db) == []


def test_warning_at_80_percent(db, authed, run_job):
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    _spend(db, authed, 85)

    run_job()
    notes = _budget_notifications(db)
    assert len(notes) == 1
    assert "85%" in notes[0].title


def test_over_budget_warning(db, authed, run_job):
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    _spend(db, authed, 130)

    run_job()
    notes = _budget_notifications(db)
    assert len(notes) == 1
    assert "over budget" in notes[0].title


def test_only_the_highest_threshold_fires(db, authed, run_job):
    """Crossing straight past 80 to 100 should not produce two notices at once."""
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    _spend(db, authed, 150)

    run_job()
    assert len(_budget_notifications(db)) == 1


def test_crossing_a_second_threshold_later_notifies_again(db, authed, run_job):
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    _spend(db, authed, 85)
    run_job()
    assert len(_budget_notifications(db)) == 1

    _spend(db, authed, 40)   # now 125% — a genuinely new state
    run_job()
    assert len(_budget_notifications(db)) == 2


def test_budget_warning_does_not_repeat(db, authed, run_job):
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    _spend(db, authed, 90)

    for _ in range(4):
        run_job()
    assert len(_budget_notifications(db)) == 1


def test_bucket_without_budget_is_ignored(db, authed, run_job):
    _spend(db, authed, 5000)
    run_job()
    assert _budget_notifications(db) == []


def test_budget_warning_respects_exchange_rate(db, authed, run_job):
    """Spend is converted before comparison, matching every other total."""
    db.get(Bucket, authed.bucket_id).budget = 100
    db.commit()
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=180, currency="USD", exchange_rate=0.5,  # = 90 base
        type=TransactionType.expense, transaction_date=date.today(),
    ))
    db.commit()

    run_job()
    notes = _budget_notifications(db)
    assert len(notes) == 1
    assert "90%" in notes[0].title

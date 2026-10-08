"""Auto-pay settles an entry at most once: a deleted or undone auto-payment is
not re-created the next night (final review I1). An auto-pay entry the job
missed is nagged about like any overdue bill (T4)."""

from datetime import timedelta

import pytest

from app.core.clock import local_today
from app.models import BillOccurrence, Notification, OccurrenceStatus, Transaction
from app.services import delete_transaction
from app.services.bills import complete_entry, undo_occurrence


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _live(db) -> int:
    return db.query(Transaction).filter(Transaction.deleted_at.is_(None)).count()


def test_deleted_autopay_payment_is_not_recreated(db, make_household, make_bill, run_job):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=50, due=local_today() - timedelta(1))
    run_job()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.paid and occ.auto_paid_at is not None
    # The user deletes it as a duplicate of the real card charge.
    delete_transaction(db, db.get(Transaction, occ.transaction_id))
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.unpaid and occ.auto_paid_at is not None
    run_job()  # the next night
    db.expire_all()
    assert _live(db) == 0
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_undo_keeping_the_autopay_expense_does_not_double(db, make_household, make_bill, run_job):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=50, due=local_today() - timedelta(1))
    run_job()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    undo_occurrence(db, occ)  # keep the expense
    db.commit()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).auto_paid_at is not None
    run_job()
    db.expire_all()
    assert _live(db) == 1
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_undone_claim_only_autopay_is_not_claimed_again(db, make_household, make_bill, run_job):
    hh = make_household()
    _, occ = make_bill(hh.household_id, None, amount=50, due=local_today())
    run_job()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.paid and occ.transaction_id is None
    undo_occurrence(db, occ)
    db.commit()
    run_job()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_the_entry_can_still_be_paid_by_hand(db, make_household, make_bill, run_job):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=50, due=local_today() - timedelta(1))
    run_job()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    delete_transaction(db, db.get(Transaction, occ.transaction_id))
    db.expire_all()
    complete_entry(db, db.get(BillOccurrence, occ.id), user_id=hh.user_id)
    db.commit()
    assert _live(db) == 1


def test_a_manual_payment_is_not_marked_auto_paid(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=50, due=local_today())
    complete_entry(db, occ, user_id=hh.user_id)
    db.commit()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).auto_paid_at is None


def _overdue_keys(db) -> set[str]:
    return {
        n.dedupe_key
        for n in db.query(Notification)
        if n.dedupe_key and n.dedupe_key.startswith("bill_overdue:")
    }


def test_a_missed_autopay_entry_gets_the_later_overdue_reminders(
    db, make_household, make_bill, run_job
):
    hh = make_household()
    today = local_today()
    # No amount: auto-pay cannot pay these, so they stay expected.
    _, late = make_bill(hh.household_id, hh.bucket_id, amount=None, due=today - timedelta(7))
    _, fresh = make_bill(
        hh.household_id, hh.bucket_id, amount=None, due=today - timedelta(3), name="Power"
    )
    run_job()
    db.expire_all()
    # 7 days late is past the 3-day auto-pay window; 3 days late is still in it.
    assert _overdue_keys(db) == {f"bill_overdue:{late.id}:7"}
    assert db.get(BillOccurrence, fresh.id).status == OccurrenceStatus.unpaid

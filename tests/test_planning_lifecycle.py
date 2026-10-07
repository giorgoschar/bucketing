"""Entry lifecycle (spec §3.3): undo done or skipped, a deleted payment
reopens its entry, set amount, the "≈" estimate."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, Transaction
from app.services import delete_transaction
from app.services.bills import (
    EntryStateError,
    estimate_amount,
    pay_occurrence,
    set_entry_amount,
    skip_entry,
    undo_occurrence,
)


def _paid(db, hh, make_bill, **kw):
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=45, auto_pay=False, **kw)
    txn = pay_occurrence(db, occ, amount=45, paid_by=hh.user_id, paid_on=utcnow_naive())
    db.commit()
    return bill, occ, txn


def test_undo_done_keeps_the_expense_but_unlinks_it(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _paid(db, hh, make_bill)
    undo_occurrence(db, occ)
    db.commit()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.unpaid and occ.transaction_id is None
    kept = db.get(Transaction, txn.id)
    assert kept.deleted_at is None and kept.recurring_bill_id is None


def test_undo_done_can_delete_the_expense(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _paid(db, hh, make_bill)
    undo_occurrence(db, occ, delete_transaction=True)
    db.expire_all()
    assert db.get(Transaction, txn.id).deleted_at is not None
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_undo_skipped_and_undo_expected(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    skip_entry(occ)
    undo_occurrence(db, occ)
    assert occ.status == OccurrenceStatus.unpaid
    with pytest.raises(EntryStateError):
        undo_occurrence(db, occ)


def test_a_done_entry_cannot_be_skipped(db, make_household, make_bill):
    hh = make_household()
    _, occ, _ = _paid(db, hh, make_bill)
    with pytest.raises(EntryStateError):
        skip_entry(occ)


def test_soft_deleting_the_payment_reopens_the_entry(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _paid(db, hh, make_bill)
    delete_transaction(db, txn)
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.unpaid
    assert occ.transaction_id is None and occ.paid_at is None


def test_deleting_through_the_old_ui_reopens_the_entry(client, db, authed, make_bill):
    _, occ, txn = _paid(db, authed, make_bill)
    r = client.post(f"/transactions/{txn.id}/delete", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_set_amount_only_on_expected_entries(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=None, auto_pay=False)
    set_entry_amount(occ, Decimal("61.456"))
    assert occ.amount == Decimal("61.46")
    occ.status = OccurrenceStatus.skipped
    with pytest.raises(EntryStateError):
        set_entry_amount(occ, Decimal("1"))


def test_estimate_is_the_mean_of_the_last_three_done_amounts(db, make_household, make_bill):
    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=None, occurrence=False)
    assert estimate_amount(db, bill.id) is None
    today = local_today()
    for months_ago, amount in ((4, 500), (3, 60), (2, 70), (1, 80)):
        db.add(
            BillOccurrence(
                bill_id=bill.id,
                due_date=today - timedelta(days=30 * months_ago),
                amount=Decimal(amount),
                status=OccurrenceStatus.paid,
            )
        )
    db.commit()
    assert estimate_amount(db, bill.id) == Decimal("70.00")

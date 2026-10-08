"""2d §7.0: a recurring item's payment method is what Pay, Mark received and
auto-pay record when nobody picks one; an explicit method wins."""

from datetime import timedelta

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, RecurringBill, Transaction
from app.services.bills import complete_entry, pay_occurrence


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _income_item(db, hh, *, method=None):
    item = RecurringBill(
        household_id=hh.household_id,
        name="Salary",
        amount=1500,
        currency="EUR",
        start_date=local_today(),
        direction="in",
        rule_kind="monthly_interval",
    )
    if method:
        item.payment_method = method
    db.add(item)
    db.flush()
    occ = BillOccurrence(bill_id=item.id, due_date=local_today(), status=OccurrenceStatus.unpaid)
    db.add(occ)
    db.commit()
    return item, occ


def test_model_default_follows_direction(db, make_household, make_bill):
    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, occurrence=False)
    item, _ = _income_item(db, hh)
    assert (bill.payment_method, item.payment_method) == ("card", "transfer")


def test_pay_uses_the_bills_method_unless_one_is_sent(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    bill.payment_method = "transfer"
    db.commit()
    txn = pay_occurrence(db, occ, amount=45, paid_by=hh.user_id, paid_on=utcnow_naive())
    assert txn.payment_method == "transfer"

    occ2 = BillOccurrence(
        bill_id=bill.id, due_date=local_today() + timedelta(days=31), status=OccurrenceStatus.unpaid
    )
    db.add(occ2)
    db.flush()
    txn2 = pay_occurrence(
        db, occ2, amount=45, paid_by=hh.user_id, paid_on=utcnow_naive(), payment_method="cash"
    )
    assert txn2.payment_method == "cash"


def test_complete_entry_out_uses_the_items_method(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, None, auto_pay=False)  # a Fixed cost
    bill.payment_method = "apple_pay"
    db.commit()
    txn = complete_entry(db, occ, user_id=hh.user_id)
    assert txn.payment_method == "apple_pay"


def test_complete_entry_explicit_method_wins(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    bill.payment_method = "transfer"
    db.commit()
    txn = complete_entry(db, occ, user_id=hh.user_id, payment_method="card")
    assert txn.payment_method == "card"


def test_mark_received_records_the_items_method(db, make_household):
    hh = make_household()
    item, occ = _income_item(db, hh)
    assert complete_entry(db, occ, user_id=hh.user_id).payment_method == "transfer"

    other, occ2 = _income_item(db, hh, method="cash")
    occ2.due_date = local_today() + timedelta(days=1)
    db.commit()
    assert complete_entry(db, occ2, user_id=hh.user_id).payment_method == "cash"


def test_mark_received_explicit_method_wins(db, make_household):
    hh = make_household()
    _, occ = _income_item(db, hh)
    txn = complete_entry(db, occ, user_id=hh.user_id, payment_method="other")
    assert txn.payment_method == "other"


def test_auto_pay_records_the_bills_method(db, make_household, make_bill, run_job):
    hh = make_household()
    bill, occ = make_bill(
        hh.household_id, hh.bucket_id, amount=50, due=local_today() - timedelta(1)
    )
    bill.payment_method = "transfer"
    db.commit()
    run_job()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.paid
    assert db.get(Transaction, occ.transaction_id).payment_method == "transfer"

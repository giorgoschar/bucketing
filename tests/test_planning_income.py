"""Income items: Mark received creates and links an income (spec §3.1, §3.3, §5.5)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, Transaction, TransactionType
from app.services import delete_transaction, get_insights_income
from app.services.bills import receive_occurrence, undo_occurrence
from tests.test_household_settlement import _add_member


def _salary(db, make_bill, hh, **kw):
    bill, occ = make_bill(hh.household_id, None, amount=1500, auto_pay=False, name="Salary", **kw)
    bill.direction = "in"
    db.commit()
    return bill, occ


def test_mark_received_creates_linked_bucketless_income(db, make_household, make_bill):
    hh = make_household()
    partner = _add_member(db, hh.household_id, "partner")
    bill, occ = _salary(db, make_bill, hh, paid_by=partner.id)

    txn = receive_occurrence(
        db, occ, amount=Decimal("1500"), received_by=None, paid_on=utcnow_naive()
    )
    db.commit()

    assert txn.type == TransactionType.income and txn.bucket_id is None
    assert txn.recurring_bill_id == bill.id and txn.paid_by == partner.id
    assert txn.transaction_date == occ.due_date
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.paid and occ.transaction_id == txn.id


def test_received_income_counts_for_the_person_who_received_it(db, make_household, make_bill):
    hh = make_household()
    partner = _add_member(db, hh.household_id, "partner")
    _, occ = _salary(db, make_bill, hh)
    receive_occurrence(db, occ, amount=1500, received_by=partner.id, paid_on=utcnow_naive())
    db.commit()
    day = occ.due_date
    assert get_insights_income(db, hh.household_id, day, day, paid_by=partner.id) == Decimal(
        "1500.00"
    )
    assert get_insights_income(db, hh.household_id, day, day, paid_by=hh.user_id) == Decimal("0.00")


def test_receiving_twice_creates_one_income(db, make_household, make_bill):
    hh = make_household()
    _, occ = _salary(db, make_bill, hh)
    assert receive_occurrence(db, occ, amount=1500, received_by=None, paid_on=utcnow_naive())
    db.commit()
    assert (
        receive_occurrence(db, occ, amount=1500, received_by=None, paid_on=utcnow_naive()) is None
    )
    assert db.query(Transaction).count() == 1


def test_an_out_item_cannot_be_received(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    with pytest.raises(ValueError):
        receive_occurrence(db, occ, amount=45, received_by=None, paid_on=utcnow_naive())


def test_undo_and_delete_reopen_an_income_entry(db, make_household, make_bill):
    hh = make_household()
    _, occ = _salary(db, make_bill, hh, due=local_today() - timedelta(days=1))
    txn = receive_occurrence(db, occ, amount=1500, received_by=None, paid_on=utcnow_naive())
    db.commit()
    undo_occurrence(db, occ)  # keeps the income, unlinked
    db.commit()
    db.expire_all()
    assert db.get(Transaction, txn.id).recurring_bill_id is None
    occ = db.get(BillOccurrence, occ.id)
    txn2 = receive_occurrence(db, occ, amount=1400, received_by=None, paid_on=utcnow_naive())
    db.commit()
    delete_transaction(db, txn2)
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid

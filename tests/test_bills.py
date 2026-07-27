"""Recurring bills: occurrence generation, paying, skipping."""
from datetime import date, timedelta

import pytest

from app.bills_service import generate_occurrences, normalise_interval_months
from app.models import (
    BillOccurrence, OccurrenceStatus, RecurringBill, Transaction,
)


# ---------------------------------------------------------------------------
# Occurrence generation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (1, 1), (3, 3), (12, 12),
    (0, 1),       # would never advance the loop -> infinite loop
    (-5, 1),
    (None, 1),
    ("x", 1),
    (99999, 120),  # clamped to the 10-year ceiling
])
def test_interval_months_is_clamped(raw, expected):
    assert normalise_interval_months(raw) == expected


def test_zero_interval_does_not_hang(db, make_household):
    """interval_months=0 used to spin forever while inserting rows."""
    hh = make_household()
    bill = RecurringBill(
        household_id=hh.household_id, name="Loop", amount=10, currency="EUR",
        start_date=date(2026, 1, 1), interval_months=0, total_occurrences=5,
    )
    db.add(bill)
    db.flush()

    generate_occurrences(db, bill)
    db.commit()

    occs = db.query(BillOccurrence).filter_by(bill_id=bill.id).all()
    assert 0 < len(occs) <= 5


def test_generate_respects_total_occurrences(db, make_household):
    hh = make_household()
    bill = RecurringBill(
        household_id=hh.household_id, name="Gym", amount=30, currency="EUR",
        start_date=date(2026, 1, 1), interval_months=1, total_occurrences=6,
    )
    db.add(bill)
    db.flush()
    generate_occurrences(db, bill)
    db.commit()
    assert db.query(BillOccurrence).filter_by(bill_id=bill.id).count() == 6


def test_generate_respects_end_date(db, make_household):
    hh = make_household()
    bill = RecurringBill(
        household_id=hh.household_id, name="Course", amount=30, currency="EUR",
        start_date=date(2026, 1, 1), end_date=date(2026, 4, 30), interval_months=1,
    )
    db.add(bill)
    db.flush()
    generate_occurrences(db, bill)
    db.commit()
    occs = db.query(BillOccurrence).filter_by(bill_id=bill.id).all()
    assert len(occs) == 4
    assert max(o.due_date for o in occs) <= date(2026, 4, 30)


def test_generate_is_idempotent(db, make_household):
    hh = make_household()
    bill = RecurringBill(
        household_id=hh.household_id, name="Rent", amount=800, currency="EUR",
        start_date=date(2026, 1, 1), interval_months=1, total_occurrences=12,
    )
    db.add(bill)
    db.flush()
    generate_occurrences(db, bill)
    db.commit()
    generate_occurrences(db, bill)
    db.commit()
    assert db.query(BillOccurrence).filter_by(bill_id=bill.id).count() == 12


def test_bill_survives_occurrence_generation(client, db, authed):
    """A duplicate-date rollback inside generation used to discard the bill."""
    r = client.post("/bills", data={
        "name": "Netflix", "amount": "15.99", "currency": "EUR",
        "start_date": "2026-01-01", "interval_months": "1",
        "frequency": "monthly", "total_occurrences": "12",
        "bucket_id": authed.bucket_id,
    }, headers=authed.headers)
    assert r.status_code == 302

    bill = db.query(RecurringBill).one()
    assert bill.name == "Netflix"
    assert db.query(BillOccurrence).filter_by(bill_id=bill.id).count() == 12


# ---------------------------------------------------------------------------
# Paying
# ---------------------------------------------------------------------------

def test_pay_creates_one_transaction(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=45,
                          auto_pay=False, paid_by=authed.user_id)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                    data={}, headers=authed.headers)
    assert r.status_code in (200, 302)

    assert db.query(Transaction).count() == 1
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid


def test_paying_twice_does_not_double_charge(client, db, authed, make_bill):
    """A double-click used to create a second transaction and orphan the first."""
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=45,
                          auto_pay=False, paid_by=authed.user_id)

    for _ in range(3):
        client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                    data={}, headers=authed.headers)

    txns = db.query(Transaction).all()
    assert len(txns) == 1, f"double-charged: {[float(t.amount) for t in txns]}"
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).transaction_id == txns[0].id


def test_pay_uses_preset_occurrence_amount(client, db, authed, make_bill):
    """Variable bill with a pre-set occurrence amount must not demand an amount."""
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=None,
                          occ_amount=88.25, auto_pay=False, paid_by=authed.user_id)

    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                    data={}, headers=authed.headers)
    assert r.status_code in (200, 302)
    assert float(db.query(Transaction).one().amount) == 88.25


def test_pay_variable_bill_without_amount_is_rejected(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=None,
                          auto_pay=False, paid_by=authed.user_id)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                    data={}, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_cannot_skip_a_paid_occurrence(client, db, authed, make_bill):
    """Skipping a paid occurrence would strand its transaction."""
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=45,
                          auto_pay=False, paid_by=authed.user_id)
    client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                data={}, headers=authed.headers)

    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/skip", headers=authed.headers)
    assert r.status_code == 400
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid


def test_skip_marks_unpaid_occurrence(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=45,
                          auto_pay=False)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/skip", headers=authed.headers)
    assert r.status_code in (200, 302)
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.skipped


def test_set_amount_on_paid_occurrence_is_rejected(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=45,
                          auto_pay=False, paid_by=authed.user_id)
    client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                data={}, headers=authed.headers)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/set-amount",
                    data={"amount": "5"}, headers=authed.headers)
    assert r.status_code == 400


def test_bad_start_date_returns_400(client, authed):
    r = client.post("/bills", data={
        "name": "Bad", "amount": "10", "start_date": "not-a-date",
        "interval_months": "1", "frequency": "monthly",
    }, headers=authed.headers)
    assert r.status_code == 400


def test_split_must_sum_to_bill_amount(client, db, authed):
    r = client.post("/bills", data={
        "name": "Shared", "amount": "100", "start_date": "2026-01-01",
        "interval_months": "1", "frequency": "monthly",
        f"split_{authed.user_id}": "40",
    }, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(RecurringBill).count() == 0

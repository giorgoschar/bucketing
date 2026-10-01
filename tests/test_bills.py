"""Recurring bills: occurrence generation, paying, skipping."""
from datetime import date

import pytest

from app.bills_service import generate_occurrences, normalise_interval_months
from app.models import (
    BillOccurrence,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
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


# ---------------------------------------------------------------------------
# pay_occurrence service: scaled splits, atomic claim
# ---------------------------------------------------------------------------

def _bill_with_splits(db, authed, make_bill, split_amounts, *, bill_amount, **kw):
    """Bill whose default splits are `split_amounts` (owner first, then new members)."""
    from decimal import Decimal

    from app.models import RecurringBillSplit
    from tests.test_household_settlement import _add_member

    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=bill_amount,
                          auto_pay=kw.pop("auto_pay", False), paid_by=authed.user_id, **kw)
    users = [authed.user_id]
    for i in range(len(split_amounts) - 1):
        users.append(_add_member(db, authed.household_id, f"splitter{bill.id[:6]}{i}").id)
    for uid, amt in zip(users, split_amounts, strict=True):
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=uid, amount=Decimal(str(amt))))
    db.commit()
    return bill, occ, users


def _split_map(db, txn):
    from decimal import Decimal

    from app.models import TransactionSplit
    return {s.user_id: Decimal(s.amount)
            for s in db.query(TransactionSplit).filter_by(transaction_id=txn.id)}


def test_variable_bill_splits_scale_to_paid_amount(db, authed, make_bill):
    from decimal import Decimal

    from app.bills_service import pay_occurrence
    from app.clock import utcnow_naive

    bill, occ, users = _bill_with_splits(db, authed, make_bill, [50, 50], bill_amount=100)
    txn = pay_occurrence(db, occ, amount=Decimal("80"), paid_by=authed.user_id,
                         paid_on=utcnow_naive())
    db.commit()
    assert txn is not None and txn.deleted_at is None
    assert _split_map(db, txn) == {users[0]: Decimal("40"), users[1]: Decimal("40")}


def test_uneven_split_remainder_goes_to_payer(db, authed, make_bill):
    from decimal import Decimal

    from app.bills_service import pay_occurrence
    from app.clock import utcnow_naive

    # 1/3 each of 100 -> 33.33 / 33.33 / 33.33 = 99.99; the payer absorbs the cent.
    bill, occ, u = _bill_with_splits(db, authed, make_bill, [1, 1, 1], bill_amount=3)
    txn = pay_occurrence(db, occ, amount=Decimal("100"), paid_by=u[2],
                         paid_on=utcnow_naive())
    db.commit()
    s = _split_map(db, txn)
    assert s[u[0]] == s[u[1]] == Decimal("33.33")
    assert s[u[2]] == Decimal("33.34")
    assert sum(s.values()) == Decimal("100.00")


def test_split_overrides_must_sum_to_amount(db, authed, make_bill):
    from decimal import Decimal

    from app.bills_service import pay_occurrence
    from app.clock import utcnow_naive

    bill, occ, users = _bill_with_splits(db, authed, make_bill, [50, 50], bill_amount=100)
    with pytest.raises(ValueError):
        pay_occurrence(db, occ, amount=Decimal("100"), paid_by=users[0],
                       paid_on=utcnow_naive(),
                       split_overrides={users[0]: Decimal("10"), users[1]: Decimal("10")})
    db.rollback()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_second_pay_of_same_occurrence_is_a_noop(db, authed, make_bill):
    from decimal import Decimal

    from app.bills_service import pay_occurrence
    from app.clock import utcnow_naive

    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=45,
                          auto_pay=False, paid_by=authed.user_id)
    first = pay_occurrence(db, occ, amount=Decimal("45"), paid_by=authed.user_id,
                           paid_on=utcnow_naive())
    db.commit()
    second = pay_occurrence(db, occ, amount=Decimal("45"), paid_by=authed.user_id,
                            paid_on=utcnow_naive())
    db.commit()
    assert first is not None and second is None
    assert db.query(Transaction).count() == 1


def test_auto_pay_job_uses_scaled_service_path(db, authed, make_bill, monkeypatch, SessionLocal):
    """Scheduler auto-pay creates the transaction through pay_occurrence."""
    import app.bills_service as bs
    import app.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    calls = []
    real = bs.pay_occurrence
    monkeypatch.setattr(bs, "pay_occurrence",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    bill, occ, users = _bill_with_splits(db, authed, make_bill, [50, 50], bill_amount=100,
                                         auto_pay=True, occ_amount=80)
    scheduler.auto_mark_paid_job()
    db.expire_all()
    assert calls
    txn = db.query(Transaction).one()
    assert sorted(float(s.amount) for s in txn.splits) == [40.0, 40.0]


# ---------------------------------------------------------------------------
# HTML pay form: prefilled default shares are not overrides
# ---------------------------------------------------------------------------

def _pay_form(client, authed, bill, occ, data):
    return client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                       data=data, headers=authed.headers, follow_redirects=False)


def test_pay_form_with_default_shares_scales_to_amount(client, db, authed, make_bill):
    from decimal import Decimal
    bill, occ, users = _bill_with_splits(db, authed, make_bill, [50, 50], bill_amount=100)
    r = _pay_form(client, authed, bill, occ, {
        "amount": "80", f"split_{users[0]}": "50.00", f"split_{users[1]}": "50"})
    assert r.status_code in (200, 302)
    db.expire_all()
    txn = db.query(Transaction).one()
    assert _split_map(db, txn) == {users[0]: Decimal("40"), users[1]: Decimal("40")}


def test_pay_form_edited_shares_used_as_is(client, db, authed, make_bill):
    from decimal import Decimal
    bill, occ, users = _bill_with_splits(db, authed, make_bill, [50, 50], bill_amount=100)
    r = _pay_form(client, authed, bill, occ, {
        "amount": "80", f"split_{users[0]}": "70", f"split_{users[1]}": "10"})
    assert r.status_code in (200, 302)
    db.expire_all()
    txn = db.query(Transaction).one()
    assert _split_map(db, txn) == {users[0]: Decimal("70"), users[1]: Decimal("10")}


def test_pay_form_edited_shares_not_summing_is_400(client, db, authed, make_bill):
    bill, occ, users = _bill_with_splits(db, authed, make_bill, [50, 50], bill_amount=100)
    r = _pay_form(client, authed, bill, occ, {
        "amount": "80", f"split_{users[0]}": "70", f"split_{users[1]}": "20"})
    assert r.status_code == 400
    assert "80" in r.text
    db.expire_all()
    assert db.query(Transaction).count() == 0
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_pay_modal_js_rescales_shares_on_amount_change():
    from pathlib import Path
    html = Path("templates/bills/list.html").read_text()
    assert "rescalePayShares" in html and "shareEdited" in html

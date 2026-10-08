"""Fixed costs: an out item with no bucket is paid with a bucket-less expense
linked to the item (spec §3.4.2, §6.2.4), and old code paths cope with it."""

from decimal import Decimal

import pytest

from app.models import BillOccurrence, OccurrenceStatus, Transaction, TransactionType
from app.schemas import TransactionUpdate
from app.services.bills import (
    FIXED_COST_NEEDS_ITEM_MSG,
    EntryStateError,
    complete_entry,
    undo_occurrence,
)
from tests.test_api import api  # noqa: F401  (fixture)


def _fixed(db, hh, make_bill, **kw):
    bill, occ = make_bill(hh.household_id, None, amount=38.90, auto_pay=False, name="Cosmote", **kw)
    txn = complete_entry(db, occ, user_id=hh.user_id)
    db.commit()
    return bill, occ, txn


def test_pay_without_bucket_creates_a_fixed_cost(db, make_household, make_bill):
    hh = make_household()
    bill, occ, txn = _fixed(db, hh, make_bill)
    assert txn.type == TransactionType.expense and txn.bucket_id is None
    assert txn.recurring_bill_id == bill.id and txn.amount == Decimal("38.90")
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).transaction_id == txn.id


def test_pay_with_a_bucket_links_the_item_too(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    txn = complete_entry(db, occ, user_id=hh.user_id)
    assert txn.bucket_id == hh.bucket_id and txn.recurring_bill_id == bill.id


def test_complete_entry_needs_an_expected_entry_and_an_amount(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, None, amount=None, auto_pay=False)
    with pytest.raises(ValueError):
        complete_entry(db, occ, user_id=hh.user_id)
    complete_entry(db, occ, user_id=hh.user_id, amount=Decimal("61.20"))
    assert occ.amount == Decimal("61.20")  # stored for the estimate
    with pytest.raises(EntryStateError):
        complete_entry(db, occ, user_id=hh.user_id, amount=1)


def test_the_old_pay_route_still_only_claims_bucketless_bills(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, None, amount=20, auto_pay=False)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid
    assert db.query(Transaction).count() == 0


def test_undo_keeping_a_fixed_cost_is_refused(db, make_household, make_bill):
    hh = make_household()
    _, occ, _ = _fixed(db, hh, make_bill)
    with pytest.raises(EntryStateError):
        undo_occurrence(db, occ)


def test_old_pages_render_a_fixed_cost(client, db, authed, make_bill):
    _, _, txn = _fixed(db, authed, make_bill)
    for url in ("/dashboard", "/transactions/search", f"/transactions/{txn.id}/edit", "/insights"):
        assert client.get(url).status_code == 200, url


def test_update_schema_leaves_the_bucket_check_to_the_service():
    assert TransactionUpdate(amount="5").bucket_id is None


def test_old_edit_form_keeps_a_fixed_cost_bucketless(client, db, authed, make_bill):
    _, _, txn = _fixed(db, authed, make_bill)
    r = client.post(
        f"/transactions/{txn.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": txn.transaction_date.isoformat(),
            "amount": "40",
            "type": "expense",
        },
    )
    assert r.status_code == 302
    db.expire_all()
    edited = db.get(Transaction, txn.id)
    assert edited.bucket_id is None and edited.amount == Decimal("40")


def test_duplicating_a_fixed_cost_keeps_the_link(client, db, authed, make_bill):
    bill, _, txn = _fixed(db, authed, make_bill)
    r = client.post(f"/transactions/{txn.id}/duplicate", headers=authed.headers)
    assert r.status_code == 302
    copy = db.query(Transaction).filter(Transaction.id != txn.id).one()
    assert copy.bucket_id is None and copy.recurring_bill_id == bill.id


def test_an_item_with_a_deleted_fixed_cost_cannot_be_deleted(client, db, authed, make_bill):
    bill, occ, _ = _fixed(db, authed, make_bill)
    undo_occurrence(db, occ, delete_transaction=True)
    r = client.post(f"/bills/{bill.id}/delete", headers=authed.headers)
    assert r.status_code == 409
    db.expire_all()
    assert db.query(Transaction).count() == 1


def test_api_delete_of_an_item_with_a_fixed_cost_is_refused(client, db, authed, make_bill):
    bill, _, _ = _fixed(db, authed, make_bill)
    r = client.delete(f"/api/v1/bills/{bill.id}", headers=authed.headers)
    assert r.status_code == 409
    db.expire_all()
    assert db.query(Transaction).count() == 1


def test_old_delete_of_an_item_with_a_live_fixed_cost_is_refused(client, db, authed, make_bill):
    bill, _, txn = _fixed(db, authed, make_bill)
    r = client.post(f"/bills/{bill.id}/delete", headers=authed.headers)
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Transaction, txn.id).recurring_bill_id == bill.id


def test_undo_fixed_cost_keeping_expense_is_refused_with_message(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _fixed(db, hh, make_bill)
    with pytest.raises(EntryStateError) as exc:
        undo_occurrence(db, occ)
    assert str(exc.value) == FIXED_COST_NEEDS_ITEM_MSG
    assert occ.status == OccurrenceStatus.paid and txn.recurring_bill_id is not None


def test_undo_fixed_cost_deleting_expense_is_allowed(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _fixed(db, hh, make_bill)
    undo_occurrence(db, occ, delete_transaction=True)
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid
    assert db.get(Transaction, txn.id).deleted_at is not None


def test_pay_links_the_item_and_undo_keeping_the_expense_unlinks(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    txn = complete_entry(db, occ, user_id=hh.user_id)
    db.commit()
    assert txn.recurring_bill_id == bill.id
    undo_occurrence(db, occ)
    db.commit()
    db.expire_all()
    assert db.get(Transaction, txn.id).recurring_bill_id is None
    assert db.get(Transaction, txn.id).deleted_at is None


def test_a_bill_payment_with_a_bucket_cannot_lose_it(client, db, api, make_bill):  # noqa: F811
    from app.schemas import BUCKET_REQUIRED

    headers, hh = api
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    txn = complete_entry(db, occ, user_id=hh.user_id)
    db.commit()
    r = client.put(
        f"/api/v1/transactions/{txn.id}", headers=headers, json={"bucket_id": None, "amount": "10"}
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == BUCKET_REQUIRED
    db.expire_all()
    assert db.get(Transaction, txn.id).bucket_id == hh.bucket_id

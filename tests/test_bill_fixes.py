"""Final-review bill fixes: B2 (deleting a bill keeps paid history) and B5 (no payer-less bill expenses)."""
from decimal import Decimal

from app.clock import utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, RecurringBill
from tests.test_api import api  # noqa: F401  (fixture)

# ---------------------------------------------------------------------------
# B2: a bill with payment history cannot be hard-deleted
# ---------------------------------------------------------------------------


def _paid_bill(db, hh, make_bill):
    from app.bills_service import settle_occurrence
    bill, occ = make_bill(hh.household_id, None, auto_pay=False)
    settle_occurrence(db, occ, amount=Decimal("45"), paid_by=hh.user_id, paid_on=utcnow_naive())
    db.commit()
    return bill, occ


def test_html_delete_refuses_bill_with_paid_history(client, db, authed, make_bill):
    bill, occ = _paid_bill(db, authed, make_bill)
    r = client.post(f"/bills/{bill.id}/delete", headers=authed.headers, follow_redirects=False)
    assert r.status_code == 409
    assert "deactivate" in r.text.lower()
    db.expire_all()
    assert db.get(RecurringBill, bill.id) is not None
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid


def test_html_delete_refuses_bill_with_skipped_amount(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, auto_pay=False)
    occ.status = OccurrenceStatus.skipped
    occ.amount = Decimal("12")
    db.commit()
    r = client.post(f"/bills/{bill.id}/delete", headers=authed.headers, follow_redirects=False)
    assert r.status_code == 409
    db.expire_all()
    assert db.get(RecurringBill, bill.id) is not None


def test_html_delete_allows_bill_without_history(client, db, authed, make_bill):
    bill, _ = make_bill(authed.household_id, authed.bucket_id, auto_pay=False)
    bill_id = bill.id
    r = client.post(f"/bills/{bill_id}/delete", headers=authed.headers, follow_redirects=False)
    assert r.status_code == 302
    db.expire_all()
    assert db.query(RecurringBill).filter_by(id=bill_id).first() is None


def test_api_delete_refuses_bill_with_paid_history(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, occ = _paid_bill(db, hh, make_bill)
    r = client.delete(f"/api/v1/bills/{bill.id}", headers=headers)
    assert r.status_code == 409
    assert "deactivate" in r.json()["detail"].lower()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id) is not None


def test_api_delete_allows_bill_without_history(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, None, auto_pay=False)
    bill_id = bill.id
    r = client.delete(f"/api/v1/bills/{bill_id}", headers=headers)
    assert r.status_code == 204
    db.expire_all()
    assert db.query(RecurringBill).filter_by(id=bill_id).first() is None

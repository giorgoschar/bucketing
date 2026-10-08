"""The old app and shared queries see only active out items (spec §3.4.1,
§3.4.5, §6.2): paused and income items are hidden, new rules are read-only,
auto-pay never backfills."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import (
    BillOccurrence,
    Notification,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
)
from app.services import (
    get_bills_due_month_total,
    get_insights_bills_due,
    get_overdue_bills,
    get_upcoming_bills,
)
from tests.test_api import api  # noqa: F401  (fixture)


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _three(db, make_bill, hh, due):
    """An active bill, a paused bill and an income item, all due on ``due``."""
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False, due=due)
    paused, _ = make_bill(
        hh.household_id, hh.bucket_id, amount=20, auto_pay=False, due=due, name="Paused"
    )
    paused.is_active = False
    salary, _ = make_bill(
        hh.household_id, None, amount=1500, auto_pay=False, due=due, name="Salary X"
    )
    salary.direction = "in"
    db.commit()
    return bill, paused, salary


def test_bill_queries_skip_paused_and_income_items(db, make_household, make_bill):
    hh = make_household()
    today = local_today()
    bill, _, _ = _three(db, make_bill, hh, today + timedelta(days=2))
    assert [o.bill_id for o in get_upcoming_bills(db, hh.household_id)] == [bill.id]
    due = today + timedelta(days=2)
    assert get_bills_due_month_total(db, hh.household_id, due.year, due.month) == Decimal("10.00")
    assert get_insights_bills_due(db, hh.household_id, due, due) == Decimal("10.00")


def test_overdue_skips_paused_and_income_items(db, make_household, make_bill):
    hh = make_household()
    bill, _, _ = _three(db, make_bill, hh, local_today() - timedelta(days=5))
    assert [o.bill_id for o in get_overdue_bills(db, hh.household_id)] == [bill.id]


def test_bills_page_lists_out_items_only(client, db, authed, make_bill):
    _three(db, make_bill, authed, local_today() + timedelta(days=2))
    page = client.get("/bills").text
    assert "Internet" in page and "Paused" in page
    assert "Salary X" not in page


def test_old_routes_404_on_income_items(client, db, authed, make_bill):
    _, _, salary = _three(db, make_bill, authed, local_today())
    occ = db.query(BillOccurrence).filter_by(bill_id=salary.id).one()
    h = authed.headers
    assert client.post(f"/bills/{salary.id}/occurrences/{occ.id}/pay", headers=h).status_code == 404
    assert (
        client.post(f"/bills/{salary.id}/occurrences/{occ.id}/skip", headers=h).status_code == 404
    )
    r = client.post(
        f"/bills/{salary.id}/occurrences/{occ.id}/set-amount", data={"amount": "5"}, headers=h
    )
    assert r.status_code == 404
    assert client.get(f"/bills/{salary.id}/edit").status_code == 404
    assert client.post(f"/bills/{salary.id}/toggle", headers=h).status_code == 404
    assert client.post(f"/bills/{salary.id}/delete", headers=h).status_code == 404
    assert client.get(f"/bills/{salary.id}/history").status_code == 404
    assert db.query(Transaction).count() == 0


def test_old_api_hides_income_items(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    _, _, salary = _three(db, make_bill, hh, local_today())
    occ = db.query(BillOccurrence).filter_by(bill_id=salary.id).one()
    names = [b["name"] for b in client.get("/api/v1/bills", headers=headers).json()["items"]]
    assert "Salary X" not in names
    assert client.get(f"/api/v1/bills/{salary.id}", headers=headers).status_code == 404
    r = client.post(f"/api/v1/bills/occurrences/{occ.id}/pay", headers=headers, json={})
    assert r.status_code == 404
    assert db.query(Transaction).count() == 0


def test_new_rule_items_are_read_only_in_the_old_app(client, db, authed, make_bill):
    bill, _ = make_bill(authed.household_id, authed.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind, bill.rule_day = "monthly_day", 26
    db.commit()
    assert "Edit in the new app" in client.get("/bills").text
    assert client.get(f"/bills/{bill.id}/edit").status_code == 409
    r = client.post(
        f"/bills/{bill.id}/edit",
        headers=authed.headers,
        data={"name": "X", "start_date": "2026-01-01", "interval_months": "1"},
    )
    assert r.status_code == 409
    db.expire_all()
    assert bill.name == "Internet"


def test_new_rule_items_are_read_only_in_the_old_api(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind = "last_business_day"
    db.commit()
    r = client.put(
        f"/api/v1/bills/{bill.id}",
        headers=headers,
        json={"name": "X", "start_date": "2026-01-01", "bucket_id": hh.bucket_id},
    )
    assert r.status_code == 409


def test_auto_pay_window_is_three_days(db, make_household, make_bill, run_job):
    hh = make_household()
    today = local_today()
    _, edge = make_bill(hh.household_id, hh.bucket_id, amount=5, due=today - timedelta(days=3))
    _, old = make_bill(
        hh.household_id, hh.bucket_id, amount=7, due=today - timedelta(days=4), name="Old"
    )
    run_job()
    db.expire_all()
    assert db.get(BillOccurrence, edge.id).status == OccurrenceStatus.paid
    assert db.get(BillOccurrence, old.id).status == OccurrenceStatus.unpaid
    assert db.query(Transaction).count() == 1


def test_income_items_get_no_bill_reminders(db, make_household, make_bill, run_job):
    hh = make_household()
    salary, _ = make_bill(
        hh.household_id,
        None,
        amount=1500,
        auto_pay=False,
        due=local_today() + timedelta(days=3),
        name="Salary X",
    )
    salary.direction = "in"
    db.commit()
    run_job()
    assert db.query(Notification).count() == 0


# ---------------------------------------------------------------------------
# Controller Ruling 9: pause and delete are edits too, so a new-rule item is
# read-only for them in the old app as well (spec §6.2.2).
# ---------------------------------------------------------------------------


def test_new_rule_items_cannot_be_toggled_or_deleted_in_the_old_app(client, db, authed, make_bill):
    bill, _ = make_bill(authed.household_id, authed.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind = "last_business_day"
    db.commit()
    h = authed.headers
    assert client.post(f"/bills/{bill.id}/toggle", headers=h).status_code == 409
    assert client.post(f"/bills/{bill.id}/delete", headers=h).status_code == 409
    db.expire_all()
    assert db.get(RecurringBill, bill.id).is_active is True


def test_new_rule_items_cannot_be_deleted_in_the_old_api(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind = "nth_weekday"
    db.commit()
    assert client.delete(f"/api/v1/bills/{bill.id}", headers=headers).status_code == 409
    db.expire_all()
    assert db.get(RecurringBill, bill.id) is not None


def test_new_rule_entries_can_still_be_paid_in_the_old_app(client, db, authed, make_bill):
    """Read-only means the schedule; paying an out entry stays allowed."""
    bill, occ = make_bill(authed.household_id, authed.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind = "monthly_day"
    db.commit()
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid


# ---------------------------------------------------------------------------
# A linked expense (even a deleted one) blocks deleting its item: the FK's
# ON DELETE SET NULL would leave a bucket-less Fixed-cost expense that breaks
# ck_transactions_bucket_unless_income.
# ---------------------------------------------------------------------------


def _linked_deleted_expense(db, hh, bill):
    txn = Transaction(
        household_id=hh.household_id,
        bucket_id=None,
        amount=Decimal("10"),
        recurring_bill_id=bill.id,
        transaction_date=local_today(),
        deleted_at=utcnow_naive(),
    )
    db.add(txn)
    db.commit()
    return txn


def test_old_app_delete_refuses_an_item_with_a_linked_expense(client, db, authed, make_bill):
    bill, _ = make_bill(authed.household_id, authed.bucket_id, amount=10, auto_pay=False)
    txn = _linked_deleted_expense(db, authed, bill)
    r = client.post(f"/bills/{bill.id}/delete", headers=authed.headers)
    assert r.status_code == 409
    db.expire_all()
    assert db.get(RecurringBill, bill.id) is not None
    assert db.get(Transaction, txn.id).recurring_bill_id == bill.id


def test_old_api_delete_refuses_an_item_with_a_linked_expense(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    _linked_deleted_expense(db, hh, bill)
    assert client.delete(f"/api/v1/bills/{bill.id}", headers=headers).status_code == 409
    db.expire_all()
    assert db.get(RecurringBill, bill.id) is not None

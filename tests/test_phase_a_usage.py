"""Phase A S1 (spec §3.1-3.3): usage on items and entries."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import BillOccurrence, OccurrenceStatus, RecurringBill
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring"


def _item(**over):
    body = {
        "name": "Electricity",
        "direction": "out",
        "rule_kind": "monthly_day",
        "rule_day": 14,
        "start_date": (local_today() - timedelta(days=60)).isoformat(),
        "usage_unit": "kWh",
    }
    body.update(over)
    return body


def _make(client, headers, **over):
    r = client.post(URL, headers=headers, json=_item(**over))
    assert r.status_code == 201, r.text
    return r.json()


def _entry_id(item):
    return item["next_entry"]["id"]


# ---------------------------------------------------------------- the item


def test_item_round_trips_usage_unit(client, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    assert item["usage_unit"] == "kWh"
    assert client.get(f"{URL}/{item['id']}", headers=headers).json()["usage_unit"] == "kWh"
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_item(usage_unit="m³"))
    assert r.json()["usage_unit"] == "m³"
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_item(usage_unit=None))
    assert r.json()["usage_unit"] is None


def test_usage_unit_is_trimmed_and_empty_becomes_null(client, api):  # noqa: F811
    headers, _ = api
    assert _make(client, headers, usage_unit="  kWh  ")["usage_unit"] == "kWh"
    assert _make(client, headers, usage_unit="   ")["usage_unit"] is None
    assert _make(client, headers, usage_unit="")["usage_unit"] is None
    omitted = _item()
    del omitted["usage_unit"]
    r = client.post(URL, headers=headers, json=omitted)
    assert r.status_code == 201 and r.json()["usage_unit"] is None


def test_usage_unit_length_and_control_characters(client, api):  # noqa: F811
    headers, _ = api
    assert _make(client, headers, usage_unit="x" * 12)["usage_unit"] == "x" * 12
    too_long = client.post(URL, headers=headers, json=_item(usage_unit="x" * 13))
    assert too_long.status_code == 422
    for bad in ("kW\x00h", "kW\nh", "k\th", "kWh\x7f"):
        r = client.post(URL, headers=headers, json=_item(usage_unit=bad))
        assert r.status_code == 422, bad


def test_existing_item_shape_only_gains_keys(client, api):  # noqa: F811
    """Existing JSON keys stay; the item gains usage_unit, the entry usage and usage_unit."""
    headers, _ = api
    item = _make(client, headers)
    assert {
        "id", "name", "direction", "amount", "currency", "category_id", "bucket_id",
        "rule_kind", "interval_months", "rule_day", "rule_month", "rule_adjust", "rule_days",
        "rule_weekday", "rule_interval_weeks", "start_date", "end_date", "total_occurrences",
        "contract_end_date", "paid_by_default", "payer_mode", "payment_method", "is_auto_pay",
        "is_active", "notes", "splits", "next_entry", "has_history",
    } <= set(item)  # fmt: skip
    assert {
        "id", "item_id", "name", "direction", "due_date", "status", "amount", "estimated",
        "currency", "bucket_id", "category_id", "transaction_id", "overdue", "infrequent",
        "payment_method",
    } <= set(item["next_entry"])  # fmt: skip
    assert item["next_entry"]["usage"] is None
    assert item["next_entry"]["usage_unit"] == "kWh"


# ------------------------------------------------------- Pay and Set amount


def test_pay_with_usage_stores_it(client, db, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    r = client.post(
        f"{URL}/entries/{_entry_id(item)}/done",
        headers=headers,
        json={"amount": "84.00", "usage": "412.5"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done" and body["usage"] == 412.5 and body["usage_unit"] == "kWh"
    occ = db.get(BillOccurrence, body["id"])
    assert occ.usage == Decimal("412.500")


def test_set_amount_with_usage_stores_it(client, db, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    r = client.post(
        f"{URL}/entries/{_entry_id(item)}/amount",
        headers=headers,
        json={"amount": "70", "usage": 300},
    )
    assert r.status_code == 200, r.text
    assert r.json()["usage"] == 300.0 and r.json()["amount"] == 70.0


def test_omitting_usage_leaves_the_stored_value(client, db, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    eid = _entry_id(item)
    client.post(f"{URL}/entries/{eid}/amount", headers=headers, json={"amount": "70", "usage": 300})
    r = client.post(f"{URL}/entries/{eid}/amount", headers=headers, json={"amount": "71"})
    assert r.json()["usage"] == 300.0 and r.json()["amount"] == 71.0
    r = client.post(f"{URL}/entries/{eid}/done", headers=headers, json={})
    assert r.status_code == 200 and r.json()["usage"] == 300.0


def test_usage_for_an_item_without_a_unit_is_422(client, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers, usage_unit=None)
    eid = _entry_id(item)
    for path, body in (
        ("done", {"amount": "10", "usage": 5}),
        ("amount", {"amount": "10", "usage": 5}),
    ):
        r = client.post(f"{URL}/entries/{eid}/{path}", headers=headers, json=body)
        assert r.status_code == 422, (path, r.text)
    # Nothing was paid by the refused request.
    assert client.get(f"{URL}/{item['id']}", headers=headers).json()["next_entry"]["status"] == (
        "expected"
    )


@pytest.mark.parametrize("bad", [-1, "-0.5", "1000000000", "abc"])
def test_usage_range_is_validated(client, api, bad):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    r = client.post(
        f"{URL}/entries/{_entry_id(item)}/amount",
        headers=headers,
        json={"amount": "10", "usage": bad},
    )
    assert r.status_code == 422


def test_usage_zero_and_nine_digits_are_accepted(client, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    eid = _entry_id(item)
    r = client.post(
        f"{URL}/entries/{eid}/amount", headers=headers, json={"amount": "1", "usage": 0}
    )
    assert r.status_code == 200 and r.json()["usage"] == 0.0
    r = client.post(
        f"{URL}/entries/{eid}/amount",
        headers=headers,
        json={"amount": "1", "usage": "999999999.999"},
    )
    assert r.status_code == 200 and r.json()["usage"] == 999999999.999


def test_undo_and_skip_keep_usage(client, db, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    eid = _entry_id(item)
    client.post(f"{URL}/entries/{eid}/done", headers=headers, json={"amount": "84", "usage": 410})
    r = client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={"delete_transaction": True})
    assert r.json()["status"] == "expected" and r.json()["usage"] == 410.0
    r = client.post(f"{URL}/entries/{eid}/skip", headers=headers)
    assert r.json()["status"] == "skipped" and r.json()["usage"] == 410.0
    r = client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={"delete_transaction": True})
    assert r.json()["status"] == "expected" and r.json()["usage"] == 410.0


# --------------------------------------------------------------- §3.3 PUT


def test_put_usage_on_expected_done_and_skipped(client, api):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    eid = _entry_id(item)
    put = lambda body: client.put(f"{URL}/entries/{eid}/usage", headers=headers, json=body)  # noqa: E731
    r = put({"usage": 12.5})
    assert r.status_code == 200 and r.json()["usage"] == 12.5 and r.json()["status"] == "expected"
    client.post(f"{URL}/entries/{eid}/done", headers=headers, json={"amount": "20"})
    r = put({"usage": 15})
    assert r.json()["usage"] == 15.0 and r.json()["status"] == "done"
    client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={"delete_transaction": True})
    client.post(f"{URL}/entries/{eid}/skip", headers=headers)
    r = put({"usage": 16})
    assert r.json()["usage"] == 16.0 and r.json()["status"] == "skipped"
    r = put({"usage": None})
    assert r.status_code == 200 and r.json()["usage"] is None


def test_put_usage_is_422_without_a_unit_or_with_a_bad_value(client, api):  # noqa: F811
    headers, _ = api
    plain = _make(client, headers, usage_unit=None)
    r = client.put(f"{URL}/entries/{_entry_id(plain)}/usage", headers=headers, json={"usage": 1})
    assert r.status_code == 422
    # null clears, but an item with no unit has nothing to clear: still 422.
    r = client.put(f"{URL}/entries/{_entry_id(plain)}/usage", headers=headers, json={"usage": None})
    assert r.status_code == 422
    item = _make(client, headers)
    for bad in (-1, "1000000000"):
        r = client.put(
            f"{URL}/entries/{_entry_id(item)}/usage", headers=headers, json={"usage": bad}
        )
        assert r.status_code == 422


def test_put_usage_other_household_is_404(client, db, api, make_household):  # noqa: F811
    headers, _ = api
    item = _make(client, headers)
    # A second household with its own entry.
    other = make_household(name="Other", username="other")
    bill = RecurringBill(
        household_id=other.household_id,
        name="Water",
        amount=None,
        currency="EUR",
        start_date=local_today(),
        usage_unit="m³",
        is_active=True,
    )
    db.add(bill)
    db.flush()
    occ = BillOccurrence(bill_id=bill.id, due_date=local_today(), status=OccurrenceStatus.unpaid)
    db.add(occ)
    db.commit()
    r = client.put(f"{URL}/entries/{occ.id}/usage", headers=headers, json={"usage": 3})
    assert r.status_code == 404
    for path in ("done", "amount"):
        r = client.post(
            f"{URL}/entries/{occ.id}/{path}", headers=headers, json={"amount": "1", "usage": 3}
        )
        assert r.status_code == 404
    db.refresh(occ)
    assert occ.usage is None
    assert item  # the caller's own item is untouched


# ----------------------------------------------------------- the old app


def test_old_app_pages_still_save_an_item_and_keep_usage_unit(client, db, authed):
    """The Jinja bill forms never send usage_unit; saving through them must not clear it."""
    bill = RecurringBill(
        household_id=authed.household_id,
        name="Internet",
        amount=Decimal("30"),
        currency="EUR",
        start_date=local_today(),
        interval_months=1,
        usage_unit="GB",
        is_active=True,
    )
    db.add(bill)
    db.commit()
    assert client.get("/bills").status_code == 200
    r = client.post(
        f"/bills/{bill.id}/edit",
        headers=authed.headers,
        data={
            "name": "Internet 2",
            "amount": "31",
            "start_date": local_today().isoformat(),
            "interval_months": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text[:300]
    db.expire_all()
    db.refresh(bill)
    assert bill.name == "Internet 2" and bill.usage_unit == "GB"

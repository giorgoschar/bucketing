"""2d §7.0 over the wire: /recurring and /bills take, keep and return an item's
payment method; Pay and Done without one use it; the old pay form too."""

from datetime import timedelta

from app.core.clock import local_today
from app.models import BillOccurrence, RecurringBill, Transaction
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring"


def _out_item(**over):
    body = {
        "name": "Rent",
        "direction": "out",
        "amount": "800",
        "rule_kind": "monthly_interval",
        "interval_months": 1,
        "start_date": local_today().isoformat(),
    }
    body.update(over)
    return body


def _in_item(**over):
    return _out_item(name="Salary", direction="in", amount="1500", **over)


def _today_entry(client, headers, item_id):
    r = client.get(
        f"{URL}/entries",
        headers=headers,
        params={
            "from": local_today().isoformat(),
            "to": (local_today() + timedelta(40)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text
    return next(e for e in r.json() if e["item_id"] == item_id)


def test_create_defaults_by_direction(client, api):  # noqa: F811
    headers, _ = api
    out = client.post(URL, headers=headers, json=_out_item()).json()
    inc = client.post(URL, headers=headers, json=_in_item()).json()
    assert (out["payment_method"], inc["payment_method"]) == ("card", "transfer")


def test_create_with_a_method_and_entries_carry_it(client, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_out_item(payment_method="transfer")).json()
    assert item["payment_method"] == "transfer"
    assert item["next_entry"]["payment_method"] == "transfer"
    assert _today_entry(client, headers, item["id"])["payment_method"] == "transfer"
    listed = {i["id"]: i for i in client.get(URL, headers=headers).json()}
    assert listed[item["id"]]["payment_method"] == "transfer"


def test_put_without_payment_method_keeps_it(client, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_out_item(payment_method="transfer")).json()
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_out_item(name="Rent flat"))
    assert r.status_code == 200, r.text
    assert r.json()["payment_method"] == "transfer"
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_out_item(payment_method="cash"))
    assert r.json()["payment_method"] == "cash"


def test_invalid_method_is_400_everywhere(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post(URL, headers=headers, json=_out_item(payment_method="bitcoin"))
    assert r.status_code == 400 and "Unknown payment method" in r.json()["detail"]
    item = client.post(URL, headers=headers, json=_out_item()).json()
    entry = _today_entry(client, headers, item["id"])
    r = client.post(
        f"{URL}/entries/{entry['id']}/done", headers=headers, json={"payment_method": "bitcoin"}
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/bills",
        headers=headers,
        json={
            "name": "X",
            "amount": "5",
            "start_date": local_today().isoformat(),
            "payment_method": "nope",
        },
    )
    assert r.status_code == 400


def test_done_without_method_uses_the_items(client, db, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_out_item(payment_method="transfer")).json()
    entry = _today_entry(client, headers, item["id"])
    r = client.post(f"{URL}/entries/{entry['id']}/done", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert db.get(Transaction, r.json()["transaction_id"]).payment_method == "transfer"


def test_done_explicit_method_wins(client, db, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_in_item()).json()
    entry = _today_entry(client, headers, item["id"])
    r = client.post(
        f"{URL}/entries/{entry['id']}/done", headers=headers, json={"payment_method": "cash"}
    )
    assert db.get(Transaction, r.json()["transaction_id"]).payment_method == "cash"


def test_bills_api_creates_updates_returns_and_pays_with_it(client, db, api):  # noqa: F811
    headers, hh = api
    body = {
        "name": "Cosmote",
        "amount": "38.90",
        "bucket_id": hh.bucket_id,
        "start_date": local_today().isoformat(),
        "payment_method": "transfer",
    }
    bill = client.post("/api/v1/bills", headers=headers, json=body).json()
    assert bill["payment_method"] == "transfer"
    body.pop("payment_method")
    r = client.put(f"/api/v1/bills/{bill['id']}", headers=headers, json=body)
    assert r.json()["payment_method"] == "transfer"  # absent: unchanged
    occ = db.query(BillOccurrence).filter_by(bill_id=bill["id"], due_date=local_today()).one()
    r = client.post(f"/api/v1/bills/occurrences/{occ.id}/pay", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert db.get(Transaction, r.json()["transaction_id"]).payment_method == "transfer"


def test_bills_api_create_without_method_is_card(client, api):  # noqa: F811
    headers, hh = api
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={"name": "Gym", "amount": "25", "start_date": local_today().isoformat()},
    ).json()
    assert bill["payment_method"] == "card"


def test_old_pay_form_blank_method_uses_the_bills(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, auto_pay=False)
    db.get(RecurringBill, bill.id).payment_method = "transfer"
    db.commit()
    r = client.post(
        f"/bills/{bill.id}/occurrences/{occ.id}/pay",
        headers=authed.headers,
        data={"amount": "", "paid_by": "", "payment_method": ""},
    )
    assert r.status_code == 302
    db.expire_all()
    txn_id = db.get(BillOccurrence, occ.id).transaction_id
    assert db.get(Transaction, txn_id).payment_method == "transfer"


def test_old_pay_form_offers_the_bills_default(client, authed, make_bill):
    make_bill(authed.household_id, authed.bucket_id, auto_pay=False)
    page = client.get("/bills").text
    assert '<option value="" selected>Bill\'s default</option>' in page

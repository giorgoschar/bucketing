"""/api/v1/recurring (spec §6.3): items in both directions on rules, their
entries and the entry actions; household isolation."""

from datetime import timedelta
from decimal import Decimal

from app.core.clock import local_today
from app.models import BillOccurrence, Bucket, BucketType, OccurrenceStatus, Transaction
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring"


def _salary(**over):
    body = {
        "name": "Salary",
        "direction": "in",
        "amount": "1500",
        "rule_kind": "monthly_day",
        "rule_day": 26,
        "rule_adjust": "previous_business_day",
        "start_date": (local_today() - timedelta(days=90)).isoformat(),
    }
    body.update(over)
    return body


def test_create_income_item_has_no_past_entries(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post(URL, headers=headers, json=_salary())
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["direction"] == "in" and item["next_entry"]["status"] == "expected"
    assert item["next_entry"]["amount"] == 1500.0
    dates = [d for (d,) in db.query(BillOccurrence.due_date).filter_by(bill_id=item["id"])]
    assert dates and min(dates) >= local_today() and len(dates) >= 12


def test_list_shows_paused_items_without_a_next_entry(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary(is_active=False)).json()
    [listed] = client.get(URL, headers=headers).json()
    assert listed["id"] == item["id"] and listed["is_active"] is False
    assert listed["next_entry"] is None


def test_resuming_fills_the_horizon_at_once(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary(is_active=False)).json()
    # A paused item may hold no entries (the nightly top-up skips it): strip
    # them so only the resume itself can fill the horizon.
    db.query(BillOccurrence).filter_by(bill_id=item["id"]).delete()
    db.commit()
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_salary(is_active=True))
    assert r.status_code == 200 and r.json()["next_entry"] is not None
    assert db.query(BillOccurrence).filter_by(bill_id=item["id"]).count() >= 12


def test_rule_and_reference_validation(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    bad_rule = client.post(URL, headers=headers, json=_salary(rule_day=None))
    assert bad_rule.status_code == 400
    in_bucket = client.post(URL, headers=headers, json=_salary(bucket_id=hh.bucket_id))
    assert in_bucket.status_code == 400
    trip = Bucket(household_id=hh.household_id, name="Trip", type=BucketType.trip)
    db.add(trip)
    db.commit()
    out_in_event = client.post(
        URL, headers=headers, json=_salary(direction="out", bucket_id=trip.id)
    )
    assert out_in_event.status_code == 400
    other = make_household(name="Other", username="other")
    foreign = client.post(
        URL, headers=headers, json=_salary(direction="out", bucket_id=other.bucket_id)
    )
    assert foreign.status_code in (400, 404)


def test_entries_range(client, db, api):  # noqa: F811
    headers, hh = api
    client.post(URL, headers=headers, json=_salary())
    today = local_today()
    r = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": today.isoformat(), "to": (today + timedelta(days=62)).isoformat()},
    )
    assert r.status_code == 200 and 2 <= len(r.json()) <= 3
    too_long = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": today.isoformat(), "to": (today + timedelta(days=500)).isoformat()},
    )
    assert too_long.status_code == 400


def _first_entry(client, headers):
    today = local_today()
    return client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": today.isoformat(), "to": (today + timedelta(days=60)).isoformat()},
    ).json()[0]


def test_done_undo_skip_amount_round_trip(client, db, api):  # noqa: F811
    headers, hh = api
    client.post(
        URL,
        headers=headers,
        json=_salary(direction="out", name="Cosmote", amount=None, rule_adjust="none"),
    )
    entry = _first_entry(client, headers)
    eid = entry["id"]
    assert client.post(f"{URL}/entries/{eid}/done", headers=headers, json={}).status_code == 400
    r = client.post(f"{URL}/entries/{eid}/amount", headers=headers, json={"amount": "38.90"})
    assert r.json()["amount"] == 38.9
    r = client.post(f"{URL}/entries/{eid}/done", headers=headers, json={})
    assert r.status_code == 200 and r.json()["status"] == "done"
    txn = db.query(Transaction).one()
    assert txn.bucket_id is None and txn.amount == Decimal("38.90")  # a Fixed cost
    again = client.post(f"{URL}/entries/{eid}/done", headers=headers, json={})
    assert again.status_code == 409
    keep = client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={})
    assert keep.status_code == 409  # a Fixed cost can't stay without its item
    r = client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={"delete_transaction": True})
    assert r.status_code == 200 and r.json()["status"] == "expected"
    assert client.post(f"{URL}/entries/{eid}/skip", headers=headers).json()["status"] == "skipped"
    assert client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={}).status_code == 200


def test_mark_received_creates_income(client, db, api):  # noqa: F811
    headers, hh = api
    client.post(URL, headers=headers, json=_salary())
    entry = _first_entry(client, headers)
    r = client.post(f"{URL}/entries/{entry['id']}/done", headers=headers, json={"amount": "1520"})
    assert r.status_code == 200
    txn = db.query(Transaction).one()
    assert txn.type.value == "income" and txn.amount == Decimal("1520.00")
    assert txn.paid_by == hh.user_id


def test_delete_item_without_history(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary()).json()
    assert client.delete(f"{URL}/{item['id']}", headers=headers).status_code == 204
    assert db.query(BillOccurrence).count() == 0


def test_another_household_gets_404_everywhere(client, db, api, make_household, make_bill):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    bill, occ = make_bill(other.household_id, other.bucket_id, auto_pay=False)
    assert client.get(f"{URL}/{bill.id}", headers=headers).status_code == 404
    assert client.put(f"{URL}/{bill.id}", headers=headers, json=_salary()).status_code == 404
    assert client.delete(f"{URL}/{bill.id}", headers=headers).status_code == 404
    for action, body in (("done", {}), ("undo", {}), ("amount", {"amount": "1"})):
        r = client.post(f"{URL}/entries/{occ.id}/{action}", headers=headers, json=body)
        assert r.status_code == 404, action
    assert client.post(f"{URL}/entries/{occ.id}/skip", headers=headers).status_code == 404
    assert client.get(URL, headers=headers).json() == []
    today = local_today()
    listed = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": (today - timedelta(days=5)).isoformat(), "to": today.isoformat()},
    ).json()
    assert listed == []
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_requires_auth(client):
    assert client.get(URL).status_code == 401


def test_failed_action_leaves_state_and_foreign_member_is_refused(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    client.post(URL, headers=headers, json=_salary())
    entry = _first_entry(client, headers)
    other = make_household(name="Other", username="other")
    r = client.post(
        f"{URL}/entries/{entry['id']}/done", headers=headers, json={"person": other.user_id}
    )
    assert r.status_code in (400, 404)
    db.expire_all()
    assert db.query(Transaction).count() == 0
    assert db.get(BillOccurrence, entry["id"]).status == OccurrenceStatus.unpaid


def _split_body(splits, **over):
    return _salary(
        direction="out", name="Rent", amount="100", rule_adjust="none", splits=splits, **over
    )


def test_split_validation(client, db, api):  # noqa: F811
    headers, hh = api
    me = hh.user_id
    for bad in (
        [{"user_id": me, "amount": "0"}],
        [{"user_id": me, "amount": "-100"}],
        [{"user_id": me, "amount": "NaN"}],
        [{"user_id": me, "amount": "50"}, {"user_id": me, "amount": "50"}],
        [{"user_id": me, "amount": "60"}],  # sum mismatch
    ):
        r = client.post(URL, headers=headers, json=_split_body(bad))
        assert r.status_code in (400, 422), (bad, r.text)
    ok = client.post(URL, headers=headers, json=_split_body([{"user_id": me, "amount": "100"}]))
    assert ok.status_code == 201, ok.text
    assert ok.json()["splits"] == [{"user_id": me, "amount": 100.0}]


def test_interval_ranges(client, db, api):  # noqa: F811
    headers, hh = api
    for over in ({"interval_months": 0}, {"interval_months": 500}):
        assert client.post(URL, headers=headers, json=_salary(**over)).status_code == 400
    weekly = _salary(rule_kind="weekly", rule_day=None, rule_weekday=1, rule_adjust="none")
    r = client.post(URL, headers=headers, json={**weekly, "rule_interval_weeks": 99})
    assert r.status_code == 400
    r = client.post(URL, headers=headers, json={**weekly, "rule_interval_weeks": 2})
    assert r.status_code == 201, r.text


def test_direction_and_currency_locked_by_history(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary()).json()
    entry = _first_entry(client, headers)
    done = client.post(f"{URL}/entries/{entry['id']}/done", headers=headers, json={})
    assert done.status_code == 200
    url = f"{URL}/{item['id']}"
    assert client.put(url, headers=headers, json=_salary(direction="out")).status_code == 409
    assert client.put(url, headers=headers, json=_salary(currency="USD")).status_code == 409
    assert client.put(url, headers=headers, json=_salary(name="Pay")).status_code == 200


def test_has_history_follows_bill_has_payment_history(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary()).json()
    assert item["has_history"] is False
    assert client.get(f"{URL}/{item['id']}", headers=headers).json()["has_history"] is False
    # A skipped occurrence with an amount recorded counts, though no transaction exists.
    occ = (
        db.query(BillOccurrence)
        .filter_by(bill_id=item["id"])
        .order_by(BillOccurrence.due_date)
        .first()
    )
    occ.status = OccurrenceStatus.skipped
    occ.amount = Decimal("1500.00")
    db.commit()
    assert db.query(Transaction).count() == 0
    [listed] = client.get(URL, headers=headers).json()
    assert listed["has_history"] is True
    assert client.get(f"{URL}/{item['id']}", headers=headers).json()["has_history"] is True

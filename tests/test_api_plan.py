"""/api/v1/matches, /plan/*, /insights/categories-vs-usual, /buckets kind and
the transaction drill-down filters (spec §6.3); household isolation."""

from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import MatchSuggestion, Transaction, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)


def _expense(client, headers, hh, amount="38.90"):
    r = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={"amount": amount, "bucket_id": hh.bucket_id, "merchant": "COSMOTE"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_match_list_link_and_refuse_a_stale_link(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=38.90,
        auto_pay=False,
        due=local_today(),
        name="Cosmote",
    )
    txn = _expense(client, headers, hh)
    [m] = client.get("/api/v1/matches", headers=headers).json()
    assert m["label"].startswith("Looks like Cosmote · ") and m["transaction_id"] == txn["id"]
    assert m["entry"]["status"] == "expected"

    assert client.post(f"/api/v1/matches/{m['id']}/link", headers={}).status_code == 401
    r = client.post(f"/api/v1/matches/{m['id']}/link", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.get("/api/v1/matches", headers=headers).json() == []
    again = client.post(f"/api/v1/matches/{m['id']}/link", headers=headers)
    assert again.status_code == 409
    assert db.get(Transaction, txn["id"]).recurring_bill_id == bill.id


def test_dismiss_and_foreign_suggestion(client, db, api, make_household, make_bill):  # noqa: F811
    headers, hh = api
    make_bill(hh.household_id, hh.bucket_id, amount=38.90, auto_pay=False, due=local_today())
    _expense(client, headers, hh)
    [m] = client.get("/api/v1/matches", headers=headers).json()
    assert client.post(f"/api/v1/matches/{m['id']}/dismiss", headers=headers).status_code == 204
    assert client.get("/api/v1/matches", headers=headers).json() == []
    assert db.query(MatchSuggestion).one().dismissed is True

    other = make_household(name="Other", username="other")
    s = db.query(MatchSuggestion).one()
    s.household_id = other.household_id
    db.commit()
    assert client.post(f"/api/v1/matches/{s.id}/link", headers=headers).status_code == 404
    assert client.post(f"/api/v1/matches/{s.id}/dismiss", headers=headers).status_code == 404


def test_plan_endpoints_shape_and_numbers_are_json_numbers(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    make_bill(hh.household_id, None, amount=30, auto_pay=False, due=local_today(), name="Net")
    month = client.get("/api/v1/plan/month", headers=headers)
    assert month.status_code == 200, month.text
    body = month.json()
    assert body["fixed"]["still_to_come"] == 30.0 and "net_projected" in body
    assert client.get("/api/v1/plan/month?month=2026-13", headers=headers).status_code == 400
    up = client.get("/api/v1/plan/upcoming", headers=headers).json()
    assert up[0]["entries"][0]["name"] == "Net"
    year = client.get("/api/v1/plan/year", headers=headers).json()
    assert len(year["months"]) == 12
    assert client.get("/api/v1/plan/pace", headers=headers).status_code == 200
    [budget] = client.get("/api/v1/plan/budgets", headers=headers).json()
    assert budget["bucket_id"] == hh.bucket_id and budget["kind"] == "monthly"
    usual = client.get("/api/v1/insights/categories-vs-usual", headers=headers)
    assert usual.status_code == 200


def test_plan_figures_ignore_other_households(client, db, api, make_household, make_bill):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    make_bill(other.household_id, None, amount=999, auto_pay=False, due=local_today())
    body = client.get("/api/v1/plan/month", headers=headers).json()
    assert body["fixed"]["still_to_come"] == 0.0
    assert client.get("/api/v1/plan/upcoming", headers=headers).json() == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/matches",
        "/api/v1/plan/month",
        "/api/v1/plan/upcoming",
        "/api/v1/plan/year",
        "/api/v1/plan/pace",
        "/api/v1/plan/budgets",
        "/api/v1/insights/categories-vs-usual",
    ],
)
def test_planning_endpoints_require_auth(client, path):
    assert client.get(path).status_code == 401


def test_transaction_drill_down_filters(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, occ = make_bill(hh.household_id, None, amount=20, auto_pay=False)
    r = client.post(f"/api/v1/recurring/entries/{occ.id}/done", headers=headers, json={})
    assert r.status_code == 200, r.text
    _expense(client, headers, hh, amount="5")
    fixed = client.get("/api/v1/transactions", headers=headers, params={"fixed": "true"}).json()
    assert [t["amount"] for t in fixed["items"]] == [20.0]
    assert fixed["items"][0]["recurring_bill_id"] == bill.id
    by_item = client.get(
        "/api/v1/transactions", headers=headers, params={"recurring_bill_id": bill.id}
    ).json()
    assert by_item["total"] == 1
    assert Decimal(str(fixed["items"][0]["amount"])) == Decimal("20")


def test_cross_household_link_and_dismiss_change_nothing(
    client,
    db,
    api,
    make_household,
    make_bill,  # noqa: F811
):
    headers, hh = api
    make_bill(hh.household_id, hh.bucket_id, amount=38.90, auto_pay=False, due=local_today())
    txn = _expense(client, headers, hh)
    s = db.query(MatchSuggestion).one()
    other = make_household(name="Other", username="other")
    s.household_id = other.household_id
    db.commit()
    assert client.post(f"/api/v1/matches/{s.id}/link", headers=headers).status_code == 404
    assert client.post(f"/api/v1/matches/{s.id}/dismiss", headers=headers).status_code == 404
    db.expire_all()
    assert db.get(MatchSuggestion, s.id).dismissed is False
    assert db.get(Transaction, txn["id"]).recurring_bill_id is None


def test_a_stale_open_suggestion_does_not_block_a_new_one(db, api, make_bill):  # noqa: F811
    from datetime import timedelta

    from app.services.matching import suggest_for_transaction

    _, hh = api
    due = local_today()

    def txn(when):
        t = Transaction(
            household_id=hh.household_id,
            bucket_id=hh.bucket_id,
            amount=Decimal("38.90"),
            currency="EUR",
            type=TransactionType.expense,
            paid_by=hh.user_id,
            transaction_date=when,
        )
        db.add(t)
        db.commit()
        return t

    _, e1 = make_bill(hh.household_id, hh.bucket_id, amount=38.90, auto_pay=False, due=due)
    a, b = txn(due), txn(due + timedelta(days=1))
    sa, sb = suggest_for_transaction(db, a), suggest_for_transaction(db, b)
    db.commit()
    assert sa and sb  # both suggested to E

    from app.services.matching import link_suggestion

    link_suggestion(db, sa)
    db.commit()  # E is done: B's suggestion is stale

    _, e2 = make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=38.90,
        auto_pay=False,
        due=due + timedelta(days=3),
        name="Other bill",
    )
    again = suggest_for_transaction(db, b)
    assert again is not None and again.occurrence_id == e2.id

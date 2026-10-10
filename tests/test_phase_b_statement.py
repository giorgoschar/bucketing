"""Phase B S2 (spec §3.2, §6 "Statement"): GET /insights/statements/{month}."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models import (
    BillOccurrence,
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionType,
)
from app.services import InsightFilters, build_insights
from app.services.cash import STASH_IN, TAKE, add_movement
from app.services.statement import build_statement, review_state
from tests.test_api import api  # noqa: F401  (fixture)

D = Decimal
NOW = date(2026, 10, 3)  # in the review window of September 2026
URL = "/api/v1/insights/statements"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    import app.api.insights as api_insights

    monkeypatch.setattr(api_insights, "local_today", lambda: NOW)


def _txn(db, hh, amount, day, *, type=TransactionType.expense, bucket="default", **kw):
    bucket_id = hh.bucket_id if bucket == "default" else bucket
    if type == TransactionType.income and bucket == "default":
        bucket_id = None
    fields = dict(
        household_id=hh.household_id,
        bucket_id=bucket_id,
        amount=D(str(amount)),
        type=type,
        paid_by=hh.user_id,
        transaction_date=day,
    )
    fields.update(kw)
    t = Transaction(**fields)
    db.add(t)
    db.flush()
    return t


def _item(db, hh, name, *, direction="out", amount=None, **kw):
    fields = dict(
        household_id=hh.household_id,
        name=name,
        amount=amount,
        currency="EUR",
        start_date=date(2025, 1, 1),
        interval_months=1,
        is_active=True,
        direction=direction,
    )
    fields.update(kw)
    item = RecurringBill(**fields)
    db.add(item)
    db.flush()
    return item


def _entry(db, item, due, status=OccurrenceStatus.unpaid, amount=None, **kw):
    occ = BillOccurrence(bill_id=item.id, due_date=due, status=status, amount=amount, **kw)
    db.add(occ)
    db.flush()
    return occ


def _get(client, headers, month):
    return client.get(f"{URL}/{month}", headers=headers)


# ------------------------------------------------------------- the sections


def _seed_september(db, hh):
    """Jun-Aug give every category a steady usual; September then has one
    category above it, one budget over, one bill changed, 45 of cash unlogged."""
    eating = Category(household_id=hh.household_id, name="Eating out", icon="🍽")
    home = Category(household_id=hh.household_id, name="Home", icon="🏠")
    db.add_all([eating, home])
    db.flush()
    for m, dinner in ((6, 200), (7, 240), (8, 240)):
        _txn(db, hh, dinner, date(2026, m, 10), category_id=eating.id)
        _txn(db, hh, 400, date(2026, m, 11), category_id=home.id)
        _txn(db, hh, 2300, date(2026, m, 12))
    _txn(db, hh, 3000, date(2026, 8, 1), type=TransactionType.income)
    _txn(db, hh, 3000, date(2026, 9, 1), type=TransactionType.income)
    _txn(db, hh, 370, date(2026, 9, 20), category_id=eating.id, merchant="Dinner place")
    _txn(db, hh, 420 - 400 + 400, date(2026, 9, 3), category_id=home.id, merchant="IKEA")
    _txn(db, hh, 25, date(2026, 9, 4), notes="bread")
    daily = Bucket(household_id=hh.household_id, name="Daily", budget=D("1200"))
    fine = Bucket(household_id=hh.household_id, name="Fine", budget=D("500"))
    trip = Bucket(household_id=hh.household_id, name="Trip", type=BucketType.trip, budget=D("10"))
    old = Bucket(
        household_id=hh.household_id, name="Old", budget=D("50"), status=BucketStatus.archived
    )
    db.add_all([daily, fine, trip, old])
    db.flush()
    _txn(db, hh, 1310, date(2026, 9, 7), bucket=daily.id)
    _txn(db, hh, 100, date(2026, 9, 7), bucket=fine.id)
    _txn(db, hh, 99, date(2026, 9, 8), bucket=trip.id)
    _txn(db, hh, 80, date(2026, 9, 9), bucket=old.id)
    rent = _item(db, hh, "Rent", amount=D("800"))
    gym = _item(db, hh, "Gym", amount=D("35"))
    nope = _item(db, hh, "Nope", amount=D("999"))
    power = _item(db, hh, "Power")
    pay = _item(db, hh, "Salary", direction="in", amount=D("3000"))
    rent_txn = _txn(db, hh, 800, date(2026, 9, 1), recurring_bill_id=rent.id)
    _entry(db, rent, date(2026, 9, 1), OccurrenceStatus.paid, transaction_id=rent_txn.id)
    _entry(db, gym, date(2026, 9, 28))
    _entry(db, nope, date(2026, 9, 12), OccurrenceStatus.skipped)
    _entry(db, power, date(2026, 8, 14), OccurrenceStatus.paid, amount=D("60"))
    _entry(db, power, date(2026, 9, 29))
    _entry(db, pay, date(2026, 9, 1), OccurrenceStatus.paid, amount=D("3000"))
    elec = _item(db, hh, "Electricity")
    for d, a in ((date(2026, 6, 14), 60), (date(2026, 7, 14), 61), (date(2026, 8, 14), 62)):
        _entry(db, elec, d, OccurrenceStatus.paid, amount=D(a))
    _entry(db, elec, date(2026, 9, 14), OccurrenceStatus.paid, amount=D(84))
    add_movement(db, hh.household_id, hh.user_id, TAKE, D("45"), "EUR", date(2026, 9, 2))
    db.commit()
    return dict(daily=daily, old=old, eating=eating)


def test_every_section_against_a_seeded_month(client, db, api):  # noqa: F811
    headers, hh = api
    ids = _seed_september(db, hh)
    r = _get(client, headers, "2026-09")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["month"] == "2026-09" and body["label"] == "September 2026"
    assert body["reviewed_at"] is None and body["reviewed_by"] is None
    assert body["closed"] is False and body["days_left"] == 3

    out = 370 + 420 + 25 + 1310 + 100 + 99 + 80 + 800 + 45
    assert body["totals"]["in"] == 3000.0
    assert body["totals"]["out"] == float(out)
    assert body["totals"]["net"] == float(3000 - out)
    assert body["totals"]["previous"] == {
        "month": "2026-08",
        "in": 3000.0,
        "out": 2940.0,
        "net": 60.0,
    }

    planned = body["planned"]
    # nope is skipped; power's open entry counts its estimate (the 60 of August).
    assert planned["out"] == {"planned": 800.0 + 35 + 60 + 84, "actual": 800.0 + 84}
    assert planned["in"] == {"planned": 3000.0, "actual": 3000.0}
    assert [(e["name"], e["amount"], e["estimated"], e["status"]) for e in planned["open"]] == [
        ("Gym", 35.0, False, "expected"),
        ("Power", 60.0, True, "expected"),
    ]
    assert planned["open"][0]["due_date"] == "2026-09-28"
    assert planned["open"][0]["direction"] == "out"

    # The event budget (trip) is left out; the archived bucket is still listed.
    assert body["budgets_over"] == [
        {
            "bucket_id": ids["daily"].id,
            "name": "Daily",
            "budget": 1200.0,
            "spent": 1310.0,
            "over": 110.0,
        },
        {"bucket_id": ids["old"].id, "name": "Old", "budget": 50.0, "spent": 80.0, "over": 30.0},
    ]
    [bill] = body["bills_changed"]
    assert (bill["name"], bill["amount"], bill["usual"], bill["basis"]) == (
        "Electricity",
        84.0,
        61.0,
        "recent",
    )
    assert bill["direction"] == "up" and bill["pct"] == 38 and bill["due_date"] == "2026-09-14"
    assert bill["reason"] is None and bill["reason_pct"] is None
    assert body["cash"] == [
        {"member_id": hh.user_id, "name": hh.username.title(), "not_yet_logged": 45.0}
    ]
    assert [(c["name"], c["icon"], c["amount"], c["usual"]) for c in body["categories_over"]] == [
        ("Eating out", "🍽", 370.0, 240.0)
    ]
    assert [(b["label"], b["category"], b["amount"]) for b in body["biggest"]] == [
        ("Transaction", None, 1310.0),
        ("Transaction", None, 800.0),
        ("IKEA", "Home", 420.0),
        ("Dinner place", "Eating out", 370.0),
        ("Transaction", None, 100.0),
    ]
    assert body["biggest"][2]["date"] == "2026-09-03"


def test_a_month_with_no_data_is_zeros_and_empty_lists(client, db, api):  # noqa: F811
    """Review Focus 1: a gap between two months with data."""
    headers, hh = api
    _txn(db, hh, 50, date(2026, 7, 5))
    _txn(db, hh, 60, date(2026, 9, 5))
    db.commit()
    r = _get(client, headers, "2026-08")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["totals"] == {
        "in": 0.0,
        "out": 0.0,
        "net": 0.0,
        "previous": {"month": "2026-07", "in": 0.0, "out": 50.0, "net": -50.0},
    }
    assert body["planned"] == {
        "in": {"planned": 0.0, "actual": 0.0},
        "out": {"planned": 0.0, "actual": 0.0},
        "open": [],
    }
    for key in ("budgets_over", "bills_changed", "cash", "categories_over", "biggest"):
        assert body[key] == []
    # A month before the household had anything is also not an error.
    assert _get(client, headers, "2020-01").status_code == 200


def test_previous_is_null_without_data_in_the_month_before(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 60, date(2026, 9, 5))
    db.commit()
    assert _get(client, headers, "2026-09").json()["totals"]["previous"] is None


def test_two_changed_entries_of_one_item_in_one_month(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh, "Water", rule_kind="weekly")
    for d, a in ((date(2026, 8, 3), 20), (date(2026, 8, 10), 20), (date(2026, 8, 17), 20)):
        _entry(db, item, d, OccurrenceStatus.paid, amount=D(a))
    _entry(db, item, date(2026, 9, 7), OccurrenceStatus.paid, amount=D(40))
    _entry(db, item, date(2026, 9, 14), OccurrenceStatus.paid, amount=D(80))
    _entry(db, item, date(2026, 9, 21), OccurrenceStatus.paid, amount=D(45))
    db.commit()
    rows = _get(client, headers, "2026-09").json()["bills_changed"]
    # 40 against 20, 80 against the median of (20, 20, 40), 45 is close to its usual 40.
    assert [(r["due_date"], r["amount"], r["usual"]) for r in rows] == [
        ("2026-09-14", 80.0, 20.0),
        ("2026-09-07", 40.0, 20.0),
    ]


def test_a_member_with_nothing_unlogged_is_left_out(client, db, api):  # noqa: F811
    from tests.test_isolation import _add_member_user

    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    add_movement(db, hh.household_id, flat.id, TAKE, D("30"), "EUR", date(2026, 9, 2))
    _txn(db, hh, 30, date(2026, 9, 3), payment_method="cash", paid_by=flat.id)
    db.commit()
    assert _get(client, headers, "2026-09").json()["cash"] == []


def test_soft_deleted_expense_is_not_in_biggest(client, db, api):  # noqa: F811
    from app.core.clock import utcnow_naive

    headers, hh = api
    _txn(db, hh, 900, date(2026, 9, 3), merchant="Gone", deleted_at=utcnow_naive())
    _txn(db, hh, 10, date(2026, 9, 4), merchant="Kept")
    _txn(db, hh, 5000, date(2026, 9, 5), type=TransactionType.income)
    db.commit()
    body = _get(client, headers, "2026-09").json()
    assert [b["label"] for b in body["biggest"]] == ["Kept"]
    assert body["totals"]["out"] == 10.0


def test_a_reviewed_month_says_who_and_when(client, db, api):  # noqa: F811
    from app.models import MonthReview

    headers, hh = api
    db.add(
        MonthReview(
            household_id=hh.household_id,
            month="2026-09",
            reviewed_at=datetime(2026, 10, 2, 8, 0, tzinfo=UTC).replace(tzinfo=None),
            reviewed_by=hh.user_id,
        )
    )
    db.commit()
    body = _get(client, headers, "2026-09").json()
    assert body["reviewed_at"].startswith("2026-10-02T08:00")
    assert body["reviewed_by"] == hh.user_id
    assert body["closed"] is True and body["days_left"] is None


# ------------------------------------------------------- agreement and rules


def test_totals_equal_insights_in_out_for_the_same_month(client, db, api):  # noqa: F811
    headers, hh = api
    _seed_september(db, hh)
    # A foreign-currency expense and a labelled cash out, which Insights counts too.
    _txn(db, hh, 10, date(2026, 9, 6), currency="USD", exchange_rate=D("0.9"))
    db.commit()
    statement = _get(client, headers, "2026-09").json()
    data = build_insights(
        db,
        hh.household_id,
        InsightFilters(preset="custom", start_date="2026-09-01", end_date="2026-09-30"),
    )
    assert statement["totals"]["in"] == float(data["in_out"]["in"])
    assert statement["totals"]["out"] == float(data["in_out"]["out"])
    assert statement["totals"]["net"] == float(data["in_out"]["net"])
    # And the same previous month as the Insights series.
    series = {(r["year"], r["month"]): r for r in data["monthly_in_out"]}
    aug = build_insights(
        db,
        hh.household_id,
        InsightFilters(preset="custom", start_date="2026-08-01", end_date="2026-08-31"),
    )["in_out"]
    assert statement["totals"]["previous"]["out"] == float(aug["out"])
    assert series is not None


def test_bad_month_is_400_and_current_or_future_is_404(client, db, api):  # noqa: F811
    headers, hh = api
    for bad in ("2026-9", "2026-13", "2026-00", "september", "26-09", "1900-01"):
        assert _get(client, headers, bad).status_code == 400, bad
    assert _get(client, headers, "2026-10").status_code == 404  # the current month
    assert _get(client, headers, "2026-11").status_code == 404
    assert _get(client, headers, "2030-01").status_code == 404
    assert _get(client, headers, "2026-09").status_code == 200
    assert client.get(f"{URL}/2026-09").status_code == 401


def test_closed_and_days_left_with_a_fixed_clock():
    rows = [
        # (month, today, reviewed, closed, days_left)
        ((2026, 9), date(2026, 10, 1), False, False, 5),
        ((2026, 9), date(2026, 10, 3), False, False, 3),
        ((2026, 9), date(2026, 10, 5), False, False, 1),
        ((2026, 9), date(2026, 10, 6), False, True, None),
        ((2026, 9), date(2026, 11, 2), False, True, None),
        ((2026, 9), date(2026, 10, 2), True, True, None),
        ((2025, 12), date(2026, 1, 3), False, False, 3),  # the turn of the year
        ((2025, 12), date(2026, 1, 5), False, False, 1),
        ((2025, 12), date(2026, 1, 6), False, True, None),
        ((2025, 11), date(2026, 1, 3), False, True, None),
    ]
    for (y, m), today, reviewed, closed, left in rows:
        assert review_state(y, m, reviewed, today) == (closed, left), (y, m, today)


def test_on_the_third_of_january_the_review_is_december(db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 70, date(2025, 12, 20))
    _txn(db, hh, 30, date(2025, 11, 20))
    db.commit()
    s = build_statement(db, hh.household_id, 2025, 12, today=date(2026, 1, 3), viewer_id=hh.user_id)
    assert s["month"] == "2025-12" and s["label"] == "December 2025"
    assert (s["closed"], s["days_left"]) == (False, 3)
    assert s["totals"]["out"] == 70.0
    assert s["totals"]["previous"] == {"month": "2025-11", "in": 0.0, "out": 30.0, "net": -30.0}


def test_statement_over_http_follows_the_clock(client, db, api, monkeypatch):  # noqa: F811
    import app.api.insights as api_insights

    headers, hh = api
    for today, closed, left in (
        (date(2026, 10, 1), False, 5),
        (date(2026, 10, 5), False, 1),
        (date(2026, 10, 6), True, None),
        (date(2026, 11, 3), True, None),
    ):
        monkeypatch.setattr(api_insights, "local_today", lambda t=today: t)
        body = _get(client, headers, "2026-09").json()
        assert (body["closed"], body["days_left"]) == (closed, left), today


def test_household_isolation_on_the_statement_route(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other")
    _txn(db, hh, 123, date(2026, 9, 5), merchant="Mine")
    _txn(db, SimpleHH(other), 999, date(2026, 9, 5), merchant="Theirs")
    db.commit()
    body = _get(client, headers, "2026-09").json()
    assert body["totals"]["out"] == 123.0
    assert [b["label"] for b in body["biggest"]] == ["Mine"]
    assert "Theirs" not in json.dumps(body)


class SimpleHH:
    """Adapts a make_household namespace to _txn."""

    def __init__(self, ns):
        self.household_id, self.bucket_id, self.user_id = ns.household_id, ns.bucket_id, ns.user_id


def test_no_stash_amount_in_the_statement(client, db, api):  # noqa: F811
    headers, hh = api
    from app.services.cash import FROM_STASH

    add_movement(db, hh.household_id, hh.user_id, STASH_IN, D("777.77"), "EUR", date(2026, 9, 1))
    add_movement(
        db,
        hh.household_id,
        hh.user_id,
        TAKE,
        D("20"),
        "EUR",
        date(2026, 9, 2),
        stash_owner_id=hh.user_id,
    )
    db.commit()
    assert FROM_STASH
    text = _get(client, headers, "2026-09").text
    assert "777" not in text
    assert json.loads(text)["cash"][0]["not_yet_logged"] == 20.0


def test_every_response_carries_only_the_documented_keys(client, db, api):  # noqa: F811
    headers, hh = api
    _seed_september(db, hh)
    body = _get(client, headers, "2026-09").json()
    assert set(body) == {
        "month", "label", "reviewed_at", "reviewed_by", "closed", "days_left", "totals",
        "planned", "budgets_over", "bills_changed", "cash", "categories_over", "biggest",
    }  # fmt: skip
    assert set(body["totals"]) == {"in", "out", "net", "previous"}
    assert set(body["planned"]) == {"in", "out", "open"}


# ------------------------------------------------------------- query count


def _count(db, fn):
    statements = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        fn()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    return len(statements)


def test_query_count_does_not_grow_with_items_or_transactions(client, db, api):  # noqa: F811
    headers, hh = api
    cats = [Category(household_id=hh.household_id, name=f"C{n}") for n in range(6)]
    db.add_all(cats)
    db.flush()

    def grow(first, last, txns):
        for n in range(first, last):
            item = _item(db, hh, f"Bill {n}", direction="out" if n % 3 else "in")
            for k, a in enumerate((50, 50, 50, 90 + n)):
                _entry(db, item, date(2026, 6 + k, 14), OccurrenceStatus.paid, amount=D(a))
            _entry(db, item, date(2026, 9, 25 + n % 3))
            variable = _item(db, hh, f"Var {n}")
            _entry(db, variable, date(2026, 8, 3), OccurrenceStatus.paid, amount=D(30))
            _entry(db, variable, date(2026, 9, 3))
        for n in range(txns):
            _txn(db, hh, 5 + n, date(2026, 9, 1 + n % 28), category_id=cats[n % 6].id)
        db.commit()

    grow(0, 5, 40)
    small = _count(db, lambda: _get(client, headers, "2026-09"))
    grow(5, 15, 160)
    large = _count(db, lambda: _get(client, headers, "2026-09"))
    assert small == large, (small, large)
    assert small < 60

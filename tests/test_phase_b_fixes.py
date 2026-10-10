"""Phase B stream S, fix round 1 (review findings 1-4, 6-8 and the wire)."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    Bucket,
    Category,
    MonthReview,
    Notification,
    NotificationType,
    RecurringBill,
    Transaction,
    TransactionType,
)
from app.services import InsightFilters, build_insights
from app.services.cash import OUT, PUT_BACK, STASH_COUNT, STASH_IN, STILL_HAVE, TAKE, add_movement
from app.services.insights import monthly_in_out
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

D = Decimal
NOW = date(2026, 10, 3)
URL = "/api/v1/insights/statements"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    import app.api.insights as api_insights

    monkeypatch.setattr(api_insights, "local_today", lambda: NOW)


def _txn(db, hh, amount, day, *, type=TransactionType.expense, bucket="default", **kw):
    bucket_id = hh.bucket_id if bucket == "default" else bucket
    if type == TransactionType.income and bucket == "default":
        bucket_id = None
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=bucket_id,
        amount=D(str(amount)),
        type=type,
        paid_by=hh.user_id,
        transaction_date=day,
        **kw,
    )
    db.add(t)
    db.flush()
    return t


def _item(db, hh, name, **kw):
    fields = dict(
        household_id=hh.household_id,
        name=name,
        currency="EUR",
        start_date=date(2025, 1, 1),
        interval_months=1,
        is_active=True,
        direction="out",
    )
    fields.update(kw)
    item = RecurringBill(**fields)
    db.add(item)
    db.flush()
    return item


def _entry(db, item, due, status, amount=None):
    from app.models import OccurrenceStatus

    occ = BillOccurrence(
        bill_id=item.id, due_date=due, status=OccurrenceStatus[status], amount=amount
    )
    db.add(occ)
    db.flush()
    return occ


def _stage(db, today):
    from app.scheduler import _notify_month_review

    _notify_month_review(db, today)
    db.expire_all()


# ---------------------------------------------------------- 1. stash is not data


@pytest.mark.parametrize("kind", [STASH_IN, STASH_COUNT])
def test_another_members_stash_only_month_is_not_data(client, db, api, kind):  # noqa: F811
    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    add_movement(db, hh.household_id, flat.id, kind, D("777.77"), "EUR", date(2026, 9, 1))
    assert client.get(URL, headers=headers).json() == {"review": None, "months": []}
    _stage(db, date(2026, 10, 1))
    assert db.query(Notification).filter_by(type=NotificationType.month_review).count() == 0


def test_a_stash_move_does_not_start_the_list_or_make_a_previous(client, db, api):  # noqa: F811
    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    add_movement(db, hh.household_id, flat.id, STASH_IN, D("50"), "EUR", date(2026, 7, 1))
    _txn(db, hh, 20, date(2026, 8, 5))
    db.commit()
    months = client.get(URL, headers=headers).json()["months"]
    assert months[-1]["month"] == "2026-08"  # not July, where only a stash move happened
    assert client.get(f"{URL}/2026-08", headers=headers).json()["totals"]["previous"] is None


# ------------------------------------------------------- 2. paused items


def test_done_entries_of_a_paused_item_stay_in_planned_but_its_open_ones_go(client, db, api):  # noqa: F811
    headers, hh = api
    power = _item(db, hh, "Power")
    gym = _item(db, hh, "Gym", amount=D("35"))
    _entry(db, power, date(2026, 9, 14), "paid", D("84"))
    _entry(db, gym, date(2026, 9, 28), "unpaid")
    db.commit()
    before = client.get(f"{URL}/2026-09", headers=headers).json()["planned"]
    assert before["out"] == {"planned": 119.0, "actual": 84.0}
    power.is_active = False
    gym.is_active = False
    db.commit()
    after = client.get(f"{URL}/2026-09", headers=headers).json()["planned"]
    assert after["out"] == {"planned": 84.0, "actual": 84.0}
    assert after["open"] == []


def test_list_entries_default_still_hides_paused_items(db, api):  # noqa: F811
    from app.services.planning import list_entries

    headers, hh = api
    item = _item(db, hh, "Old", amount=D("5"), is_active=False)
    _entry(db, item, date(2026, 9, 2), "paid", D("5"))
    db.commit()
    args = (db, hh.household_id, date(2026, 9, 1), date(2026, 9, 30))
    assert list_entries(*args) == []
    assert [e.name for e in list_entries(*args, include_paused=True)] == ["Old"]


# ------------------------------------------- 3. mutants and the agreement test


def test_budget_spending_is_only_the_months(client, db, api):  # noqa: F811
    headers, hh = api
    b = Bucket(household_id=hh.household_id, name="Fine", budget=D("500"))
    db.add(b)
    db.flush()
    _txn(db, hh, 100, date(2026, 9, 7), bucket=b.id)
    _txn(db, hh, 450, date(2026, 8, 31), bucket=b.id)
    _txn(db, hh, 450, date(2026, 10, 1), bucket=b.id)
    db.commit()
    assert client.get(f"{URL}/2026-09", headers=headers).json()["budgets_over"] == []


def test_another_households_review_does_not_review_mine(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other")
    db.add(
        MonthReview(
            household_id=other.household_id,
            month="2026-09",
            reviewed_at=utcnow_naive(),
            reviewed_by=other.user_id,
        )
    )
    _txn(db, hh, 10, date(2026, 9, 5))
    db.commit()
    body = client.get(f"{URL}/2026-09", headers=headers).json()
    assert body["reviewed_at"] is None and body["closed"] is False
    listing = client.get(URL, headers=headers).json()
    assert listing["review"] is not None and listing["months"][0]["reviewed_at"] is None
    assert client.post(f"{URL}/2026-09/review", headers=headers).status_code == 200
    db.expire_all()
    assert db.query(MonthReview).filter_by(month="2026-09").count() == 2


def test_totals_agree_with_insights_including_cash_outs_and_hidden_income(client, db, api):  # noqa: F811
    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    cat = Category(household_id=hh.household_id, name="Misc")
    hidden = Bucket(household_id=hh.household_id, name="Hidden", show_income=False)
    db.add_all([cat, hidden])
    db.flush()
    _txn(db, hh, 3000, date(2026, 9, 1), type=TransactionType.income)
    _txn(db, hh, 700, date(2026, 9, 2), type=TransactionType.income, bucket=hidden.id)
    _txn(db, hh, 10, date(2026, 9, 6), currency="USD", exchange_rate=D("0.9"))
    add_movement(db, hh.household_id, hh.user_id, TAKE, D("100"), "EUR", date(2026, 9, 3))
    add_movement(db, hh.household_id, hh.user_id, OUT, D("33"), "EUR", date(2026, 9, 4), cat.id)
    add_movement(db, hh.household_id, hh.user_id, PUT_BACK, D("5"), "EUR", date(2026, 9, 5))
    add_movement(db, hh.household_id, flat.id, TAKE, D("60"), "EUR", date(2026, 9, 3))
    add_movement(db, hh.household_id, flat.id, STILL_HAVE, D("20"), "EUR", date(2026, 9, 28))
    _txn(db, hh, 25, date(2026, 10, 2), payment_method="cash")  # uses up September's cash
    db.commit()
    s = client.get(f"{URL}/2026-09", headers=headers).json()["totals"]
    flt = InsightFilters(preset="custom", start_date="2026-09-01", end_date="2026-09-30")
    data = build_insights(db, hh.household_id, flt)
    assert s["in"] == 3000.0  # the hidden-bucket income is not income
    assert s["out"] == float(data["in_out"]["out"]) > 33.0 + 10 * 0.9
    assert (s["in"], s["net"]) == (float(data["in_out"]["in"]), float(data["in_out"]["net"]))
    row = next(
        r
        for r in monthly_in_out(db, hh.household_id, 3, today=date(2026, 9, 30))
        if (r["year"], r["month"]) == (2026, 9)
    )
    assert (s["in"], s["out"], s["net"]) == (float(row["in"]), float(row["out"]), float(row["net"]))
    listed = client.get(URL, headers=headers).json()["months"][0]
    assert (listed["in"], listed["out"], listed["net"]) == (s["in"], s["out"], s["net"])


# ------------------------------------------------ reviewed_on / reviewed_by_name


def _review_row(db, hh, when, by="me"):
    db.add(
        MonthReview(
            household_id=hh.household_id,
            month="2026-09",
            reviewed_at=when,
            reviewed_by=hh.user_id if by == "me" else by,
        )
    )
    db.commit()


def test_reviewed_on_is_the_household_local_date(client, db, api, monkeypatch):  # noqa: F811
    from app.core import config

    monkeypatch.setattr(config.settings, "app_timezone", "Europe/Athens")
    headers, hh = api
    _txn(db, hh, 10, date(2026, 9, 5))
    _review_row(db, hh, datetime(2026, 9, 30, 22, 30, tzinfo=UTC).replace(tzinfo=None))
    body = client.get(f"{URL}/2026-09", headers=headers).json()
    assert body["reviewed_on"] == "2026-10-01"
    assert body["reviewed_by"] == hh.user_id
    assert body["reviewed_by_name"] == hh.username.title()
    row = client.get(URL, headers=headers).json()["months"][0]
    assert row["reviewed_on"] == "2026-10-01"
    assert row["reviewed_by"] == hh.user_id and row["reviewed_by_name"] == hh.username.title()


def test_reviewed_fields_are_null_when_not_reviewed_or_the_user_is_gone(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 9, 5))
    db.commit()
    body = client.get(f"{URL}/2026-09", headers=headers).json()
    assert (body["reviewed_on"], body["reviewed_by_name"]) == (None, None)
    row = client.get(URL, headers=headers).json()["months"][0]
    assert (row["reviewed_on"], row["reviewed_by"], row["reviewed_by_name"]) == (None,) * 3
    _review_row(db, hh, utcnow_naive(), by=None)
    body = client.get(f"{URL}/2026-09", headers=headers).json()
    assert body["reviewed_on"] is not None
    assert (body["reviewed_by"], body["reviewed_by_name"]) == (None, None)


def test_reviewed_by_name_falls_back_to_the_username(client, db, api):  # noqa: F811
    from app.models import User

    headers, hh = api
    db.get(User, hh.user_id).display_name = ""
    _review_row(db, hh, utcnow_naive())
    body = client.get(f"{URL}/2026-09", headers=headers).json()
    assert body["reviewed_by_name"] == hh.username


# ------------------------------------------------------------------ the wire


def test_money_is_json_numbers_and_categories_over_carry_amount(client, db, api):  # noqa: F811
    headers, hh = api
    eating = Category(household_id=hh.household_id, name="Eating")
    db.add(eating)
    db.flush()
    for m, a in ((6, 100), (7, 100), (8, 100)):
        _txn(db, hh, a, date(2026, m, 10), category_id=eating.id)
    _txn(db, hh, 300, date(2026, 9, 10), category_id=eating.id, merchant="X")
    _txn(db, hh, 1000, date(2026, 9, 1), type=TransactionType.income)
    add_movement(db, hh.household_id, hh.user_id, TAKE, D("45"), "EUR", date(2026, 9, 2))
    bucket = Bucket(household_id=hh.household_id, name="B", budget=D("10"))
    db.add(bucket)
    db.flush()
    _txn(db, hh, 50, date(2026, 9, 9), bucket=bucket.id)
    item = _item(db, hh, "Power")
    for d, a in ((6, 60), (7, 61), (8, 62)):
        _entry(db, item, date(2026, d, 14), "paid", D(a))
    _entry(db, item, date(2026, 9, 14), "paid", D(84))
    _entry(db, item, date(2026, 9, 29), "unpaid")
    db.commit()

    raw = client.get(f"{URL}/2026-09", headers=headers).text
    stmt = json.loads(raw)
    assert set(stmt["categories_over"][0]) == {"category_id", "name", "icon", "amount", "usual"}

    def number(v):
        return isinstance(v, int | float) and not isinstance(v, bool)

    for k in ("in", "out", "net"):
        assert number(stmt["totals"][k])
    assert number(stmt["totals"]["previous"]["net"]) if stmt["totals"]["previous"] else True
    for side in ("in", "out"):
        assert number(stmt["planned"][side]["planned"]) and number(stmt["planned"][side]["actual"])
    assert all(number(e["amount"]) for e in stmt["planned"]["open"])
    for row in stmt["budgets_over"]:
        assert all(number(row[k]) for k in ("budget", "spent", "over"))
    for row in stmt["bills_changed"]:
        assert all(number(row[k]) for k in ("amount", "usual", "pct"))
    assert all(number(r["not_yet_logged"]) for r in stmt["cash"])
    assert all(number(r["amount"]) and number(r["usual"]) for r in stmt["categories_over"])
    assert all(number(r["amount"]) for r in stmt["biggest"])
    assert stmt["budgets_over"] and stmt["bills_changed"] and stmt["cash"] and stmt["biggest"]
    assert stmt["categories_over"] and stmt["planned"]["open"]
    listing = client.get(URL, headers=headers).json()
    assert all(number(m[k]) for m in listing["months"] for k in ("in", "out", "net"))


# ------------------------------------------------------------------ minors


def test_month_parsing_is_strict(client, db, api):  # noqa: F811
    headers, hh = api
    for bad in ("%202026-09", "2026-09%0A", "٢٠٢٦-٠٩"):
        assert client.get(f"{URL}/{bad}", headers=headers).status_code == 400, bad
    assert client.get(f"{URL}/2026-09", headers=headers).status_code == 200


def test_no_review_for_a_month_before_the_first_data_month(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 8, 5))
    db.commit()
    assert client.post(f"{URL}/2026-06/review", headers=headers).status_code == 404
    db.expire_all()
    assert db.query(MonthReview).count() == 0
    assert client.post(f"{URL}/2026-08/review", headers=headers).status_code == 200


def test_days_two_to_five_do_not_recompute_for_a_notified_household(db, api, monkeypatch):  # noqa: F811
    import app.services.insights as insights

    headers, hh = api
    _txn(db, hh, 10, date(2026, 9, 5))
    db.commit()
    _stage(db, date(2026, 10, 1))
    calls = []
    real = insights.in_out_by_month
    monkeypatch.setattr(
        insights, "in_out_by_month", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    _stage(db, date(2026, 10, 2))
    assert calls == []
    assert db.query(Notification).filter_by(type=NotificationType.month_review).count() == 1


def test_a_done_entry_without_an_amount_does_not_count_an_estimate_as_actual(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh, "Var")
    _entry(db, item, date(2026, 8, 3), "paid", D("30"))
    _entry(db, item, date(2026, 9, 3), "paid", None)
    db.commit()
    out = client.get(f"{URL}/2026-09", headers=headers).json()["planned"]["out"]
    assert out["actual"] == 0.0

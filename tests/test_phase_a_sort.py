"""Phase A S4 (spec §3.8-3.9): Activity sorting and the longer month series."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import Transaction, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/transactions"


def _txn(db, hh, amount, when, *, currency="EUR", rate=None, kind=TransactionType.expense):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=None if kind == TransactionType.income else hh.bucket_id,
        amount=Decimal(str(amount)),
        currency=currency,
        exchange_rate=None if rate is None else Decimal(str(rate)),
        type=kind,
        paid_by=hh.user_id,
        transaction_date=when,
    )
    db.add(t)
    db.flush()
    return t


def _ids(client, headers, **params):
    r = client.get(URL, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]], r.json()


@pytest.fixture()
def rows(db, api):  # noqa: F811
    headers, hh = api
    base = date(2026, 3, 1)
    made = [
        _txn(db, hh, 30, base),
        _txn(db, hh, 10, base + timedelta(days=1)),
        _txn(db, hh, 50, base + timedelta(days=2)),
        _txn(db, hh, 20, base + timedelta(days=3)),
    ]
    db.commit()
    return headers, hh, made


def test_default_is_date_desc_and_unchanged(client, rows):
    headers, _, made = rows
    ids, body = _ids(client, headers)
    assert ids == [made[3].id, made[2].id, made[1].id, made[0].id]
    assert ids == _ids(client, headers, sort="date_desc")[0]
    assert set(body["day_totals"]) == {"2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"}
    assert body["day_totals"]["2026-03-03"] == -50.0


def test_date_asc(client, rows):
    headers, _, made = rows
    ids, body = _ids(client, headers, sort="date_asc")
    assert ids == [made[0].id, made[1].id, made[2].id, made[3].id]
    assert body["day_totals"]["2026-03-01"] == -30.0


def test_amount_desc_and_asc(client, rows):
    headers, _, made = rows
    desc, _ = _ids(client, headers, sort="amount_desc")
    assert desc == [made[2].id, made[0].id, made[3].id, made[1].id]
    asc, _ = _ids(client, headers, sort="amount_asc")
    assert asc == [made[1].id, made[3].id, made[0].id, made[2].id]


def test_amount_sorts_use_the_base_currency_amount(client, db, api):  # noqa: F811
    headers, hh = api
    today = local_today()
    small_but_strong = _txn(db, hh, 40, today, currency="USD", rate="2.5")  # 100 base
    plain = _txn(db, hh, 60, today)
    db.commit()
    assert _ids(client, headers, sort="amount_desc")[0] == [small_but_strong.id, plain.id]
    assert _ids(client, headers, sort="amount_asc")[0] == [plain.id, small_but_strong.id]


def test_bad_sort_is_400(client, rows):
    headers, _, _ = rows
    for bad in ("amount", "DATE_DESC", "", "date_desc;drop", "merchant_asc"):
        r = client.get(URL, headers=headers, params={"sort": bad})
        assert r.status_code == 400, bad


def test_day_totals_is_empty_under_an_amount_sort(client, rows):
    headers, _, _ = rows
    for s in ("amount_desc", "amount_asc"):
        _, body = _ids(client, headers, sort=s)
        assert body["day_totals"] == {}


def test_paging_an_amount_sort_with_equal_amounts_repeats_and_drops_nothing(
    client,
    db,
    api,  # noqa: F811
):
    """Review Focus 5: 7 rows of the same amount, 3 a page."""
    headers, hh = api
    same_day = date(2026, 4, 1)
    made = {_txn(db, hh, 12, same_day).id for _ in range(5)}
    made |= {_txn(db, hh, 12, same_day + timedelta(days=1)).id for _ in range(2)}
    db.commit()
    for sort in ("amount_desc", "amount_asc", "date_asc", "date_desc"):
        seen = []
        for page in (1, 2, 3, 4):
            ids, body = _ids(client, headers, sort=sort, page=page, page_size=3)
            assert body["total"] == 7
            seen += ids
        assert len(seen) == 7 and set(seen) == made, sort


def test_amount_ties_break_by_the_current_order(client, db, api):  # noqa: F811
    headers, hh = api
    old = _txn(db, hh, 5, date(2026, 1, 1))
    new = _txn(db, hh, 5, date(2026, 2, 1))
    db.commit()
    assert _ids(client, headers, sort="amount_desc")[0] == [new.id, old.id]
    assert _ids(client, headers, sort="amount_asc")[0] == [new.id, old.id]


def test_filters_work_with_every_sort(client, db, api):  # noqa: F811
    headers, hh = api
    a = _txn(db, hh, 70, date(2026, 5, 1))
    _txn(db, hh, 5, date(2026, 5, 2), kind=TransactionType.income)
    c = _txn(db, hh, 90, date(2026, 5, 3))
    db.commit()
    for sort, expected in (("amount_desc", [c.id, a.id]), ("amount_asc", [a.id, c.id])):
        ids, body = _ids(client, headers, sort=sort, type="expense")
        assert ids == expected and body["total"] == 2


def test_totals_ignores_sort(client, rows):
    headers, _, _ = rows
    plain = client.get(f"{URL}/totals", headers=headers).json()
    for s in ("amount_desc", "date_asc", "nonsense"):
        r = client.get(f"{URL}/totals", headers=headers, params={"sort": s})
        assert r.status_code == 200 and r.json() == plain


# ------------------------------------------------------------------ months


@pytest.mark.parametrize("months", [6, 12, 24])
def test_months_sets_the_series_length(client, api, months):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/insights", headers=headers, params={"months": months})
    assert r.status_code == 200, r.text
    series = r.json()["monthly_in_out"]
    assert len(series) == months
    today = local_today()
    assert (series[-1]["year"], series[-1]["month"]) == (today.year, today.month)


def test_months_default_is_six(client, api):  # noqa: F811
    headers, _ = api
    assert len(client.get("/api/v1/insights", headers=headers).json()["monthly_in_out"]) == 6


@pytest.mark.parametrize("bad", ["0", "5", "7", "13", "36", "-6", "abc", ""])
def test_bad_months_is_400(client, api, bad):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/insights", headers=headers, params={"months": bad})
    assert r.status_code == 400

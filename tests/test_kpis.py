"""
Insight KPIs.

Every figure must obey the same filters as the rest of the page — the previous
version mixed filtered and unfiltered numbers on one screen.
"""
from datetime import date, timedelta

import pytest

from app.models import Bucket, Category, Transaction, TransactionType
from app.services import get_insights_kpis


def _expense(db, ctx, amount, when, bucket_id=None, category_id=None, notes=None):
    db.add(Transaction(
        bucket_id=bucket_id or ctx.bucket_id, household_id=ctx.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=when,
        category_id=category_id, notes=notes, paid_by=ctx.user_id,
    ))
    db.commit()


@pytest.fixture()
def spread(db, authed):
    """300 across three consecutive months: 100 / 50 / 150."""
    _expense(db, authed, 100, date(2026, 1, 10), notes="January")
    _expense(db, authed, 50,  date(2026, 2, 10), notes="February")
    _expense(db, authed, 150, date(2026, 3, 10), notes="March big one")
    return authed


def _kpis(db, ctx, start=date(2026, 1, 1), end=date(2026, 3, 31), **kw):
    return get_insights_kpis(db, ctx.household_id, start, end, **kw)


def test_total_and_count(db, spread):
    k = _kpis(db, spread)
    assert k["total"] == 300.0
    assert k["count"] == 3


def test_average_per_month(db, spread):
    """The headline the board exists for."""
    k = _kpis(db, spread)
    assert k["months"] == 3
    assert k["avg_per_month"] == 100.0


def test_average_per_day(db, spread):
    k = _kpis(db, spread)
    assert k["days"] == 90          # 1 Jan to 31 Mar inclusive
    assert k["avg_per_day"] == round(300 / 90, 2)


def test_average_per_expense(db, spread):
    assert _kpis(db, spread)["avg_per_txn"] == 100.0


def test_busiest_and_quietest_month(db, spread):
    k = _kpis(db, spread)
    assert k["busiest_month"]["label"] == "Mar 2026"
    assert k["busiest_month"]["total"] == 150.0
    assert k["quietest_month"]["label"] == "Feb 2026"
    assert k["quietest_month"]["total"] == 50.0


def test_largest_single_expense(db, spread):
    k = _kpis(db, spread)
    assert k["largest"]["amount"] == 150.0
    assert k["largest"]["notes"] == "March big one"
    assert k["largest"]["date"] == date(2026, 3, 10)


def test_change_versus_the_preceding_window(db, spread):
    """Compared against a window of the same length immediately before."""
    _expense(db, spread, 200, date(2025, 12, 15))   # falls in Oct-Dec
    k = _kpis(db, spread)
    assert k["previous_total"] == 200.0
    assert k["change_pct"] == 50.0                   # 300 vs 200


def test_no_prior_data_gives_no_percentage(db, spread):
    k = _kpis(db, spread)
    assert k["previous_total"] == 0.0
    assert k["change_pct"] is None


def test_month_count_never_zero(db, authed):
    """A single-day range must not divide by zero."""
    _expense(db, authed, 20, date(2026, 5, 5))
    k = _kpis(db, authed, date(2026, 5, 5), date(2026, 5, 5))
    assert k["months"] == 1
    assert k["days"] == 1
    assert k["avg_per_month"] == 20.0


def test_open_ended_range_uses_the_data(db, spread):
    """All-time derives its bounds from the transactions themselves."""
    k = get_insights_kpis(db, spread.household_id, None, None)
    assert k["range_start"] == date(2026, 1, 10)
    assert k["range_end"] == date(2026, 3, 10)
    assert k["months"] == 3


def test_empty_range_does_not_crash(db, authed):
    k = _kpis(db, authed)
    assert k["total"] == 0.0
    assert k["count"] == 0
    assert k["avg_per_month"] == 0.0
    assert k["largest"] is None
    assert k["busiest_month"] is None


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def test_bucket_filter_applies(db, authed):
    other = Bucket(household_id=authed.household_id, name="Other")
    db.add(other)
    db.flush()
    _expense(db, authed, 100, date(2026, 1, 5))
    _expense(db, authed, 900, date(2026, 1, 6), bucket_id=other.id)
    db.commit()

    k = _kpis(db, authed, date(2026, 1, 1), date(2026, 1, 31),
              bucket_ids=[authed.bucket_id])
    assert k["total"] == 100.0
    assert k["count"] == 1


def test_category_filter_applies(db, authed):
    food = Category(household_id=authed.household_id, name="Food")
    db.add(food)
    db.flush()
    _expense(db, authed, 40, date(2026, 1, 5), category_id=food.id)
    _expense(db, authed, 60, date(2026, 1, 6))
    db.commit()

    k = _kpis(db, authed, date(2026, 1, 1), date(2026, 1, 31), category_ids=[food.id])
    assert k["total"] == 40.0


def test_currency_is_converted(db, authed):
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=200, currency="USD", exchange_rate=0.5,
        type=TransactionType.expense, transaction_date=date(2026, 1, 5),
    ))
    db.commit()
    assert _kpis(db, authed, date(2026, 1, 1), date(2026, 1, 31))["total"] == 100.0


def test_savings_rate_needs_income(db, spread):
    """Income is not tracked in this household, so the rate is withheld."""
    assert _kpis(db, spread)["savings_rate"] is None


def test_savings_rate_when_income_exists(db, authed):
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=1000, currency="EUR", exchange_rate=1,
        type=TransactionType.income, transaction_date=date(2026, 1, 5),
    ))
    db.commit()
    _expense(db, authed, 250, date(2026, 1, 6))

    k = _kpis(db, authed, date(2026, 1, 1), date(2026, 1, 31))
    assert k["income"] == 1000.0
    assert k["savings_rate"] == 75.0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_board_renders_on_the_page(client, db, spread):
    r = client.get("/insights?preset=all_time")
    assert r.status_code == 200
    for label in ("Avg / month", "Avg / day", "vs previous", "Busiest month",
                  "Largest single"):
        assert label in r.text, label


def test_charts_are_server_rendered_svg(client, db, spread):
    """No JS charting library: the markup must arrive complete."""
    r = client.get("/insights?preset=all_time")
    assert "<svg" in r.text
    assert "polyline" in r.text          # the trend line
    assert "<title>" in r.text           # native hover tooltips


def test_api_exposes_kpis(client, db, spread, make_household):
    import pyotp
    from tests.conftest import PASSWORD

    r = client.post("/api/v1/auth/login",
                    json={"username": spread.username, "password": PASSWORD})
    pending = r.json()["pending_token"]
    tok = client.post("/api/v1/auth/totp/verify",
                      json={"pending_token": pending,
                            "code": pyotp.TOTP(spread.secret).now()}).json()["access_token"]

    body = client.get("/api/v1/insights?preset=all_time",
                      headers={"Authorization": f"Bearer {tok}"}).json()
    assert "kpis" in body
    assert body["kpis"]["avg_per_month"] == 100.0

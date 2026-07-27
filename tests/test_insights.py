"""Insights: date presets, filter consistency and chart scaling."""
from datetime import date, timedelta

import pytest

from app.models import Bucket, Category, Transaction
from app.services import (
    get_insights_bucket_breakdown,
    get_insights_budget_status,
    get_insights_category_trend,
    get_insights_summary,
    resolve_insight_period,
)


@pytest.fixture()
def data(db, authed):
    """Two buckets, two categories and a handful of transactions."""
    other = Bucket(household_id=authed.household_id, name="Other Bucket")
    db.add(other)
    food = Category(household_id=authed.household_id, name="Food")
    travel = Category(household_id=authed.household_id, name="Travel")
    db.add_all([food, travel])
    db.flush()

    today = date.today()
    rows = [
        (authed.bucket_id, food.id, 100, today),
        (authed.bucket_id, travel.id, 50, today),
        (other.id, food.id, 25, today),
        (other.id, travel.id, 75, today - timedelta(days=40)),
    ]
    for bucket_id, cat_id, amount, when in rows:
        db.add(Transaction(
            bucket_id=bucket_id, household_id=authed.household_id,
            amount=amount, currency="EUR", type="expense",
            category_id=cat_id, transaction_date=when, paid_by=authed.user_id,
        ))
    db.commit()
    authed.other_bucket_id = other.id
    authed.food_id = food.id
    authed.travel_id = travel.id
    return authed


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def test_all_time_has_no_bounds():
    p = resolve_insight_period("all_time")
    assert p["start"] is None and p["end"] is None
    assert p["all_time"] is True


def test_this_month_starts_on_the_first():
    today = date(2026, 7, 27)
    p = resolve_insight_period("this_month", today=today)
    assert p["start"] == date(2026, 7, 1)
    assert p["end"] == today
    assert p["is_current_month"] is True


def test_last_month_covers_the_whole_previous_month():
    p = resolve_insight_period("last_month", today=date(2026, 7, 27))
    assert p["start"] == date(2026, 6, 1)
    assert p["end"] == date(2026, 6, 30)


def test_last_month_across_a_year_boundary():
    p = resolve_insight_period("last_month", today=date(2026, 1, 15))
    assert p["start"] == date(2025, 12, 1)
    assert p["end"] == date(2025, 12, 31)


def test_last_3m_wraps_the_year():
    p = resolve_insight_period("last_3m", today=date(2026, 2, 10))
    assert p["start"] == date(2025, 11, 1)


def test_custom_range_is_honoured():
    p = resolve_insight_period("custom", "2026-01-01", "2026-03-31")
    assert p["start"] == date(2026, 1, 1)
    assert p["end"] == date(2026, 3, 31)


def test_reversed_custom_range_is_swapped():
    p = resolve_insight_period("custom", "2026-03-31", "2026-01-01")
    assert p["start"] == date(2026, 1, 1)
    assert p["end"] == date(2026, 3, 31)


def test_unparseable_custom_falls_back_to_this_month():
    """It used to silently become all-time under a 'custom' label."""
    p = resolve_insight_period("custom", "garbage", "nonsense", today=date(2026, 7, 27))
    assert p["preset"] == "this_month"
    assert p["start"] == date(2026, 7, 1)
    assert p["all_time"] is False


def test_unknown_preset_falls_back_to_this_month():
    p = resolve_insight_period("wat", today=date(2026, 7, 27))
    assert p["preset"] == "this_month"


# ---------------------------------------------------------------------------
# Filter consistency
# ---------------------------------------------------------------------------

def test_bucket_breakdown_respects_bucket_filter(db, data):
    """This chart used to ignore bucket_ids and render every bucket."""
    rows = get_insights_bucket_breakdown(
        db, data.household_id, None, None, bucket_ids=[data.bucket_id]
    )
    assert [r["bucket"].id for r in rows] == [data.bucket_id]
    assert rows[0]["total"] == 150.0


def test_bucket_breakdown_totals_match_the_summary(db, data):
    """Breakdown percentages must add up against the headline total."""
    summary = get_insights_summary(db, data.household_id, None, None)
    rows = get_insights_bucket_breakdown(db, data.household_id, None, None)
    assert round(sum(r["total"] for r in rows), 2) == summary["total_spent"]


def test_summary_respects_category_filter(db, data):
    s = get_insights_summary(db, data.household_id, None, None,
                             category_ids=[data.food_id])
    assert s["total_spent"] == 125.0


def test_budget_status_respects_bucket_filter(db, data):
    b = db.get(Bucket, data.bucket_id)
    b.budget = 200
    other = db.get(Bucket, data.other_bucket_id)
    other.budget = 200
    db.commit()

    rows = get_insights_budget_status(db, data.household_id, None, None,
                                      bucket_ids=[data.bucket_id])
    assert [r["bucket"].id for r in rows] == [data.bucket_id]


def test_budget_status_reports_true_percentage_over_100(db, data):
    """pct is clamped for the bar width; pct_actual carries the real number."""
    b = db.get(Bucket, data.bucket_id)
    b.budget = 100
    db.commit()

    row = next(r for r in get_insights_budget_status(db, data.household_id, None, None)
               if r["bucket"].id == data.bucket_id)
    assert row["over_budget"] is True
    assert row["pct"] == 100          # clamped for display
    assert row["pct_actual"] == 150.0  # true value
    assert row["remaining"] == -50.0


def test_budget_status_excludes_forecast_excluded_rows(db, data):
    b = db.get(Bucket, data.bucket_id)
    b.budget = 500
    for t in db.query(Transaction).filter_by(bucket_id=data.bucket_id).all():
        t.exclude_from_forecast = True
    db.commit()

    row = next(r for r in get_insights_budget_status(db, data.household_id, None, None)
               if r["bucket"].id == data.bucket_id)
    assert row["spent"] == 0.0


# ---------------------------------------------------------------------------
# Chart scaling
# ---------------------------------------------------------------------------

def test_category_trend_max_is_the_largest_monthly_value(db, data):
    """max_value used to be computed as a whole-period sum, which squashed
    every bar to a fraction of its correct height."""
    trend = get_insights_category_trend(db, data.household_id, n_months=6)
    all_values = [v for s in trend["series"] for v in s["values"]]
    assert trend["max_value"] == max(all_values)
    # Every bar must fit within the axis.
    assert all(v <= trend["max_value"] for v in all_values)


def test_category_trend_month_count(db, data):
    trend = get_insights_category_trend(db, data.household_id, n_months=6)
    assert len(trend["months"]) == 6
    for s in trend["series"]:
        assert len(s["values"]) == 6


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "", "preset=this_month", "preset=last_month", "preset=last_3m",
    "preset=last_6m", "preset=this_year", "preset=all_time",
    "preset=custom&start_date=2026-01-01&end_date=2026-06-30",
    "preset=custom&start_date=bad&end_date=bad",
    "preset=nonsense", "bucket_type=bills",
])
def test_insights_page_renders(client, data, query):
    assert client.get(f"/insights?{query}").status_code == 200


def test_htmx_request_returns_a_bare_fragment(client, data):
    r = client.get("/insights?preset=all_time", headers={"HX-Request": "true"})
    assert r.status_code == 200
    # The swap target id must survive, or subsequent filter changes hit nothing.
    assert 'id="insights-body"' in r.text
    assert "<!DOCTYPE" not in r.text


def test_full_page_load_is_not_a_fragment(client, data):
    r = client.get("/insights")
    assert "<!DOCTYPE" in r.text or "<html" in r.text

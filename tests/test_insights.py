"""Insights: date presets, filter consistency and chart scaling."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.clock import local_today
from app.models import Bucket, Category, HouseholdMember, Transaction, TransactionSplit
from app.services import (
    get_insights_bucket_breakdown,
    get_insights_budget_status,
    get_insights_category_breakdown,
    get_insights_category_trend,
    get_insights_summary,
    get_monthly_trend,
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

    today = local_today()
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


def test_budget_status_counts_one_off_purchases(db, authed):
    """exclude_from_forecast only affects projections, not actual budget spend."""
    b = db.get(Bucket, authed.bucket_id)
    b.budget = 100
    when = local_today()
    for amount, one_off in ((Decimal("127.60"), False), (Decimal("99"), True)):
        db.add(Transaction(
            bucket_id=authed.bucket_id, household_id=authed.household_id,
            amount=amount, currency="EUR", type="expense", transaction_date=when,
            paid_by=authed.user_id, exclude_from_forecast=one_off,
        ))
    db.commit()

    row = next(r for r in get_insights_budget_status(db, authed.household_id, None, None)
               if r["bucket"].id == authed.bucket_id)
    assert row["spent"] == Decimal("226.60")
    assert row["over_budget"] is True
    # Every actual-spend figure includes the one-off...
    assert get_insights_summary(db, authed.household_id, None, None)["total_spent"] == Decimal("226.60")
    assert get_monthly_trend(db, authed.household_id, 1)[-1]["total"] == Decimal("226.60")
    # ...while the projection's trend baseline ignores it.
    from app.services.insights import _sum_expenses_by
    month = (when.year, when.month)
    assert _sum_expenses_by(db, authed.household_id, None, None, group_by="month",
                            include_one_offs=False)[month] == Decimal("127.60")


# ---------------------------------------------------------------------------
# Who paid
# ---------------------------------------------------------------------------

@pytest.fixture()
def duo(db, authed):
    from tests.test_household_settlement import _add_member
    partner = _add_member(db, authed.household_id, "partner")
    db.commit()
    authed.partner_id = partner.id
    return authed


def _paid(db, ctx, amount, splits=(), payer="__me__"):
    t = Transaction(
        bucket_id=ctx.bucket_id, household_id=ctx.household_id, amount=amount,
        currency="EUR", type="expense", transaction_date=local_today(),
        paid_by=ctx.user_id if payer == "__me__" else payer,
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


def test_who_paid_credits_the_full_amount_to_the_payer(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(a, 50), (b, 50)])
    s = get_insights_summary(db, duo.household_id, None, None)
    assert s["total_spent"] == Decimal("100")
    assert s["paid_by"][a]["paid"] == Decimal("100")
    assert s["paid_by"][a]["share"] == Decimal("50")
    assert s["paid_by"][b]["paid"] == Decimal("0")
    assert s["paid_by"][b]["share"] == Decimal("50")
    assert s["paid_by"][a]["amount"] == s["paid_by"][a]["paid"]


def test_partial_split_remainder_is_the_payers_share(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(b, 50)])
    s = get_insights_summary(db, duo.household_id, None, None)
    assert (s["paid_by"][a]["paid"], s["paid_by"][a]["share"]) == (Decimal("100"), Decimal("50"))
    assert (s["paid_by"][b]["paid"], s["paid_by"][b]["share"]) == (Decimal("0"), Decimal("50"))


def test_paid_sums_to_total_spent_including_unassigned(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(a, 50), (b, 50)])
    _paid(db, duo, 30, payer=b)
    _paid(db, duo, 20, payer=None)
    s = get_insights_summary(db, duo.household_id, None, None)
    assert s["total_spent"] == Decimal("150")
    assert sum(d["paid"] for d in s["paid_by"].values()) == s["total_spent"]
    assert s["paid_by"]["unassigned"]["name"] == "Unassigned"
    assert s["paid_by"]["unassigned"]["paid"] == Decimal("20")


def test_paid_by_filter_means_payer_everywhere(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(a, 50), (b, 50)])          # A paid, B owes a share
    s = get_insights_summary(db, duo.household_id, None, None, paid_by=b)
    assert s["total_spent"] == Decimal("0")
    s = get_insights_summary(db, duo.household_id, None, None, paid_by=a)
    assert s["total_spent"] == Decimal("100")
    assert get_insights_category_breakdown(db, duo.household_id, None, None, paid_by=b) == []
    rows = get_insights_category_breakdown(db, duo.household_id, None, None, paid_by=a)
    assert sum(r["amount"] for r in rows) == Decimal("100")


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


def test_paid_and_share_both_sum_to_total_with_edge_cases(db, duo):
    from app.models import User
    from app.services import delete_transaction
    from tests.test_household_settlement import _add_member
    a, b = duo.user_id, duo.partner_id
    gone = _add_member(db, duo.household_id, "gone")
    db.commit()
    gone_id = gone.id
    _paid(db, duo, 100, [(a, 50), (b, 50)])
    _paid(db, duo, 20, payer=None)                                # no payer, no split
    t = _paid(db, duo, 30, payer=b)
    t.exchange_rate = 2                                           # 60 base
    db.commit()
    deleted = _paid(db, duo, 777)
    delete_transaction(db, deleted)
    _paid(db, duo, 40, payer=gone_id)
    db.query(HouseholdMember).filter_by(user_id=gone_id).delete()
    db.commit()

    s = get_insights_summary(db, duo.household_id, None, None)
    assert s["total_spent"] == Decimal("220")
    assert sum(d["paid"] for d in s["paid_by"].values()) == s["total_spent"]
    assert sum(d["share"] for d in s["paid_by"].values()) == s["total_spent"]
    assert s["paid_by"][gone_id]["name"].startswith("Former member")
    assert s["paid_by"]["unassigned"]["share"] == Decimal("20")
    assert db.get(User, gone_id) is not None


def test_forecast_ignores_one_off_purchases(db, authed):
    from app.models import TransactionType
    from app.services import get_forecast
    today = local_today()

    def add(amount, when, one_off=False):
        db.add(Transaction(
            bucket_id=authed.bucket_id, household_id=authed.household_id,
            amount=amount, currency="EUR", exchange_rate=1, type=TransactionType.expense,
            transaction_date=when, paid_by=authed.user_id, exclude_from_forecast=one_off,
        ))

    # three complete past months of history, plus this month's spend
    y, m = today.year, today.month
    for back in (1, 2, 3):
        mm = m - back
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        add(300, date(yy, mm, 10))
        add(500, date(yy, mm, 11), one_off=True)     # one-off history must not lift the baseline
    add(Decimal("127.60"), today)
    db.commit()
    base = get_forecast(db, authed.household_id)

    add(99, today, one_off=True)
    db.commit()
    with_one_off = get_forecast(db, authed.household_id)

    assert base["spend_so_far"] == Decimal("127.60")
    assert base["baseline"] == Decimal("300")
    for key in ("spend_so_far", "projected", "baseline"):
        assert with_one_off[key] == base[key]


def test_dashboard_month_and_all_time_summary_count_one_offs(db, authed):
    from app.services import get_all_time_summary, get_month_summary
    today = local_today()
    for amount, one_off in ((Decimal("127.60"), False), (Decimal("99"), True)):
        db.add(Transaction(
            bucket_id=authed.bucket_id, household_id=authed.household_id,
            amount=amount, currency="EUR", type="expense", transaction_date=today,
            paid_by=authed.user_id, exclude_from_forecast=one_off,
        ))
    db.commit()
    assert get_month_summary(db, authed.household_id, today.year, today.month)["total_spent"] == Decimal("226.60")
    assert get_all_time_summary(db, authed.household_id)["total_spent"] == Decimal("226.60")


# ---------------------------------------------------------------------------
# Payment-method breakdown
# ---------------------------------------------------------------------------

def _pay(db, ctx, amount, method, rate=None, payer="__me__", deleted=False):
    from app.clock import utcnow_naive
    t = Transaction(
        bucket_id=ctx.bucket_id, household_id=ctx.household_id, amount=amount,
        currency="EUR", type="expense", transaction_date=local_today(),
        paid_by=ctx.user_id if payer == "__me__" else payer,
        payment_method=method, exchange_rate=rate,
        deleted_at=utcnow_naive() if deleted else None,
    )
    db.add(t)
    db.commit()
    return t


def _by_method(db, ctx, **filters):
    from app.services import InsightFilters, build_insights
    return build_insights(db, ctx.household_id, InsightFilters(preset="all_time", **filters))


def test_by_method_two_cash_one_card(db, authed):
    for m in ("cash", "cash", "card"):
        _pay(db, authed, 10, m)
    data = _by_method(db, authed)
    rows = data["by_method"]
    assert [r["method"] for r in rows] == ["cash", "card"]
    assert rows[0]["amount"] == Decimal("20.00")
    assert rows[0]["pct"] == Decimal("66.7")
    assert rows[0]["label"] == "Cash"
    assert data["cash_share"] == Decimal("66.7")


def test_by_method_uses_exchange_rates_and_omits_zero(db, authed):
    _pay(db, authed, 10, "cash", rate=Decimal("2"))     # 20 base
    _pay(db, authed, 20, "card", rate=Decimal("0.5"))   # 10 base
    _pay(db, authed, 10, "card")                        # 10 base
    data = _by_method(db, authed)
    amounts = {r["method"]: r["amount"] for r in data["by_method"]}
    assert amounts == {"cash": Decimal("20.00"), "card": Decimal("20.00")}
    assert data["cash_share"] == Decimal("50.0")


def test_by_method_respects_paid_by_and_soft_delete(db, duo):
    _pay(db, duo, 10, "cash")
    _pay(db, duo, 30, "card", payer=duo.partner_id)
    _pay(db, duo, 50, "cash", deleted=True)
    data = _by_method(db, duo, paid_by=duo.user_id)
    assert [(r["method"], r["amount"]) for r in data["by_method"]] == [("cash", Decimal("10.00"))]
    assert data["cash_share"] == Decimal("100.0")
    assert _by_method(db, duo)["cash_share"] == Decimal("25.0")


def test_cash_share_is_zero_without_spending(db, authed):
    data = _by_method(db, authed)
    assert data["by_method"] == []
    assert data["cash_share"] == Decimal("0.0")


from tests.test_api import api  # noqa: E402,F401  (fixture)


def test_by_method_in_api(client, db, api):
    headers, hh = api
    for m in ("cash", "cash", "card"):
        _pay(db, hh, 10, m)
    body = client.get("/api/v1/insights?preset=all_time", headers=headers).json()
    assert body["by_method"][0]["method"] == "cash"
    assert body["cash_share"] == 66.7


def test_by_method_in_widget(client, db, authed):
    for m in ("cash", "cash", "card"):
        _pay(db, authed, 10, m)
    page = client.get("/insights?preset=all_time").text
    assert "Payment method" in page and "Cash" in page and "Card" in page
    assert "Cash share" in page
    assert "by_method" in page      # widget toggle key

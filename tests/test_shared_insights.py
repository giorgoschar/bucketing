"""
Insights are correct for shared amounts.

* A shared expense with blank splits stores an equal split, so insights, /me
  and settle-up all see the same shares.
* The insights "Person" filter (query param ``paid_by``, kept for old links)
  selects the expenses a person takes part in and reports *their share*.
* Budget status honours the category and person filters.
* Skipped bill occurrences are not "due".

Scenario used throughout: rent 1100 paid 800 / 300 directly ("each paid their
own share") and groceries paid by one person and shared equally.
"""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import (
    BillOccurrence,
    Bucket,
    Category,
    OccurrenceStatus,
    PayerMode,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services import (
    InsightFilters,
    build_insights,
    get_bills_due_month_total,
    get_insights_bills_due,
    get_insights_budget_status,
)
from app.services.money import equal_split
from app.services.person import get_person_summary
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member

D = Decimal


@pytest.fixture()
def duo(db, authed):
    partner = _add_member(db, authed.household_id, "flatmate")
    db.commit()
    authed.partner_id = partner.id
    return authed


def _expense(db, ctx, amount, *, payer="__me__", splits=(), mode="single",
             category_id=None, method="card", when=None, type_="expense"):
    t = Transaction(
        bucket_id=ctx.bucket_id, household_id=ctx.household_id, amount=amount,
        currency="EUR", type=TransactionType(type_), transaction_date=when or local_today(),
        paid_by=ctx.user_id if payer == "__me__" else payer, payer_mode=mode,
        category_id=category_id, payment_method=method,
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


def _rent(db, ctx, **kw):
    return _expense(db, ctx, 1100, payer=None, mode=PayerMode.own_share.value,
                    splits=[(ctx.user_id, 800), (ctx.partner_id, 300)], **kw)


def _category(db, ctx, name):
    c = Category(household_id=ctx.household_id, name=name)
    db.add(c)
    db.commit()
    return c


def _insights(db, ctx, **filters):
    return build_insights(db, ctx.household_id, InsightFilters(preset="this_month", **filters))


def _form(ctx, **extra):
    return {
        "bucket_id": ctx.bucket_id, "transaction_date": local_today().isoformat(),
        "type": "expense", **extra,
    }


def _splits(db, txn_id):
    db.expire_all()
    t = db.get(Transaction, txn_id)
    return {s.user_id: D(str(s.amount)) for s in t.splits}


# ---------------------------------------------------------------------------
# 1. Equal split is stored
# ---------------------------------------------------------------------------

def test_equal_split_divides_exactly_and_payer_takes_the_cent():
    shares = equal_split(D("10.00"), ["a", "b", "c"], payer="b")
    assert shares == {"a": D("3.33"), "b": D("3.34"), "c": D("3.33")}
    assert sum(shares.values()) == D("10.00")


def test_equal_split_without_payer_gives_the_cent_to_the_first_member():
    shares = equal_split(D("0.05"), ["b", "a"], payer=None)
    assert shares == {"a": D("0.03"), "b": D("0.02")}


def test_equal_split_even_amount():
    assert equal_split(D("100"), ["a", "b"], payer="a") == {"a": D("50.00"), "b": D("50.00")}


def test_shared_create_with_blank_splits_stores_an_equal_split(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data=_form(
        duo, amount="10.01", is_shared="on", paid_by=duo.partner_id,
    ))
    assert r.status_code == 302, r.text
    t = db.query(Transaction).one()
    # The odd cent sits with the payer; the shares add up to the total exactly.
    assert _splits(db, t.id) == {duo.user_id: D("5.00"), duo.partner_id: D("5.01")}


def test_shared_create_keeps_explicit_splits(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data=_form(
        duo, amount="90", is_shared="on",
        **{f"split_{duo.user_id}": "30", f"split_{duo.partner_id}": "60"},
    ))
    assert r.status_code == 302, r.text
    t = db.query(Transaction).one()
    assert _splits(db, t.id) == {duo.user_id: D("30"), duo.partner_id: D("60")}


def test_unshared_create_stores_no_split(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data=_form(
        duo, amount="40", is_shared="off",
    ))
    assert r.status_code == 302
    assert db.query(TransactionSplit).count() == 0


def test_shared_create_in_a_one_person_household_stores_no_split(client, db, authed):
    r = client.post("/transactions", headers=authed.headers, data=_form(
        authed, amount="40", is_shared="on",
    ))
    assert r.status_code == 302
    assert db.query(TransactionSplit).count() == 0


def test_shared_income_stores_no_split(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data=_form(
        duo, amount="40", is_shared="on", type="income", paid_by=duo.user_id,
    ))
    assert r.status_code == 302
    assert db.query(TransactionSplit).count() == 0


def test_edit_marked_shared_with_blank_splits_stores_an_equal_split(client, db, duo):
    t = _expense(db, duo, 60)
    r = client.post(f"/transactions/{t.id}/edit", headers=duo.headers, data=_form(
        duo, amount="60", paid_by=duo.user_id, is_shared="on",
    ))
    assert r.status_code == 302
    assert _splits(db, t.id) == {duo.user_id: D("30.00"), duo.partner_id: D("30.00")}


def test_edit_marked_not_shared_drops_the_split(client, db, duo):
    t = _expense(db, duo, 60, splits=[(duo.user_id, 30), (duo.partner_id, 30)])
    # The hidden split inputs still post their values when the toggle is off.
    r = client.post(f"/transactions/{t.id}/edit", headers=duo.headers, data=_form(
        duo, amount="60", paid_by=duo.user_id, is_shared="off",
        **{f"split_{duo.user_id}": "30", f"split_{duo.partner_id}": "30"},
    ))
    assert r.status_code == 302
    assert _splits(db, t.id) == {}


def test_edit_without_shared_flag_keeps_old_behaviour(client, db, duo):
    t = _expense(db, duo, 60)
    r = client.post(f"/transactions/{t.id}/edit", headers=duo.headers, data=_form(
        duo, amount="60", paid_by=duo.user_id,
    ))
    assert r.status_code == 302
    assert _splits(db, t.id) == {}


def test_edit_page_posts_the_shared_flag(client, db, duo):
    t = _expense(db, duo, 60)
    page = client.get(f"/transactions/{t.id}/edit").text
    assert 'name="is_shared"' in page


def test_equal_split_makes_insights_and_settlement_agree(client, db, duo):
    from app.services import get_member_balances

    db.get(Bucket, duo.bucket_id).enable_settlement = True
    db.commit()
    client.post("/transactions", headers=duo.headers, data=_form(
        duo, amount="60", is_shared="on", paid_by=duo.user_id,
    ))
    summary = _insights(db, duo)["summary"]["paid_by"]
    assert summary[duo.user_id]["share"] == D("30.00")
    assert summary[duo.partner_id]["share"] == D("30.00")
    nets = {b["user_id"]: b["net"] for b in get_member_balances(db, duo.household_id)}
    assert nets[duo.user_id] == D("30.00")
    assert nets[duo.partner_id] == D("-30.00")


def _settle_bucket(db, ctx):
    db.get(Bucket, ctx.bucket_id).enable_settlement = True
    db.commit()


def test_unsplit_expense_in_a_settlement_bucket_is_shared_everywhere(db, duo):
    """An old Spotify payment (no splits) that settle-up shares equally is
    shared equally in insights, the Person filter and /me as well."""
    from app.services import get_member_balances

    _settle_bucket(db, duo)
    a, b = duo.user_id, duo.partner_id
    _expense(db, duo, 10)                                       # Spotify, no splits
    _expense(db, duo, 30, payer=b, splits=[(a, 15), (b, 15)])
    nets = {r["user_id"]: r["net"] for r in get_member_balances(db, duo.household_id)}
    assert nets == {a: D("-10.00"), b: D("10.00")}

    who = _insights(db, duo)["summary"]["paid_by"]
    assert who[a]["share"] == who[b]["share"] == D("20.00")
    for uid in (a, b):
        person = _insights(db, duo, paid_by=uid)
        assert person["summary"]["total_spent"] == D("20.00"), uid
        assert person["kpis"]["count"] == 2, uid
        me = get_person_summary(db, duo.household_id, uid, local_today().replace(day=1),
                                local_today())
        assert me["my_share"] == D("20.00"), uid
        # Paid out minus my share is the settle-up position.
        assert me["balance"] == nets[uid], uid


def test_unsplit_expense_outside_settle_up_stays_with_the_payer(db, duo):
    a, b = duo.user_id, duo.partner_id
    _expense(db, duo, 10)
    _expense(db, duo, 30, payer=b, splits=[(a, 15), (b, 15)])
    who = _insights(db, duo)["summary"]["paid_by"]
    assert (who[a]["share"], who[b]["share"]) == (D("25.00"), D("15.00"))
    assert _insights(db, duo, paid_by=b)["summary"]["total_spent"] == D("15.00")


def test_unsplit_expense_excluded_from_settle_up_stays_with_the_payer(db, duo):
    _settle_bucket(db, duo)
    a, b = duo.user_id, duo.partner_id
    t = _expense(db, duo, 10)
    t.exclude_from_settlement = True
    db.commit()
    _expense(db, duo, 30, payer=b, splits=[(a, 15), (b, 15)])
    assert _insights(db, duo, paid_by=b)["summary"]["total_spent"] == D("15.00")
    assert get_person_summary(db, duo.household_id, a)["my_share"] == D("25.00")


def test_trip_per_person_follows_settle_up(db, duo):
    from app.models import BucketType
    from app.services.buckets import get_trip_summary

    _settle_bucket(db, duo)
    db.get(Bucket, duo.bucket_id).type = BucketType.trip
    db.commit()
    a, b = duo.user_id, duo.partner_id
    _expense(db, duo, 10)
    _expense(db, duo, 30, payer=b, splits=[(a, 15), (b, 15)])
    rows = get_trip_summary(db, db.get(Bucket, duo.bucket_id))["per_person"]
    assert {r["user_id"]: r["amount"] for r in rows} == {a: D("20.00"), b: D("20.00")}


# ---------------------------------------------------------------------------
# 2. Person filter is share-based
# ---------------------------------------------------------------------------

def test_person_filter_reports_the_persons_share_everywhere(db, duo):
    food = _category(db, duo, "Food")
    _expense(db, duo, 100, splits=[(duo.user_id, 50), (duo.partner_id, 50)],
             category_id=food.id, method="cash")
    _expense(db, duo, 30, category_id=food.id)            # mine alone

    data = _insights(db, duo, paid_by=duo.partner_id)
    assert data["summary"]["total_spent"] == D("50.00")
    assert data["kpis"]["total"] == D("50.00")
    assert data["kpis"]["count"] == 1
    assert data["kpis"]["largest"]["amount"] == D("50.00")
    assert [r["amount"] for r in data["categories"]] == [D("50.00")]
    assert [r["total"] for r in data["bucket_breakdown"]] == [D("50.00")]
    assert [(r["method"], r["amount"]) for r in data["by_method"]] == [("cash", D("50.00"))]
    assert data["trend"][-1]["total"] == D("50.00")
    assert data["category_trend"]["series"][0]["values"][-1] == D("50.00")

    mine = _insights(db, duo, paid_by=duo.user_id)
    assert mine["summary"]["total_spent"] == D("80.00")
    assert mine["kpis"]["count"] == 2
    assert sorted(r["amount"] for r in mine["by_method"]) == [D("30.00"), D("50.00")]


def test_person_filter_includes_expenses_the_person_did_not_pay(db, duo):
    _expense(db, duo, 100, payer=duo.partner_id, splits=[(duo.user_id, 40), (duo.partner_id, 60)])
    assert _insights(db, duo, paid_by=duo.user_id)["summary"]["total_spent"] == D("40.00")


def test_rent_own_share_and_shared_groceries(client, db, duo):
    _rent(db, duo)
    r = client.post("/transactions", headers=duo.headers, data=_form(
        duo, amount="60", is_shared="on", paid_by=duo.user_id,
    ))
    assert r.status_code == 302

    me = _insights(db, duo, paid_by=duo.user_id)
    flatmate = _insights(db, duo, paid_by=duo.partner_id)
    assert me["summary"]["total_spent"] == D("830.00")
    assert flatmate["summary"]["total_spent"] == D("330.00")

    # Who paid, over the expenses each person takes part in (here: both).
    who = flatmate["summary"]["paid_by"]
    assert (who[duo.user_id]["paid"], who[duo.user_id]["share"]) == (D("860.00"), D("830.00"))
    assert (who[duo.partner_id]["paid"], who[duo.partner_id]["share"]) == (D("300.00"), D("330.00"))
    assert "unassigned" not in who
    assert flatmate["summary"]["gross_total"] == D("1160.00")

    everyone = _insights(db, duo)["summary"]
    assert everyone["total_spent"] == everyone["gross_total"] == D("1160.00")


def test_person_filter_keeps_income_received_by_the_person(db, duo):
    from app.models import Bucket
    db.get(Bucket, duo.bucket_id).show_income = True
    db.commit()
    _expense(db, duo, 1000, type_="income")
    assert _insights(db, duo, paid_by=duo.user_id)["income_total"] == D("1000.00")
    assert _insights(db, duo, paid_by=duo.partner_id)["income_total"] == D("0.00")


def test_person_totals_match_the_me_page(client, db, duo):
    """Mixed month: the Person-filtered insights equal /me for each member."""
    a, b = duo.user_id, duo.partner_id
    food = _category(db, duo, "Food")
    home = _category(db, duo, "Home")
    _expense(db, duo, 40, category_id=food.id)                                # solo
    _expense(db, duo, 90, splits=[(a, 30), (b, 60)], category_id=food.id)     # explicit split
    r = client.post("/transactions", headers=duo.headers, data=_form(         # blank → equal
        duo, amount="50", is_shared="on", paid_by=b, category_id=food.id,
    ))
    assert r.status_code == 302
    _rent(db, duo, category_id=home.id)                                       # own share
    _expense(db, duo, 20, payer=None)                                         # no payer
    _expense(db, duo, 999, when=local_today() - timedelta(days=400))          # out of range

    data_start = local_today().replace(day=1)
    for uid, expected in ((a, D("895.00")), (b, D("385.00"))):
        me = get_person_summary(db, duo.household_id, uid, data_start, local_today())
        ins = _insights(db, duo, paid_by=uid)
        assert me["my_share"] == expected
        assert ins["summary"]["total_spent"] == me["my_share"]
        assert ins["kpis"]["total"] == me["my_share"]
        assert sum(r["amount"] for r in ins["categories"]) == me["my_share"]
        assert sum(r["total"] for r in ins["bucket_breakdown"]) == me["my_share"]
        assert {r["name"]: r["amount"] for r in ins["categories"]} == {
            r["name"]: r["amount"] for r in me["by_category"]
        }
        assert ins["trend"][-1]["total"] == me["trend"][-1]["total"]


def test_me_counts_cash_like_the_person_filter(db, duo):
    """Cash not logged yet and labelled cash outs are in /me's totals, as
    they are in the Person-filtered insights; the stash never is."""
    from app.services.cash import add_movement

    a, b = duo.user_id, duo.partner_id
    gifts = _category(db, duo, "Gifts")
    today = local_today()
    _expense(db, duo, 200, payer=a)
    for user, kind, amount, cat in (
        (a, "take", 50, None), (a, "stash_in", 20, None),
        (a, "out", 15, gifts.id), (b, "take", 30, None),
    ):
        add_movement(db, duo.household_id, user, kind, D(amount), "EUR", today, cat)
    start = today.replace(day=1)
    expected = D("250.00")

    me = get_person_summary(db, duo.household_id, a, start, today)
    ins = build_insights(db, duo.household_id, InsightFilters(preset="this_month", paid_by=a))
    assert me["my_share"] == ins["summary"]["total_spent"] == expected
    assert me["paid_out"] == expected          # their own cash
    assert me["balance"] == D("0.00")
    assert {r["name"]: r["amount"] for r in me["by_category"]} == {
        r["name"]: r["amount"] for r in ins["categories"]
    }
    assert me["trend"][-1]["total"] == ins["trend"][-1]["total"] == expected
    # The household total includes everyone's cash.
    assert me["household_total"] == expected + D("30.00")


def test_me_page_shows_cash_not_yet_logged(client, db, duo):
    from app.services.cash import add_movement

    add_movement(db, duo.household_id, duo.user_id, "take", D("45"), "EUR", local_today())
    page = client.get("/me").text
    by_category = page.split("share by category", 1)[1]
    assert "Cash (not yet logged)" in by_category and "45.00" in by_category


def test_html_insights_labels_the_filter_person(client, db, duo):
    _expense(db, duo, 100, splits=[(duo.user_id, 50), (duo.partner_id, 50)])
    page = client.get(f"/insights?paid_by={duo.partner_id}").text
    assert "this person's share" in page
    partial = client.get(f"/insights?paid_by={duo.partner_id}", headers={"HX-Request": "true"})
    assert partial.status_code == 200


def test_api_insights_person_filter_is_share_based(client, db, api):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "partner")
    db.commit()
    hh.partner_id = partner.id
    _expense(db, hh, 100, splits=[(hh.user_id, 50), (partner.id, 50)])
    body = client.get(f"/api/v1/insights?paid_by={partner.id}", headers=headers).json()
    assert body["total_spent"] == 50.0
    assert body["kpis"]["total"] == 50.0


# ---------------------------------------------------------------------------
# 3. Budget status honours the category and person filters
# ---------------------------------------------------------------------------

def test_budget_status_honours_category_filter(db, duo):
    db.get(Bucket, duo.bucket_id).budget = 500
    db.commit()
    food = _category(db, duo, "Food")
    _expense(db, duo, 100, category_id=food.id)
    _expense(db, duo, 50)

    rows = get_insights_budget_status(db, duo.household_id, None, None, category_ids=[food.id])
    assert rows[0]["spent"] == D("100.00")
    data = _insights(db, duo, category_ids=food.id)
    assert data["budget_status"][0]["spent"] == D("100.00")
    assert _insights(db, duo)["budget_status"][0]["spent"] == D("150.00")


def test_budget_status_honours_person_filter(db, duo):
    db.get(Bucket, duo.bucket_id).budget = 500
    db.commit()
    _expense(db, duo, 100, splits=[(duo.user_id, 50), (duo.partner_id, 50)])
    _expense(db, duo, 40)

    data = _insights(db, duo, paid_by=duo.partner_id)
    assert data["budget_status"][0]["spent"] == D("50.00")
    assert _insights(db, duo, paid_by=duo.user_id)["budget_status"][0]["spent"] == D("90.00")


# ---------------------------------------------------------------------------
# 4. Bills due excludes skipped occurrences
# ---------------------------------------------------------------------------

def test_bills_due_excludes_skipped_occurrences(db, duo, make_bill):
    today = local_today()
    make_bill(duo.household_id, duo.bucket_id, amount=45, due=today, name="Internet")
    _, skipped = make_bill(duo.household_id, duo.bucket_id, amount=20, due=today, name="Spotify")
    _, paid = make_bill(duo.household_id, duo.bucket_id, amount=10, due=today, name="Phone")
    db.get(BillOccurrence, skipped.id).status = OccurrenceStatus.skipped
    db.get(BillOccurrence, paid.id).status = OccurrenceStatus.paid
    db.commit()

    start = today.replace(day=1)
    assert get_insights_bills_due(db, duo.household_id, start, today) == D("55.00")
    assert get_bills_due_month_total(db, duo.household_id, today.year, today.month) == D("55.00")


def test_dashboard_bills_due_excludes_skipped(client, db, duo, make_bill):
    today = local_today()
    _, occ = make_bill(duo.household_id, duo.bucket_id, amount=77.77, due=today, name="Gym")
    db.get(BillOccurrence, occ.id).status = OccurrenceStatus.skipped
    db.commit()
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "77.77" not in page.text

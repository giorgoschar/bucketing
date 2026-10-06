"""
The built-in Fuel category and litres.

* Every household has exactly one category with ``system_key='fuel'``. Seeding
  adopts an existing fuel-like category (e.g. "Καύσιμα") instead of adding a
  second one, and the migration does the same for existing households.
* A system category is locked: it cannot be renamed, recoloured, re-iconed or
  deleted, from the settings page or the API. Category rules may still map to it.
* A fuel expense takes a price per litre; the server works out the litres
  (amount / price, 3 dp), never trusts a client value, and clears both fields
  when the expense is not (or no longer) fuel.
* Insights report a Fuel card from those litres, under the usual filters.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.clock import local_today
from app.models import (
    FUEL_SYSTEM_KEY,
    Bucket,
    Category,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.seed import ensure_system_categories, seed_categories
from app.services import InsightFilters, build_insights
from app.services.insights import get_insights_fuel
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member
from tests.test_migrations import _alembic, _db_url

D = Decimal


def _fuel(db, household_id) -> Category:
    return (
        db.query(Category)
        .filter_by(household_id=household_id, system_key=FUEL_SYSTEM_KEY)
        .one()
    )


@pytest.fixture()
def fuel_hh(db, authed):
    """A logged-in household with its Fuel category and a plain category."""
    ensure_system_categories(db, authed.household_id)
    other = Category(household_id=authed.household_id, name="Groceries", icon="🛒")
    db.add(other)
    db.commit()
    authed.fuel_id = _fuel(db, authed.household_id).id
    authed.other_id = other.id
    return authed


def _post_expense(client, ctx, **fields):
    data = {
        "bucket_id": ctx.bucket_id,
        "transaction_date": local_today().isoformat(),
        "amount": "60.00",
        "currency": "EUR",
        "type": "expense",
        "category_id": ctx.fuel_id,
        "paid_by": ctx.user_id,
        **fields,
    }
    return client.post("/transactions", data=data, headers=ctx.headers)


def _latest(db, household_id) -> Transaction:
    db.expire_all()
    return (
        db.query(Transaction)
        .filter_by(household_id=household_id)
        .order_by(Transaction.created_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Seeding and uniqueness
# ---------------------------------------------------------------------------

def test_seed_creates_exactly_one_fuel_category(db, make_household):
    hh = make_household()
    seed_categories(db, hh.household_id)
    seed_categories(db, hh.household_id)  # idempotent
    fuel = (
        db.query(Category)
        .filter_by(household_id=hh.household_id, system_key=FUEL_SYSTEM_KEY)
        .all()
    )
    assert len(fuel) == 1
    assert fuel[0].name == "Fuel"
    assert fuel[0].icon == "⛽"


def test_seed_adopts_an_existing_fuel_like_category(db, make_household):
    hh = make_household()
    mine = Category(household_id=hh.household_id, name="Καύσιμα", icon="🛢️")
    db.add(mine)
    db.commit()
    ensure_system_categories(db, hh.household_id)
    db.commit()
    db.refresh(mine)
    assert mine.system_key == FUEL_SYSTEM_KEY
    names = [c.name for c in db.query(Category).filter_by(household_id=hh.household_id)]
    assert "Fuel" not in names  # adopted, not duplicated


def test_system_key_is_unique_per_household(db, make_household):
    a = make_household()
    b = make_household(name="Other")
    ensure_system_categories(db, a.household_id)
    ensure_system_categories(db, b.household_id)  # each household has its own
    db.commit()
    db.add(Category(household_id=a.household_id, name="Petrol 2", system_key=FUEL_SYSTEM_KEY))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_new_household_gets_the_fuel_category(client, db, authed):
    r = client.post("/settings/household/new", data={"name": "Second home"}, headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    rows = (
        db.query(Category)
        .filter(Category.system_key == FUEL_SYSTEM_KEY)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].household_id != authed.household_id


def test_migration_seeds_fuel_and_adopts_existing(tmp_path):
    """Existing households get a fuel category; a "Καύσιμα" one is reused."""
    db_url = _db_url(tmp_path, "fuel.db")
    assert _alembic(["upgrade", "d8e9f0a1b2c3"], db_url).returncode == 0
    engine = create_engine(db_url)
    hh_a, hh_b, cat_a = (str(uuid.uuid4()) for _ in range(3))
    with engine.begin() as conn:
        for hh in (hh_a, hh_b):
            conn.execute(text(
                "INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"
            ), {"i": hh})
        conn.execute(text(
            "INSERT INTO categories (id, household_id, name, color, icon, is_default) "
            "VALUES (:i, :h, 'Καύσιμα', '#000000', 'x', false)"
        ), {"i": cat_a, "h": hh_a})

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, household_id, name, icon FROM categories WHERE system_key = 'fuel'"
        )).all()
    by_hh = {r.household_id: r for r in rows}
    assert set(by_hh) == {hh_a, hh_b}
    assert by_hh[hh_a].id == cat_a  # adopted
    assert by_hh[hh_b].name == "Fuel" and by_hh[hh_b].icon == "⛽"

    down = _alembic(["downgrade", "d8e9f0a1b2c3"], db_url)
    assert down.returncode == 0, down.stderr
    with engine.connect() as conn:
        names = sorted(r[0] for r in conn.execute(text("SELECT name FROM categories")))
    # Downgrade only drops the columns: expenses may point at the seeded row.
    assert names == ["Fuel", "Καύσιμα"]
    engine.dispose()


# ---------------------------------------------------------------------------
# Locked category
# ---------------------------------------------------------------------------

def test_html_delete_of_fuel_category_is_refused(client, db, fuel_hh):
    r = client.post(f"/settings/categories/{fuel_hh.fuel_id}/delete", headers=fuel_hh.headers)
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Category, fuel_hh.fuel_id) is not None


def test_settings_page_hides_delete_and_shows_lock(client, fuel_hh):
    r = client.get("/settings")
    assert r.status_code == 200
    assert f"/settings/categories/{fuel_hh.fuel_id}/delete" not in r.text
    assert f"/settings/categories/{fuel_hh.other_id}/delete" in r.text
    assert "Built-in category" in r.text


def test_api_cannot_edit_or_delete_fuel_category(client, db, api):  # noqa: F811
    headers, hh = api
    ensure_system_categories(db, hh.household_id)
    db.commit()
    fuel = _fuel(db, hh.household_id)

    r = client.put(f"/api/v1/settings/categories/{fuel.id}", headers=headers,
                   json={"name": "Gas", "color": "#000000", "icon": "x"})
    assert r.status_code == 403
    r = client.delete(f"/api/v1/settings/categories/{fuel.id}", headers=headers)
    assert r.status_code == 403

    db.expire_all()
    fuel = db.get(Category, fuel.id)
    assert (fuel.name, fuel.icon) == ("Fuel", "⛽")

    listed = {c["id"]: c for c in client.get("/api/v1/settings/categories", headers=headers).json()}
    assert listed[fuel.id]["system_key"] == "fuel"
    assert listed[fuel.id]["locked"] is True


def test_category_rule_may_map_to_fuel(db, fuel_hh):
    from app.services.category_rules import learn_rule

    rule = learn_rule(db, fuel_hh.household_id, "Shell Kifisias", fuel_hh.fuel_id)
    db.commit()
    assert rule is not None and rule.category_id == fuel_hh.fuel_id


# ---------------------------------------------------------------------------
# Litres on create / edit / duplicate (HTML)
# ---------------------------------------------------------------------------

def test_create_fuel_expense_computes_litres(client, db, fuel_hh):
    r = _post_expense(client, fuel_hh, fuel_price_per_litre="1.789",
                      fuel_litres="999")  # a client value is never trusted
    assert r.status_code == 302, r.text
    t = _latest(db, fuel_hh.household_id)
    assert t.fuel_price_per_litre == D("1.789")
    assert t.fuel_litres == D("33.538")  # 60 / 1.789 = 33.5382…


def test_fuel_price_accepts_a_comma(client, db, fuel_hh):
    r = _post_expense(client, fuel_hh, fuel_price_per_litre="1,50")
    assert r.status_code == 302, r.text
    assert _latest(db, fuel_hh.household_id).fuel_litres == D("40.000")


@pytest.mark.parametrize("price", ["0", "-1.5", "abc"])
def test_bad_fuel_price_is_rejected(client, db, fuel_hh, price):
    r = _post_expense(client, fuel_hh, fuel_price_per_litre=price)
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_fuel_price_is_dropped_for_other_categories(client, db, fuel_hh):
    r = _post_expense(client, fuel_hh, category_id=fuel_hh.other_id, fuel_price_per_litre="1.80")
    assert r.status_code == 302, r.text
    t = _latest(db, fuel_hh.household_id)
    assert t.fuel_price_per_litre is None and t.fuel_litres is None


def test_fuel_expense_without_price_has_no_litres(client, db, fuel_hh):
    r = _post_expense(client, fuel_hh, fuel_price_per_litre="")
    assert r.status_code == 302, r.text
    t = _latest(db, fuel_hh.household_id)
    assert t.category_id == fuel_hh.fuel_id
    assert t.fuel_litres is None


def _edit(client, ctx, txn_id, **fields):
    data = {
        "bucket_id": ctx.bucket_id,
        "transaction_date": local_today().isoformat(),
        "amount": "60.00",
        "currency": "EUR",
        "type": "expense",
        "category_id": ctx.fuel_id,
        "paid_by": ctx.user_id,
        **fields,
    }
    return client.post(f"/transactions/{txn_id}/edit", data=data, headers=ctx.headers)


def test_edit_recomputes_litres_and_clears_on_category_change(client, db, fuel_hh):
    _post_expense(client, fuel_hh, fuel_price_per_litre="1.50")
    t = _latest(db, fuel_hh.household_id)

    r = _edit(client, fuel_hh, t.id, amount="75", fuel_price_per_litre="1.50")
    assert r.status_code == 302, r.text
    db.expire_all()
    t = db.get(Transaction, t.id)
    assert t.fuel_litres == D("50.000")

    r = _edit(client, fuel_hh, t.id, amount="75", category_id=fuel_hh.other_id,
              fuel_price_per_litre="1.50")
    assert r.status_code == 302, r.text
    db.expire_all()
    t = db.get(Transaction, t.id)
    assert t.fuel_price_per_litre is None and t.fuel_litres is None


def test_edit_with_bad_price_rerenders_with_error(client, db, fuel_hh):
    _post_expense(client, fuel_hh, fuel_price_per_litre="1.50")
    t = _latest(db, fuel_hh.household_id)
    r = _edit(client, fuel_hh, t.id, fuel_price_per_litre="0")
    assert r.status_code == 400
    assert "Price per litre" in r.text


def test_duplicate_copies_fuel_fields(client, db, fuel_hh):
    _post_expense(client, fuel_hh, fuel_price_per_litre="1.50")
    src = _latest(db, fuel_hh.household_id)
    r = client.post(f"/transactions/{src.id}/duplicate", headers=fuel_hh.headers)
    assert r.status_code == 302
    db.expire_all()
    copies = db.query(Transaction).filter(Transaction.id != src.id).all()
    assert len(copies) == 1
    assert copies[0].fuel_price_per_litre == D("1.5000")
    assert copies[0].fuel_litres == D("40.000")


def test_wizard_and_edit_form_offer_the_price_input(client, db, fuel_hh):
    r = client.get("/transactions/new")
    assert r.status_code == 200
    assert '"fuelCategoryId": "' + fuel_hh.fuel_id + '"' in r.text
    assert 'name="fuel_price_per_litre"' in r.text

    _post_expense(client, fuel_hh, fuel_price_per_litre="1.50")
    t = _latest(db, fuel_hh.household_id)
    r = client.get(f"/transactions/{t.id}/edit")
    assert r.status_code == 200
    assert 'name="fuel_price_per_litre"' in r.text
    assert f'data-fuel-category="{fuel_hh.fuel_id}"' in r.text


def test_bucket_rows_show_litres_and_price(client, db, fuel_hh):
    _post_expense(client, fuel_hh, fuel_price_per_litre="1.50")
    r = client.get(f"/buckets/{fuel_hh.bucket_id}")
    assert r.status_code == 200
    assert "40.00 L" in r.text
    assert "1.500/L" in r.text


def test_search_rows_show_litres(client, db, fuel_hh):
    _post_expense(client, fuel_hh, fuel_price_per_litre="1.50")
    r = client.get("/transactions/search?type=expense")
    assert r.status_code == 200
    assert "40.00 L" in r.text


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@pytest.fixture()
def fuel_api(db, api):  # noqa: F811
    headers, hh = api
    ensure_system_categories(db, hh.household_id)
    other = Category(household_id=hh.household_id, name="Groceries")
    db.add(other)
    db.commit()
    hh.fuel_id = _fuel(db, hh.household_id).id
    hh.other_id = other.id
    return headers, hh


def test_api_create_and_update_fuel(client, db, fuel_api):
    headers, hh = fuel_api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "60", "category_id": hh.fuel_id,
        "fuel_price_per_litre": "1.789", "fuel_litres": "1",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert D(str(body["fuel_litres"])) == D("33.538")
    assert D(str(body["fuel_price_per_litre"])) == D("1.789")
    txn_id = body["id"]

    # An omitted price keeps the stored one; litres follow the new amount.
    r = client.put(f"/api/v1/transactions/{txn_id}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "71.56", "category_id": hh.fuel_id,
    })
    assert r.status_code == 200, r.text
    assert D(str(r.json()["fuel_litres"])) == D("40.000")

    # Another category clears both fields.
    r = client.put(f"/api/v1/transactions/{txn_id}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "71.56", "category_id": hh.other_id,
        "fuel_price_per_litre": "1.789",
    })
    assert r.status_code == 200, r.text
    assert r.json()["fuel_litres"] is None
    assert r.json()["fuel_price_per_litre"] is None


def test_api_rejects_zero_price(client, fuel_api):
    headers, hh = fuel_api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "60", "category_id": hh.fuel_id,
        "fuel_price_per_litre": "0",
    })
    assert r.status_code == 422


def test_api_rejects_absurd_litres(client, fuel_api):
    headers, hh = fuel_api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "99999999", "category_id": hh.fuel_id,
        "fuel_price_per_litre": "0.0001",
    })
    assert r.status_code == 400


def test_income_never_gets_litres(client, db, fuel_api):
    headers, hh = fuel_api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "amount": "60", "type": "income", "category_id": hh.fuel_id,
        "fuel_price_per_litre": "1.5",
    })
    assert r.status_code == 201, r.text
    assert r.json()["fuel_litres"] is None


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------

def _fill(db, ctx, amount, price, *, when, rate=1, currency="EUR", bucket_id=None,
          payer="__me__", splits=()):
    amount, price = D(str(amount)), D(str(price))
    t = Transaction(
        bucket_id=bucket_id or ctx.bucket_id, household_id=ctx.household_id,
        amount=amount, currency=currency, exchange_rate=D(str(rate)),
        type=TransactionType.expense, transaction_date=when,
        paid_by=ctx.user_id if payer == "__me__" else payer,
        category_id=ctx.fuel_id, fuel_price_per_litre=price,
        fuel_litres=(amount / price).quantize(D("0.001")),
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


JAN, FEB = date(2026, 1, 10), date(2026, 2, 12)


def test_insights_fuel_totals_and_monthly_trend(db, fuel_hh):
    _fill(db, fuel_hh, 60, "1.50", when=JAN)    # 40 L
    _fill(db, fuel_hh, 90, "1.80", when=FEB)    # 50 L
    # A fuel expense without a price adds no litres and stays out of €/L.
    db.add(Transaction(bucket_id=fuel_hh.bucket_id, household_id=fuel_hh.household_id,
                       amount=30, currency="EUR", type=TransactionType.expense,
                       transaction_date=FEB, paid_by=fuel_hh.user_id,
                       category_id=fuel_hh.fuel_id))
    db.commit()

    fuel = get_insights_fuel(db, fuel_hh.household_id, date(2026, 1, 1), date(2026, 2, 28))
    assert fuel["litres"] == D("90.000")
    assert fuel["spend"] == D("150.00")
    # Weighted: 150 / 90, not the mean of 1.50 and 1.80.
    assert fuel["avg_price_per_litre"] == D("1.667")
    assert fuel["fills"] == 2
    assert fuel["unpriced_count"] == 1
    assert [(m["year"], m["month"]) for m in fuel["months"]] == [(2026, 1), (2026, 2)]
    assert [m["litres"] for m in fuel["months"]] == [D("40.000"), D("50.000")]
    assert [m["avg_price_per_litre"] for m in fuel["months"]] == [D("1.500"), D("1.800")]


def test_insights_fuel_converts_spend_to_base_currency(db, fuel_hh):
    _fill(db, fuel_hh, 60, "1.50", when=JAN)                       # 40 L, 60 EUR
    _fill(db, fuel_hh, 100, "2.00", when=JAN, currency="USD", rate="0.9")  # 50 L, 90 EUR
    fuel = get_insights_fuel(db, fuel_hh.household_id, JAN, JAN)
    assert fuel["litres"] == D("90.000")
    assert fuel["spend"] == D("150.00")
    assert fuel["avg_price_per_litre"] == D("1.667")


def test_insights_fuel_respects_date_and_bucket_filters(db, fuel_hh):
    other = Bucket(household_id=fuel_hh.household_id, name="Car 2")
    db.add(other)
    db.commit()
    _fill(db, fuel_hh, 60, "1.50", when=JAN)
    _fill(db, fuel_hh, 90, "1.80", when=FEB, bucket_id=other.id)

    jan = get_insights_fuel(db, fuel_hh.household_id, JAN, JAN)
    assert jan["litres"] == D("40.000")
    only_other = get_insights_fuel(db, fuel_hh.household_id, None, None, bucket_ids=[other.id])
    assert only_other["litres"] == D("50.000")
    assert get_insights_fuel(db, fuel_hh.household_id, date(2025, 1, 1), date(2025, 1, 31)) is None
    # A category filter without Fuel leaves no fuel data.
    assert get_insights_fuel(db, fuel_hh.household_id, None, None,
                             category_ids=[fuel_hh.other_id]) is None


def test_insights_fuel_person_filter_scales_by_share(db, fuel_hh):
    partner = _add_member(db, fuel_hh.household_id, "partner")
    db.commit()
    # 60 EUR / 40 L shared 45 / 15: the partner's quarter is 10 L and 15 EUR.
    _fill(db, fuel_hh, 60, "1.50", when=JAN,
          splits=[(fuel_hh.user_id, D("45")), (partner.id, D("15"))])
    _fill(db, fuel_hh, 90, "1.80", when=JAN)  # mine alone

    theirs = get_insights_fuel(db, fuel_hh.household_id, JAN, JAN, paid_by=partner.id)
    assert theirs["litres"] == D("10.000")
    assert theirs["spend"] == D("15.00")
    assert theirs["avg_price_per_litre"] == D("1.500")

    mine = get_insights_fuel(db, fuel_hh.household_id, JAN, JAN, paid_by=fuel_hh.user_id)
    assert mine["litres"] == D("80.000")
    assert mine["spend"] == D("135.00")


def test_build_insights_and_api_expose_fuel(client, db, fuel_hh):
    today = local_today()
    _fill(db, fuel_hh, 60, "1.50", when=today)
    data = build_insights(db, fuel_hh.household_id, InsightFilters(preset="this_month"))
    assert data["fuel"]["litres"] == D("40.000")

    r = client.get("/insights")
    assert r.status_code == 200
    assert "Average price" in r.text and "40.00 L" in r.text


def test_insights_page_has_no_fuel_card_without_data(client, db, fuel_hh):
    r = client.get("/insights")
    assert r.status_code == 200
    assert "Average price" not in r.text


def test_api_insights_fuel(client, db, fuel_api):
    headers, hh = fuel_api
    _fill(db, hh, 60, "1.50", when=local_today())
    body = client.get("/api/v1/insights", headers=headers).json()
    assert D(str(body["fuel"]["litres"])) == D("40.000")
    assert D(str(body["fuel"]["avg_price_per_litre"])) == D("1.500")
    assert len(body["fuel"]["months"]) == 1

    last_year = (local_today() - timedelta(days=400)).isoformat()
    body = client.get("/api/v1/insights", headers=headers, params={
        "preset": "custom", "start_date": last_year, "end_date": last_year,
    }).json()
    assert body["fuel"] is None


# ---------------------------------------------------------------------------
# Review fixes
# ---------------------------------------------------------------------------

def test_seed_does_not_adopt_an_ambiguous_gas_category(db, make_household):
    """"Gas" is often the natural-gas utility: it stays an ordinary category."""
    hh = make_household()
    gas = Category(household_id=hh.household_id, name="Gas", icon="🔥")
    db.add(gas)
    db.commit()
    ensure_system_categories(db, hh.household_id)
    db.commit()
    db.refresh(gas)
    assert gas.system_key is None
    assert _fuel(db, hh.household_id).name == "Fuel"


def test_seed_prefers_an_exact_fuel_name(db, make_household):
    hh = make_household()
    diesel = Category(household_id=hh.household_id, name="Diesel")
    fuel = Category(household_id=hh.household_id, name="fuel")
    db.add_all([diesel, fuel])
    db.commit()
    ensure_system_categories(db, hh.household_id)
    db.commit()
    assert _fuel(db, hh.household_id).id == fuel.id


def test_migration_skips_gas_and_prefers_exact_fuel(tmp_path):
    db_url = _db_url(tmp_path, "fuel_pref.db")
    assert _alembic(["upgrade", "d8e9f0a1b2c3"], db_url).returncode == 0
    engine = create_engine(db_url)
    hh_gas, hh_mixed, hh_both = (str(uuid.uuid4()) for _ in range(3))
    ids = {}
    with engine.begin() as conn:
        for hh in (hh_gas, hh_mixed, hh_both):
            conn.execute(text(
                "INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"
            ), {"i": hh})
        for hh, name in ((hh_gas, "Gas"), (hh_mixed, "Gas"), (hh_mixed, "Petrol"),
                         (hh_both, "Diesel"), (hh_both, "Fuel")):
            ids[(hh, name)] = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO categories (id, household_id, name, color, icon, is_default) "
                "VALUES (:i, :h, :n, '#000000', 'x', false)"
            ), {"i": ids[(hh, name)], "h": hh, "n": name})

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, household_id, name FROM categories WHERE system_key = 'fuel'"
        )).all()
    by_hh = {r.household_id: r for r in rows}
    assert by_hh[hh_gas].name == "Fuel" and by_hh[hh_gas].id != ids[(hh_gas, "Gas")]
    assert by_hh[hh_mixed].id == ids[(hh_mixed, "Petrol")]
    assert by_hh[hh_both].id == ids[(hh_both, "Fuel")]
    engine.dispose()


def test_api_update_changing_currency_drops_the_stored_price(client, db, fuel_api):
    headers, hh = fuel_api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "50", "currency": "EUR",
        "category_id": hh.fuel_id, "fuel_price_per_litre": "1.80",
    })
    assert r.status_code == 201, r.text
    txn_id = r.json()["id"]

    # The stored price is in EUR: it cannot carry over to a USD amount.
    r = client.put(f"/api/v1/transactions/{txn_id}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "55", "currency": "USD",
        "exchange_rate": "0.9", "category_id": hh.fuel_id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["fuel_price_per_litre"] is None
    assert r.json()["fuel_litres"] is None


def test_insights_fuel_person_filter_skips_unpriced_fills_outside_their_share(db, fuel_hh):
    partner = _add_member(db, fuel_hh.household_id, "partner")
    db.commit()
    _fill(db, fuel_hh, 60, "1.50", when=JAN, payer=partner.id)  # theirs, priced
    # The partner paid, but it is all mine: nothing of it is theirs.
    t = Transaction(bucket_id=fuel_hh.bucket_id, household_id=fuel_hh.household_id,
                    amount=D("60"), currency="EUR", type=TransactionType.expense,
                    transaction_date=JAN, paid_by=partner.id, category_id=fuel_hh.fuel_id)
    db.add(t)
    db.flush()
    db.add(TransactionSplit(transaction_id=t.id, user_id=fuel_hh.user_id, amount=D("60")))
    db.commit()

    theirs = get_insights_fuel(db, fuel_hh.household_id, JAN, JAN, paid_by=partner.id)
    assert theirs["unpriced_count"] == 0
    everyone = get_insights_fuel(db, fuel_hh.household_id, JAN, JAN)
    assert everyone["unpriced_count"] == 1


def test_switching_away_from_fuel_clears_the_price_in_the_forms():
    """Plan 6.3: another category clears the price, so picking Fuel again
    starts empty instead of resubmitting the old price. (Behaviour is checked
    in a browser; this keeps the wiring from regressing.)"""
    from pathlib import Path

    wizard = Path("static/expense-wizard.js").read_text()
    assert "this.$watch('form.category_id'" in wizard
    assert "this.form.fuel_price_per_litre = ''" in wizard
    edit = Path("templates/transactions/edit.html").read_text()
    assert "$watch('categoryId'" in edit and "$watch('txnType'" in edit
    assert "this.fuelPrice = ''" in edit


def test_insights_fuel_per_car(db, fuel_hh):
    """One bucket per car: each gets its own litres, spend and price per litre."""
    car2 = Bucket(household_id=fuel_hh.household_id, name="Car 2", icon="🚙")
    db.add(car2)
    db.commit()
    _fill(db, fuel_hh, 60, "1.50", when=JAN)                        # car 1: 40 L
    _fill(db, fuel_hh, 90, "1.80", when=FEB)                        # car 1: 50 L
    _fill(db, fuel_hh, 38, "1.90", when=FEB, bucket_id=car2.id)     # car 2: 20 L

    fuel = get_insights_fuel(db, fuel_hh.household_id, date(2026, 1, 1), date(2026, 2, 28))
    cars = {c["bucket_id"]: c for c in fuel["cars"]}
    assert set(cars) == {fuel_hh.bucket_id, car2.id}
    one, two = cars[fuel_hh.bucket_id], cars[car2.id]
    assert (one["litres"], one["spend"], one["avg_price_per_litre"], one["fills"]) == (
        D("90.000"), D("150.00"), D("1.667"), 2)
    assert (two["litres"], two["spend"], two["avg_price_per_litre"], two["fills"]) == (
        D("20.000"), D("38.00"), D("1.900"), 1)
    assert two["name"] == "Car 2" and two["icon"] == "🚙"
    # Most litres first; each car carries its own monthly trend.
    assert [c["bucket_id"] for c in fuel["cars"]] == [fuel_hh.bucket_id, car2.id]
    assert [(m["month"], m["avg_price_per_litre"]) for m in one["months"]] == [
        (1, D("1.500")), (2, D("1.800"))]
    assert [(m["month"], m["litres"]) for m in two["months"]] == [(2, D("20.000"))]
    # The household figures are unchanged.
    assert fuel["litres"] == D("110.000") and fuel["spend"] == D("188.00")


def test_insights_page_shows_per_car_fuel(client, db, fuel_hh):
    car2 = Bucket(household_id=fuel_hh.household_id, name="Golf", icon="🚙")
    db.add(car2)
    db.commit()
    today = local_today()
    _fill(db, fuel_hh, 60, "1.50", when=today)
    _fill(db, fuel_hh, 38, "1.90", when=today, bucket_id=car2.id)
    page = client.get("/insights").text
    card = page.split('x-show="show(\'fuel\')"', 1)[1].split("x-show=", 1)[0]
    # One section per car, each with its own figures; no cross-car total
    # (different cars may take different fuel).
    first = db.get(Bucket, fuel_hh.bucket_id).name
    assert "Golf" in card and first in card
    assert "€1.900" in card and "€1.500" in card
    assert "38.00" in card and "60.00" in card
    assert "€98.00" not in card and "60.00 L" not in card


def test_insights_fuel_refuels_per_car(db, fuel_hh):
    """Each car lists its refuels, oldest first, for the price-per-refuel chart.
    The price is in household currency; litres follow the Person filter."""
    car2 = Bucket(household_id=fuel_hh.household_id, name="Car 2")
    db.add(car2)
    db.commit()
    _fill(db, fuel_hh, 90, "1.80", when=FEB)
    _fill(db, fuel_hh, 60, "1.50", when=JAN)
    _fill(db, fuel_hh, 100, "2.00", when=FEB, currency="USD", rate="0.9")  # 50 L, 1.80 EUR/L
    _fill(db, fuel_hh, 38, "1.90", when=FEB, bucket_id=car2.id)

    fuel = get_insights_fuel(db, fuel_hh.household_id, date(2026, 1, 1), date(2026, 2, 28))
    cars = {c["bucket_id"]: c for c in fuel["cars"]}
    one = cars[fuel_hh.bucket_id]["refuels"]
    assert [r["date"] for r in one] == [JAN, FEB, FEB]
    assert [r["price_per_litre"] for r in one] == [D("1.500"), D("1.800"), D("1.800")]
    assert [r["litres"] for r in one] == [D("40.000"), D("50.000"), D("50.000")]
    assert [r["spend"] for r in one] == [D("60.00"), D("90.00"), D("90.00")]
    assert [(r["date"], r["price_per_litre"]) for r in cars[car2.id]["refuels"]] == [
        (FEB, D("1.900"))]


def test_insights_page_draws_price_per_refuel(client, db, fuel_hh):
    today = local_today()
    _fill(db, fuel_hh, 60, "1.50", when=today - timedelta(days=3))
    _fill(db, fuel_hh, 66, "1.65", when=today)
    page = client.get("/insights?preset=all_time").text
    card = page.split('x-show="show(\'fuel\')"', 1)[1].split("x-show=", 1)[0]
    assert 'aria-label="Price per litre per refuel' in card
    assert card.count("<circle") == 2            # one point per refuel
    assert "€1.650/L" in card and "40.00 L" in card

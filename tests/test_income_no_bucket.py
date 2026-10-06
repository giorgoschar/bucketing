"""
Income without buckets, and the monthly In / Out / Net.

Income may be logged with no bucket at all (the bucket picker is an optional
disclosure on the income form); expenses and transfers still need one, in the
schema, the service and as a database CHECK. Bucket-less income always counts
as income; bucketed income still respects the bucket's "Track income" switch.
Out is logged expenses plus the cash taken but not logged yet
(app.services.cash), so In / Out / Net is the same on Insights and the
dashboard. Every list, search, export and form must cope with a NULL bucket.
"""

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.clock import local_today
from app.models import (
    Bucket,
    BucketStatus,
    Category,
    Transaction,
    TransactionType,
)
from app.schemas import TransactionCreate
from app.services import InsightFilters, add_movement, build_insights, create_transaction
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

D = Decimal
JAN_10 = date(2026, 1, 10)


def _income(db, ctx, amount, day=JAN_10, *, bucket_id=None, paid_by=None, rate=1, category_id=None):
    t = Transaction(
        bucket_id=bucket_id,
        household_id=ctx.household_id,
        amount=D(str(amount)),
        currency="EUR",
        exchange_rate=rate,
        type=TransactionType.income,
        transaction_date=day,
        paid_by=paid_by,
        category_id=category_id,
    )
    db.add(t)
    db.commit()
    return t


def _expense(db, ctx, amount, day=JAN_10, **kw):
    t = Transaction(
        bucket_id=ctx.bucket_id,
        household_id=ctx.household_id,
        amount=D(str(amount)),
        currency="EUR",
        exchange_rate=1,
        type=TransactionType.expense,
        transaction_date=day,
        paid_by=ctx.user_id,
        **kw,
    )
    db.add(t)
    db.commit()
    return t


def _insights(db, ctx, start="2026-01-01", end="2026-01-31", **filters):
    return build_insights(
        db,
        ctx.household_id,
        InsightFilters(preset="custom", start_date=start, end_date=end, **filters),
    )


def _form(**over):
    data = {
        "transaction_date": local_today().isoformat(),
        "amount": "1200",
        "currency": "EUR",
        "notes": "Salary",
    }
    data.update(over)
    return data


# ---------------------------------------------------------------------------
# HTML income form
# ---------------------------------------------------------------------------


def test_income_form_hides_bucket_picker_by_default(client, authed):
    r = client.get("/income/new")
    assert r.status_code == 200
    assert "Assign to a bucket" in r.text
    # Closed disclosure, "No bucket" chosen.
    assert "<details data-income-bucket class=" in r.text
    assert 'name="bucket_id" value="" checked' in r.text


def test_income_form_opens_picker_for_preselected_bucket(client, authed):
    r = client.get("/income/new", params={"bucket_id": authed.bucket_id})
    assert "<details data-income-bucket open" in r.text
    assert f'value="{authed.bucket_id}"' in r.text


def test_income_without_bucket_is_saved(client, db, authed):
    r = client.post("/income", headers=authed.headers, data=_form(received_by=authed.user_id))
    assert r.status_code == 302
    assert r.headers["location"] == "/transactions/search?type=income"
    t = db.query(Transaction).one()
    assert t.bucket_id is None and t.type == TransactionType.income
    assert t.amount == D("1200") and t.paid_by == authed.user_id


def test_income_blank_bucket_means_none(client, db, authed):
    r = client.post("/income", headers=authed.headers, data=_form(bucket_id=""))
    assert r.status_code == 302
    assert db.query(Transaction).one().bucket_id is None


def test_income_stores_exchange_rate(client, db, authed):
    r = client.post(
        "/income",
        headers=authed.headers,
        data=_form(currency="USD", amount="100", exchange_rate="0.9"),
    )
    assert r.status_code == 302, r.text
    t = db.query(Transaction).one()
    assert t.currency == "USD" and t.exchange_rate == D("0.9")
    # Counted in the household currency.
    data = _insights(db, authed, start="2000-01-01", end="2100-01-01")
    assert data["income_total"] == D("90.00")


@pytest.mark.parametrize("rate", ["0", "-1", "abc"])
def test_income_rejects_bad_exchange_rate(client, db, authed, rate):
    r = client.post(
        "/income", headers=authed.headers, data=_form(currency="USD", exchange_rate=rate)
    )
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_income_rejects_foreign_category(client, db, authed, make_household):
    other = make_household(name="Other", username="someone")
    cat = Category(household_id=other.household_id, name="Theirs")
    db.add(cat)
    db.commit()
    r = client.post("/income", headers=authed.headers, data=_form(category_id=cat.id))
    assert r.status_code in (400, 404)
    assert db.query(Transaction).count() == 0


@pytest.mark.parametrize(
    "change",
    [
        {"show_income": False},
        {"status": BucketStatus.archived},
    ],
)
def test_income_rejects_bucket_that_does_not_track_income(client, db, authed, change):
    bucket = db.get(Bucket, authed.bucket_id)
    for k, v in change.items():
        setattr(bucket, k, v)
    db.commit()
    r = client.post("/income", headers=authed.headers, data=_form(bucket_id=authed.bucket_id))
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


# ---------------------------------------------------------------------------
# API income
# ---------------------------------------------------------------------------


def test_api_income_without_bucket(client, db, api):
    headers, hh = api
    r = client.post("/api/v1/income", headers=headers, json={"amount": 500, "notes": "Bonus"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["bucket_id"] is None and body["type"] == "income"
    assert db.query(Transaction).one().bucket_id is None


def test_api_income_stores_exchange_rate(client, db, api):
    headers, _ = api
    r = client.post(
        "/api/v1/income",
        headers=headers,
        json={"amount": 100, "currency": "GBP", "exchange_rate": "1.17"},
    )
    assert r.status_code == 201, r.text
    assert db.query(Transaction).one().exchange_rate == D("1.17")


@pytest.mark.parametrize(
    "body",
    [
        {"amount": 10, "currency": "XXX"},
        {"amount": 10, "exchange_rate": 0},
        {"amount": 0},
    ],
)
def test_api_income_rejects_bad_fields(client, db, api, body):
    headers, _ = api
    r = client.post("/api/v1/income", headers=headers, json=body)
    assert r.status_code in (400, 422), r.text
    assert db.query(Transaction).count() == 0


def test_api_income_rejects_foreign_category(client, db, api, make_household):
    headers, _ = api
    other = make_household(name="Other", username="someone")
    cat = Category(household_id=other.household_id, name="Theirs")
    db.add(cat)
    db.commit()
    r = client.post("/api/v1/income", headers=headers, json={"amount": 10, "category_id": cat.id})
    assert r.status_code == 404
    assert db.query(Transaction).count() == 0


@pytest.mark.parametrize(
    "change",
    [
        {"show_income": False},
        {"status": BucketStatus.archived},
    ],
)
def test_api_income_rejects_bucket_that_does_not_track_income(client, db, api, change):
    headers, hh = api
    bucket = db.get(Bucket, hh.bucket_id)
    for k, v in change.items():
        setattr(bucket, k, v)
    db.commit()
    r = client.post(
        "/api/v1/income", headers=headers, json={"amount": 10, "bucket_id": hh.bucket_id}
    )
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


# ---------------------------------------------------------------------------
# Expenses (and transfers) still need a bucket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["expense", "transfer"])
def test_schema_requires_bucket_unless_income(kind):
    with pytest.raises(ValidationError, match="bucket"):
        TransactionCreate(amount="5", type=kind)
    with pytest.raises(ValidationError, match="bucket"):
        TransactionCreate(bucket_id="", amount="5", type=kind)
    assert TransactionCreate(amount="5", type="income").bucket_id is None


def test_service_requires_bucket_for_expense(db, authed):
    from app.models import User

    user = db.get(User, authed.user_id)
    data = TransactionCreate.model_construct(
        **{**TransactionCreate(bucket_id="x", amount="5").model_dump(), "bucket_id": None},
    )
    with pytest.raises(HTTPException) as exc:
        create_transaction(db, household_id=authed.household_id, bucket=None, user=user, data=data)
    assert exc.value.status_code == 400
    assert db.query(Transaction).count() == 0


def test_database_rejects_expense_without_bucket(db, authed):
    db.add(
        Transaction(
            household_id=authed.household_id,
            amount=5,
            type=TransactionType.expense,
            transaction_date=JAN_10,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_html_expense_without_bucket_is_rejected(client, db, authed):
    r = client.post(
        "/transactions",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": "2026-01-10",
            "amount": "5",
            "type": "expense",
        },
    )
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_html_wizard_income_without_bucket_is_allowed(client, db, authed):
    r = client.post(
        "/transactions",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": "2026-01-10",
            "amount": "5",
            "type": "income",
        },
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/transactions/search?type=income"
    assert db.query(Transaction).one().bucket_id is None


def test_api_expense_without_bucket_is_rejected(client, db, api):
    headers, _ = api
    r = client.post("/api/v1/transactions", headers=headers, json={"amount": 5})
    assert r.status_code == 422
    assert db.query(Transaction).count() == 0


def test_api_income_transaction_without_bucket(client, db, api):
    headers, _ = api
    r = client.post("/api/v1/transactions", headers=headers, json={"amount": 5, "type": "income"})
    assert r.status_code == 201, r.text
    assert r.json()["bucket_id"] is None


def test_edit_income_to_no_bucket_and_expense_cannot(client, db, authed):
    inc = _income(db, authed, 100, bucket_id=authed.bucket_id)
    r = client.post(
        f"/transactions/{inc.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": "2026-01-10",
            "amount": "100",
            "type": "income",
        },
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/transactions/search?type=income"
    db.expire_all()
    assert db.get(Transaction, inc.id).bucket_id is None

    exp = _expense(db, authed, 20)
    r = client.post(
        f"/transactions/{exp.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": "2026-01-10",
            "amount": "20",
            "type": "expense",
        },
    )
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Transaction, exp.id).bucket_id == authed.bucket_id


def test_edit_keeps_exchange_rate(client, db, authed):
    inc = _income(db, authed, 100, rate=D("0.9"))
    page = client.get(f"/transactions/{inc.id}/edit")
    assert page.status_code == 200
    assert 'name="exchange_rate" value="0.9' in page.text
    r = client.post(
        f"/transactions/{inc.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": "2026-01-10",
            "amount": "100",
            "type": "income",
            "currency": "USD",
            "exchange_rate": "0.9",
        },
    )
    assert r.status_code == 302
    db.expire_all()
    assert db.get(Transaction, inc.id).exchange_rate == D("0.9")


def test_api_update_income_to_no_bucket(client, db, api):
    headers, hh = api
    inc = _income(db, hh, 100, bucket_id=hh.bucket_id)
    r = client.put(
        f"/api/v1/transactions/{inc.id}",
        headers=headers,
        json={"amount": 100, "type": "income", "bucket_id": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["bucket_id"] is None


# ---------------------------------------------------------------------------
# "Track income" holds on every path, not only /income: income put into a
# bucket that does not take it would be saved but never counted in In / Net.
# ---------------------------------------------------------------------------

NO_INCOME = [{"show_income": False}, {"status": BucketStatus.archived}]


def _stop_income(db, bucket_id, change):
    bucket = db.get(Bucket, bucket_id)
    for k, v in change.items():
        setattr(bucket, k, v)
    db.commit()


@pytest.mark.parametrize("change", NO_INCOME)
def test_html_wizard_income_rejects_bucket_that_does_not_track_income(client, db, authed, change):
    _stop_income(db, authed.bucket_id, change)
    r = client.post(
        "/transactions",
        headers=authed.headers,
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-01-10",
            "amount": "5",
            "type": "income",
        },
    )
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


@pytest.mark.parametrize("change", NO_INCOME)
def test_api_transaction_income_rejects_bucket_that_does_not_track_income(client, db, api, change):
    headers, hh = api
    _stop_income(db, hh.bucket_id, change)
    r = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={"amount": 1000, "type": "income", "bucket_id": hh.bucket_id},
    )
    assert r.status_code == 400, r.text
    assert db.query(Transaction).count() == 0


def test_edit_expense_into_income_rejects_bucket_that_does_not_track_income(client, db, authed):
    _stop_income(db, authed.bucket_id, {"show_income": False})
    exp = _expense(db, authed, 1000)
    r = client.post(
        f"/transactions/{exp.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-01-10",
            "amount": "1000",
            "type": "income",
        },
    )
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Transaction, exp.id).type == TransactionType.expense


def test_edit_income_into_bucket_that_does_not_track_income(client, db, authed):
    other = Bucket(household_id=authed.household_id, name="No income", show_income=False)
    db.add(other)
    db.commit()
    inc = _income(db, authed, 100)
    r = client.post(
        f"/transactions/{inc.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": other.id,
            "transaction_date": "2026-01-10",
            "amount": "100",
            "type": "income",
        },
    )
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Transaction, inc.id).bucket_id is None


def test_api_update_expense_into_income_rejects_bucket_that_does_not_track_income(client, db, api):
    headers, hh = api
    _stop_income(db, hh.bucket_id, {"show_income": False})
    exp = _expense(db, hh, 1000)
    r = client.put(
        f"/api/v1/transactions/{exp.id}",
        headers=headers,
        json={"amount": 1000, "type": "income", "bucket_id": hh.bucket_id},
    )
    assert r.status_code == 400, r.text
    db.expire_all()
    assert db.get(Transaction, exp.id).type == TransactionType.expense


@pytest.mark.parametrize("change", NO_INCOME)
def test_edit_income_already_in_bucket_keeps_working(client, db, authed, change):
    # Income logged before the bucket stopped taking it (or was archived) is
    # left where it is: fixing its notes must not fail or move it.
    inc = _income(db, authed, 100, bucket_id=authed.bucket_id)
    _stop_income(db, authed.bucket_id, change)
    r = client.post(
        f"/transactions/{inc.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-01-10",
            "amount": "100",
            "type": "income",
            "notes": "fixed",
        },
    )
    assert r.status_code == 302
    db.expire_all()
    t = db.get(Transaction, inc.id)
    assert t.bucket_id == authed.bucket_id and t.notes == "fixed"


# ---------------------------------------------------------------------------
# The edit form keeps an archived bucket: its select used to list only active
# buckets, so the browser picked the first option and saving moved the row.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["income", "expense"])
def test_edit_page_keeps_archived_bucket_selected(client, db, authed, kind):
    if kind == "income":
        txn = _income(db, authed, 500, bucket_id=authed.bucket_id)
    else:
        txn = _expense(db, authed, 500)
    _stop_income(db, authed.bucket_id, {"status": BucketStatus.archived})
    page = client.get(f"/transactions/{txn.id}/edit")
    assert page.status_code == 200
    assert f'value="{authed.bucket_id}" selected' in page.text
    assert 'value="" selected' not in page.text.split('name="bucket_id"')[1].split("</select>")[0]
    assert "(archived)" in page.text


# ---------------------------------------------------------------------------
# Insights / dashboard: income and In / Out / Net
# ---------------------------------------------------------------------------


def test_bucketless_income_always_counts(db, authed):
    db.get(Bucket, authed.bucket_id).show_income = False
    db.commit()
    _income(db, authed, 1000)
    _income(db, authed, 300, bucket_id=authed.bucket_id)  # bucket does not track income
    data = _insights(db, authed)
    assert data["income_total"] == D("1000.00")
    assert data["kpis"]["income"] == D("1000.00")


def test_bucketed_income_respects_show_income(db, authed):
    _income(db, authed, 300, bucket_id=authed.bucket_id)
    assert _insights(db, authed)["income_total"] == D("300.00")


def test_bucket_filter_leaves_out_bucketless_income(db, authed):
    _income(db, authed, 1000)
    _income(db, authed, 300, bucket_id=authed.bucket_id)
    data = _insights(db, authed, bucket_ids=authed.bucket_id)
    assert data["income_total"] == D("300.00")


def test_person_filter_on_income_is_the_recipient(db, authed):
    partner, _ = _add_member_user(db, authed.household_id, "flatmate")
    _income(db, authed, 1000, paid_by=authed.user_id)
    _income(db, authed, 700, paid_by=partner.id)
    assert _insights(db, authed, paid_by=partner.id)["income_total"] == D("700.00")


def test_in_out_net_includes_cash_not_yet_logged(db, authed):
    _income(db, authed, 1000)
    _expense(db, authed, 200)
    # 50 taken into the wallet, nothing logged: 50 not yet logged.
    add_movement(db, authed.household_id, authed.user_id, "take", D("50"), "EUR", date(2026, 1, 3))
    data = _insights(db, authed)
    assert data["in_out"] == {
        "in": D("1000.00"),
        "out": D("250.00"),
        "logged": D("200.00"),
        "cash_not_logged": D("50.00"),
        "net": D("750.00"),
    }
    assert data["net"] == D("750.00")


def test_in_out_leaves_out_the_stash(db, authed):
    partner, _ = _add_member_user(db, authed.household_id, "flatmate")
    _income(db, authed, 1000)
    add_movement(db, authed.household_id, partner.id, "stash_in", D("80"), "EUR", date(2026, 1, 3))
    data = _insights(db, authed)
    assert data["in_out"]["out"] == D("0.00")
    assert data["in_out"]["net"] == D("1000.00")


def test_insights_page_shows_in_out_net(client, db, authed):
    _income(db, authed, 1000, day=local_today())
    r = client.get("/insights")
    assert r.status_code == 200, r.text[:300]
    for label in (">In<", ">Out<", ">Net<"):
        assert label in r.text


def test_dashboard_in_out_net(client, db, authed):
    today = local_today()
    _income(db, authed, 1000, day=today)
    _expense(db, authed, 200, day=today)
    add_movement(db, authed.household_id, authed.user_id, "take", D("50"), "EUR", today)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "data-in-out" in r.text
    assert "€1,000.00" in r.text and "€250.00" in r.text and "+€750.00" in r.text


def test_dashboard_in_out_shows_without_income_buckets(client, db, authed):
    db.get(Bucket, authed.bucket_id).show_income = False
    db.commit()
    r = client.get("/dashboard")
    assert "data-in-out" in r.text


def test_api_dashboard_in_out(client, db, api):
    headers, hh = api
    today = local_today()
    _income(db, hh, 1000, day=today)
    _expense(db, hh, 200, day=today)
    body = client.get("/api/v1/dashboard", headers=headers).json()
    assert body["income_total"] == 1000.0
    assert body["in_out"]["net"] == 800.0 and body["in_out"]["out"] == 200.0


# ---------------------------------------------------------------------------
# Bucket-less income renders everywhere
# ---------------------------------------------------------------------------


@pytest.fixture()
def bucketless(db, authed):
    t = _income(db, authed, 1234, day=local_today(), paid_by=authed.user_id)
    t.notes = "Paycheck"
    db.commit()
    return t


def test_bucketless_income_in_search(client, bucketless):
    for params in ({"type": "income"}, {"q": "Paycheck"}, {"q": "Bucket"}):
        r = client.get("/transactions/search", params=params)
        assert r.status_code == 200, params
    assert "Paycheck" in client.get("/transactions/search", params={"q": "Paycheck"}).text


def test_bucketless_income_in_dashboard_recent(client, bucketless):
    r = client.get("/dashboard")
    assert r.status_code == 200 and "Paycheck" in r.text


def test_bucketless_income_in_csv_export(client, bucketless):
    r = client.get("/transactions/export")
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))
    row = next(r for r in rows if r[-1] == "Paycheck")
    assert row[1] == "" and row[3] == "income"


def test_bucketless_income_in_duplicates_and_check(client, db, authed, bucketless):
    _income(db, authed, 1234, day=local_today(), paid_by=authed.user_id)
    assert client.get("/transactions/duplicates").status_code == 200
    r = client.get(
        "/transactions/check-duplicate",
        params={"amount": "1234", "transaction_date": local_today().isoformat()},
    )
    assert r.status_code == 200
    assert all(d["bucket"] is None for d in r.json()["duplicates"])


def test_bucketless_income_edit_page_delete_and_duplicate(client, db, authed, bucketless):
    page = client.get(f"/transactions/{bucketless.id}/edit")
    assert page.status_code == 200
    assert "No bucket" in page.text

    r = client.post(f"/transactions/{bucketless.id}/duplicate", headers=authed.headers)
    assert r.status_code == 302 and r.headers["location"] == "/transactions/search?type=income"
    r = client.post(
        f"/transactions/{bucketless.id}/duplicate", headers={**authed.headers, "HX-Request": "true"}
    )
    assert r.status_code == 200 and "Income added" in r.text

    r = client.post(f"/transactions/{bucketless.id}/delete", headers=authed.headers)
    assert r.status_code == 302 and r.headers["location"] == "/transactions/search?type=income"


def test_bucketless_income_in_api_list_and_me(client, db, api):
    headers, hh = api
    _income(db, hh, 10, day=local_today(), paid_by=hh.user_id)
    r = client.get("/api/v1/transactions", headers=headers, params={"type": "income"})
    assert r.status_code == 200
    assert r.json()["items"][0]["bucket_id"] is None


def test_bucketless_income_on_me_and_settlement(client, db, authed, bucketless):
    for path in ("/me", "/settlement", "/insights"):
        assert client.get(path).status_code == 200, path


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_makes_bucket_optional(tmp_path):
    from sqlalchemy import create_engine, inspect

    from tests.test_migrations import _alembic, _db_url

    url = _db_url(tmp_path, "income.db")
    up = _alembic(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr
    cols = {c["name"]: c for c in inspect(create_engine(url)).get_columns("transactions")}
    assert cols["bucket_id"]["nullable"] is True

    down = _alembic(["downgrade", "c7d8e9f0a1b2"], url)
    assert down.returncode == 0, down.stderr
    cols = {c["name"]: c for c in inspect(create_engine(url)).get_columns("transactions")}
    assert cols["bucket_id"]["nullable"] is False
    assert _alembic(["upgrade", "head"], url).returncode == 0

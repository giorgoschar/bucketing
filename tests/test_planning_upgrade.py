"""Production-shaped upgrade (spec §7): the schema production runs (commit
8b01313, alembic head f0a1b2c3d4e5; or e9f0a1b2c3d4 for a database restored
from a pre-Phase-1 backup) with real-looking data, upgraded to head,
then the old app used as a person would: TOTP login, dashboard, bills (pay
one), insights, a trip bucket, search; and the new API on the same data.

The data has what a real database has: a bucketed bill with a paid, an
overdue, a skipped and a year of old-app-generated future entries; a
bucket-less bill the old app paid claim-only; and a paused bill."""

import uuid
from collections import Counter
from datetime import timedelta

import pyotp
import pytest
from dateutil.relativedelta import relativedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.core.clock import local_today
from tests.conftest import PASSWORD, form_csrf
from tests.test_migrations import _alembic, _db_url

PROD_REVISION = "f0a1b2c3d4e5"  # alembic head at commit 8b01313 (production)
PRE_PHASE1_REVISION = "e9f0a1b2c3d4"  # production before Phase 1 (a restored older backup)


def _seed(conn) -> dict:
    today = local_today()
    ids = {
        k: str(uuid.uuid4())
        for k in (
            "hh",
            "user",
            "daily",
            "trip",
            "bill",
            "paid",
            "due",
            "txn",
            "inc",
            "skipped",
            "gym",
            "gym_paid",
            "paused",
            "paused_due",
        )
    }
    ids["secret"] = pyotp.random_base32()
    q = lambda sql, **p: conn.execute(text(sql), p)  # noqa: E731
    q("INSERT INTO households (id, name, default_currency) VALUES (:i, 'Home', 'EUR')", i=ids["hh"])
    q(
        "INSERT INTO users (id, username, display_name, password_hash, session_version, "
        "totp_enabled, totp_secret, email_verified) VALUES (:i, 'giorgos', 'Giorgos', :p, 0, "
        "true, :s, false)",
        i=ids["user"],
        p=hash_password(PASSWORD),
        s=ids["secret"],
    )
    q(
        "INSERT INTO household_members (id, household_id, user_id, role) "
        "VALUES (:i, :h, :u, 'owner')",
        i=str(uuid.uuid4()),
        h=ids["hh"],
        u=ids["user"],
    )
    for key, kind, budget in (("daily", "day2day", 1200), ("trip", "trip", 900)):
        q(
            "INSERT INTO buckets (id, household_id, name, type, status, budget, show_income, "
            "enable_settlement) VALUES (:b, :h, :n, :t, 'active', :g, true, false)",
            b=ids[key],
            h=ids["hh"],
            n=key.title(),
            t=kind,
            g=budget,
        )
    q(
        "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
        "frequency, interval_months, start_date, is_active, is_auto_pay) VALUES (:i, :h, :b, "
        "'Cosmote', 38.90, 'EUR', 'monthly', 1, :s, true, false)",
        i=ids["bill"],
        h=ids["hh"],
        b=ids["daily"],
        s=today - timedelta(days=40),
    )
    q(
        "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, exchange_rate, "
        "type, paid_by, transaction_date, exclude_from_forecast, exclude_from_settlement) "
        "VALUES (:i, :b, :h, 38.90, 'EUR', 1, 'expense', :u, :d, false, false)",
        i=ids["txn"],
        b=ids["daily"],
        h=ids["hh"],
        u=ids["user"],
        d=today - timedelta(days=40),
    )
    q(
        "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, exchange_rate, "
        "type, paid_by, transaction_date, exclude_from_forecast, exclude_from_settlement) "
        "VALUES (:i, :b, :h, 1500, 'EUR', 1, 'income', :u, :d, false, false)",
        i=ids["inc"],
        b=ids["daily"],
        h=ids["hh"],
        u=ids["user"],
        d=today,
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status, transaction_id) "
        "VALUES (:i, :b, :d, 'paid', :t)",
        i=ids["paid"],
        b=ids["bill"],
        d=today - timedelta(days=40),
        t=ids["txn"],
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status) VALUES (:i, :b, :d, 'unpaid')",
        i=ids["due"],
        b=ids["bill"],
        d=today - timedelta(days=10),
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status) "
        "VALUES (:i, :b, :d, 'skipped')",
        i=ids["skipped"],
        b=ids["bill"],
        d=today - timedelta(days=70),
    )
    # The old app generated a bill's entries far ahead, stepping a month at a time.
    for k in range(1, 13):
        q(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status) "
            "VALUES (:i, :b, :d, 'unpaid')",
            i=str(uuid.uuid4()),
            b=ids["bill"],
            d=today - timedelta(days=10) + relativedelta(months=k),
        )
    # A bucket-less bill: the old app's Pay only claimed the entry (no expense).
    q(
        "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
        "frequency, interval_months, start_date, is_active, is_auto_pay) VALUES (:i, :h, NULL, "
        "'Gym', 25, 'EUR', 'monthly', 1, :s, true, false)",
        i=ids["gym"],
        h=ids["hh"],
        s=today - timedelta(days=40),
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status, paid_at, paid_by) "
        "VALUES (:i, :b, :d, 'paid', :p, :u)",
        i=ids["gym_paid"],
        b=ids["gym"],
        d=today - timedelta(days=40),
        p=today - timedelta(days=40),
        u=ids["user"],
    )
    # A paused bill with an entry that would be overdue: hidden everywhere.
    q(
        "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
        "frequency, interval_months, start_date, is_active, is_auto_pay) VALUES (:i, :h, :b, "
        "'Old gym', 30, 'EUR', 'monthly', 1, :s, false, false)",
        i=ids["paused"],
        h=ids["hh"],
        b=ids["daily"],
        s=today - timedelta(days=12),
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status) VALUES (:i, :b, :d, 'unpaid')",
        i=ids["paused_due"],
        b=ids["paused"],
        d=today - timedelta(days=12),
    )
    return ids


@pytest.fixture(params=[PROD_REVISION, PRE_PHASE1_REVISION])
def upgraded(request, tmp_path, monkeypatch):
    db_url = _db_url(tmp_path, "prod.db")
    assert _alembic(["upgrade", request.param], db_url).returncode == 0
    engine = create_engine(db_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as conn:
        ids = _seed(conn)
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr

    import app.core.database as database
    from app.main import app as fastapi_app

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine, raising=False)
    monkeypatch.setattr(database, "SessionLocal", Session, raising=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[database.get_db] = _get_db
    yield TestClient(fastapi_app, follow_redirects=False), Session, ids
    fastapi_app.dependency_overrides.clear()
    engine.dispose()


def test_old_app_works_after_the_upgrade(upgraded):
    client, Session, ids = upgraded
    r = client.post(
        "/login", data={"username": "giorgos", "password": PASSWORD, **form_csrf(client, "/login")}
    )
    assert r.status_code == 302
    r = client.post(
        "/login/verify",
        data={"code": pyotp.TOTP(ids["secret"]).now(), **form_csrf(client, "/login/verify")},
    )
    assert r.status_code == 302
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}

    dashboard = client.get("/dashboard").text
    # The 10-day-overdue entry is in the alert strip; the paused bill is not.
    assert "1 overdue bill" in dashboard and "Old gym" not in dashboard

    for url in (
        "/dashboard",
        "/bills",
        "/insights",
        f"/buckets/{ids['trip']}",
        "/transactions/search",
    ):
        assert client.get(url).status_code == 200, url
    assert "Cosmote" in client.get("/bills").text

    r = client.post(f"/bills/{ids['bill']}/occurrences/{ids['due']}/pay", headers=headers)
    assert r.status_code == 302
    with Session() as db:
        row = db.execute(
            text(
                "SELECT o.status, t.recurring_bill_id FROM bill_occurrences o "
                "JOIN transactions t ON t.id = o.transaction_id WHERE o.id = :i"
            ),
            {"i": ids["due"]},
        ).one()
        assert tuple(row) == ("paid", ids["bill"])
        backfilled = db.execute(
            text("SELECT recurring_bill_id FROM transactions WHERE id = :i"), {"i": ids["txn"]}
        ).scalar()
        assert backfilled == ids["bill"]


def test_new_api_reads_the_upgraded_data(upgraded):
    client, Session, ids = upgraded
    r = client.post("/api/v1/auth/login", json={"username": "giorgos", "password": PASSWORD})
    pending = r.json()["pending_token"]
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": pending, "code": pyotp.TOTP(ids["secret"]).now()},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    month = client.get("/api/v1/plan/month", headers=headers)
    assert month.status_code == 200, month.text
    assert month.json()["income"]["so_far"] == 1500.0
    buckets = {b["name"]: b["kind"] for b in client.get("/api/v1/buckets", headers=headers).json()}
    assert buckets == {"Daily": "monthly", "Trip": "event"}
    items = client.get("/api/v1/recurring", headers=headers).json()
    # Paused items stay listed in management lists (Ruling 6).
    assert {i["name"] for i in items} == {"Cosmote", "Gym", "Old gym"}
    assert {(i["direction"], i["rule_kind"]) for i in items} == {("out", "monthly_interval")}

    today = local_today()
    r = client.get(
        "/api/v1/recurring/entries",
        headers=headers,
        params={"from": (today - timedelta(days=75)).isoformat(), "to": today.isoformat()},
    )
    assert r.status_code == 200, r.text
    entries = {e["id"]: e for e in r.json()}
    assert ids["paused_due"] not in entries  # paused: hidden
    assert entries[ids["due"]]["status"] == "expected" and entries[ids["due"]]["overdue"]
    assert entries[ids["paid"]]["status"] == "done"
    assert entries[ids["skipped"]]["status"] == "skipped"
    gym = entries[ids["gym_paid"]]
    assert (gym["status"], gym["transaction_id"], gym["bucket_id"]) == ("done", None, None)


def test_the_claim_only_payment_is_a_fixed_cost_paid(upgraded):
    from app.services.planning import month_picture

    _, Session, ids = upgraded
    when = local_today() - timedelta(days=40)
    with Session() as db:
        pic = month_picture(db, ids["hh"], when.year, when.month)
    # Gym (25, claim-only, no bucket) counts as Fixed paid; Cosmote has a bucket.
    assert pic["fixed"]["so_far"] == 25


def test_periods_are_backfilled_and_top_up_adds_nothing_to_them(upgraded):
    from app.scheduler import _top_up_entries

    _, Session, ids = upgraded
    with Session() as db:
        rows = db.execute(text("SELECT bill_id, due_date, period FROM bill_occurrences")).all()
        assert rows and all(
            period == f"{_as_date(due).year:04d}-{_as_date(due).month:02d}"
            for _, due, period in rows
        )
        before = Counter((bill_id, period) for bill_id, _, period in rows)

        created = _top_up_entries(db, local_today())
        db.commit()
        after = db.execute(text("SELECT bill_id, period FROM bill_occurrences")).all()
    counts = Counter(map(tuple, after))
    # Every period the old app had already generated keeps exactly the rows it had.
    assert all(counts[pair] == n for pair, n in before.items())
    # It did run: the bucket-less bill had no future entries and gets them now.
    assert created == len(after) - len(rows) and created > 0
    # The paused bill gets nothing.
    assert sum(1 for bill_id, _ in after if bill_id == ids["paused"]) == 1


def _as_date(value):
    from datetime import date

    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


# ---------------------------------------------------------------------------
# 2d M: recurring_bills.payment_method, backfilled from history
# ---------------------------------------------------------------------------

PLANNING_REVISION = "a7b8c9d0e1f2"
BILL_PM_REVISION = "b8c9d0e1f2a3"


def _paid_occurrence(conn, ids, bill_key, *, due, method, deleted=False):
    """A paid entry of ``bill_key`` with its expense. a7b8c9d0e1f2 links the two."""
    from datetime import datetime, time

    txn = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement, payment_method, deleted_at) VALUES (:i, :b, :h, 38.90, "
            "'EUR', 1, 'expense', :u, :d, false, false, :m, :x)"
        ),
        {
            "i": txn,
            "b": ids["daily"],
            "h": ids["hh"],
            "u": ids["user"],
            "d": due,
            "m": method,
            "x": datetime.combine(due, time()) if deleted else None,
        },
    )
    conn.execute(
        text(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status, transaction_id) "
            "VALUES (:i, :b, :d, 'paid', :t)"
        ),
        {"i": str(uuid.uuid4()), "b": ids[bill_key], "d": due, "t": txn},
    )


def _item(conn, ids, name, *, direction):
    """A recurring item written at a7b8c9d0e1f2 (direction exists from there on)."""
    item = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
            "frequency, interval_months, start_date, is_active, is_auto_pay, direction) "
            "VALUES (:i, :h, :b, :n, 100, 'EUR', 'monthly', 1, :s, true, false, :d)"
        ),
        {
            "i": item,
            "h": ids["hh"],
            "b": None if direction == "in" else ids["daily"],
            "n": name,
            "s": local_today() - timedelta(days=60),
            "d": direction,
        },
    )
    return item


def _linked(conn, ids, item, *, when, method, kind="expense", created_at=None):
    """A transaction linked to ``item`` the way the new app links it (recurring_bill_id)."""
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement, payment_method, recurring_bill_id, created_at) "
            "VALUES (:i, :b, :h, 100, 'EUR', 1, :k, :u, :d, false, false, :m, :r, :c)"
        ),
        {
            "i": str(uuid.uuid4()),
            "b": None if kind == "income" else ids["daily"],
            "h": ids["hh"],
            "k": kind,
            "u": ids["user"],
            "d": when,
            "m": method,
            "r": item,
            "c": created_at,
        },
    )


def _methods(db_url) -> dict:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            return dict(conn.execute(text("SELECT id, payment_method FROM recurring_bills")).all())
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [PROD_REVISION, PRE_PHASE1_REVISION])
def test_bill_payment_method_is_backfilled_from_history(tmp_path, revision):
    from datetime import datetime

    from sqlalchemy import inspect

    db_url = _db_url(tmp_path, "pm.db")
    assert _alembic(["upgrade", revision], db_url).returncode == 0
    today = local_today()
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
        # Cosmote: card 40 days ago (seeded), transfer 25 days ago, and a newer
        # cash payment that was deleted. The latest *active* one is the transfer.
        _paid_occurrence(conn, ids, "bill", due=today - timedelta(days=25), method="transfer")
        _paid_occurrence(
            conn, ids, "bill", due=today - timedelta(days=5), method="cash", deleted=True
        )
    engine.dispose()
    up = _alembic(["upgrade", PLANNING_REVISION], db_url)
    assert up.returncode == 0, up.stderr

    engine = create_engine(db_url)
    with engine.begin() as conn:
        # Income items exist from a7b8c9d0e1f2 on. One received "by card" by mistake
        # still becomes transfer: receive_occurrence always recorded transfer.
        ids["salary"] = _item(conn, ids, "Salary", direction="in")
        _linked(
            conn, ids, ids["salary"], when=today - timedelta(days=3), method="card", kind="income"
        )
        # Two payments on one day: the one with a created_at is the newer (rows
        # without one predate the column), whichever way the dialect sorts NULLs.
        ids["rent"] = _item(conn, ids, "Rent", direction="out")
        same_day = today - timedelta(days=2)
        _linked(conn, ids, ids["rent"], when=same_day, method="other")
        _linked(
            conn,
            ids,
            ids["rent"],
            when=same_day,
            method="apple_pay",
            created_at=datetime(2026, 1, 1, 9, 0),  # noqa: DTZ001
        )
    engine.dispose()

    up = _alembic(["upgrade", BILL_PM_REVISION], db_url)
    assert up.returncode == 0, up.stderr
    expected = {
        ids["bill"]: "transfer",  # latest active linked payment
        ids["gym"]: "card",  # claim-only: no linked transaction
        ids["paused"]: "card",  # nothing paid
        ids["salary"]: "transfer",  # in items
        ids["rent"]: "apple_pay",  # created_at breaks the same-day tie
    }
    assert _methods(db_url) == expected

    # Round trip: down drops the column, up recomputes the same values.
    down = _alembic(["downgrade", PLANNING_REVISION], db_url)
    assert down.returncode == 0, down.stderr
    engine = create_engine(db_url)
    assert "payment_method" not in {
        c["name"] for c in inspect(engine).get_columns("recurring_bills")
    }
    engine.dispose()
    up = _alembic(["upgrade", BILL_PM_REVISION], db_url)
    assert up.returncode == 0, up.stderr
    assert _methods(db_url) == expected


def test_pantry_works_on_the_upgraded_data(upgraded):
    """Pantry (e1f2a3b4c5d6) on a production-shaped upgrade: shopping_lines
    exists, and a stock item from before the upgrade can be ticked and
    added to the pantry through the new API."""
    from sqlalchemy import inspect

    client, Session, ids = upgraded
    with Session() as db:
        assert "shopping_lines" in inspect(db.get_bind()).get_table_names()
        product, item = str(uuid.uuid4()), str(uuid.uuid4())
        db.execute(
            text("INSERT INTO products (id, household_id, name) VALUES (:i, :h, 'Milk')"),
            {"i": product, "h": ids["hh"]},
        )
        db.execute(
            text(
                "INSERT INTO stock_items (id, household_id, product_id, quantity, min_quantity, "
                "track_price) VALUES (:i, :h, :p, 0, 1, true)"
            ),
            {"i": item, "h": ids["hh"], "p": product},
        )
        db.commit()

    r = client.post("/api/v1/auth/login", json={"username": "giorgos", "password": PASSWORD})
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(ids["secret"]).now()},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/stock/summary", headers=headers).json() == {
        "low_count": 1,
        "ticked_count": 0,
    }
    r = client.post("/api/v1/stock/shopping/ticks", json={"stock_item_id": item}, headers=headers)
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == [{"stock_item_id": item, "name": "Milk", "before": 0, "after": 2}]

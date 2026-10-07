"""Production-shaped upgrade (spec §7): the schema production runs (commit
8b01313, alembic head f0a1b2c3d4e5; or e9f0a1b2c3d4 for a database restored
from a pre-Phase-1 backup) with real-looking data, upgraded to head,
then the old app used as a person would: TOTP login, dashboard, bills (pay
one), insights, a trip bucket, search; and the new API on the same data.

The data has what a real database has: a bucketed bill with a paid, an
overdue, a skipped and a year of old-app-generated future entries; a
bucket-less bill the old app paid claim-only; and a paused bill."""

import uuid
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
        before = {(bill_id, period) for bill_id, _, period in rows}
        assert len(before) == len(rows)  # one entry per bill and month

        created = _top_up_entries(db, local_today())
        db.commit()
        after = db.execute(text("SELECT bill_id, period FROM bill_occurrences")).all()
    counts: dict = {}
    for pair in map(tuple, after):
        counts[pair] = counts.get(pair, 0) + 1
    # Every period the old app had already generated still has exactly its one row.
    assert all(counts[pair] == 1 for pair in before)
    # It did run: the bucket-less bill had no future entries and gets them now.
    assert created == len(after) - len(rows) and created > 0
    # The paused bill gets nothing.
    assert sum(1 for bill_id, _ in after if bill_id == ids["paused"]) == 1


def _as_date(value):
    from datetime import date

    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])

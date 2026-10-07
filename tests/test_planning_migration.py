"""The planning migration (spec §6.1): additive, backfilled, reversible."""

import importlib.util
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.test_migrations import ROOT, _alembic, _db_url

MIGRATION = ROOT / "alembic" / "versions" / "a7b8c9d0e1f2_planning_recurring_items.py"


def _previous_revision() -> str:
    spec = importlib.util.spec_from_file_location("planning_mig", MIGRATION)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig.down_revision


def _seed(conn) -> dict:
    ids = {
        k: str(uuid.uuid4())
        for k in (
            "hh",
            "user",
            "trip",
            "daily",
            "savings",
            "custom",
            "bill",
            "paid",
            "open",
            "txn",
            "loose",
        )
    }
    conn.execute(
        text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
        {"i": ids["hh"]},
    )
    conn.execute(
        text(
            "INSERT INTO users (id, username, display_name, password_hash, session_version, "
            "totp_enabled, email_verified) VALUES (:i, 'u', 'U', 'x', 0, false, false)"
        ),
        {"i": ids["user"]},
    )
    for key, kind in (
        ("trip", "trip"),
        ("daily", "day2day"),
        ("savings", "savings"),
        ("custom", "custom"),
    ):
        conn.execute(
            text(
                "INSERT INTO buckets (id, household_id, name, type, status, show_income, "
                "enable_settlement) VALUES (:b, :h, :n, :t, 'active', true, false)"
            ),
            {"b": ids[key], "h": ids["hh"], "n": key, "t": kind},
        )
    conn.execute(
        text(
            "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
            "frequency, interval_months, start_date, is_active, is_auto_pay) "
            "VALUES (:i, :h, :b, 'Cosmote', 38.90, 'EUR', 'monthly', 1, '2026-01-05', true, false)"
        ),
        {"i": ids["bill"], "h": ids["hh"], "b": ids["daily"]},
    )
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement) VALUES (:i, :b, :h, 38.90, 'EUR', 1, 'expense', :u, "
            "'2026-02-05', false, false)"
        ),
        {"i": ids["txn"], "b": ids["daily"], "h": ids["hh"], "u": ids["user"]},
    )
    # An ordinary expense that pays no bill: it must stay unlinked.
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement) VALUES (:i, :b, :h, 5, 'EUR', 1, 'expense', :u, "
            "'2026-02-06', false, false)"
        ),
        {"i": ids["loose"], "b": ids["daily"], "h": ids["hh"], "u": ids["user"]},
    )
    conn.execute(
        text(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status, transaction_id) "
            "VALUES (:i, :b, '2026-02-05', 'paid', :t)"
        ),
        {"i": ids["paid"], "b": ids["bill"], "t": ids["txn"]},
    )
    conn.execute(
        text(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status) "
            "VALUES (:i, :b, '2026-03-05', 'unpaid')"
        ),
        {"i": ids["open"], "b": ids["bill"]},
    )
    return ids


def test_upgrade_backfills_and_keeps_every_row(tmp_path):
    db_url = _db_url(tmp_path, "planning.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr

    with engine.connect() as conn:
        bill = conn.execute(
            text("SELECT direction, rule_kind, rule_adjust, interval_months FROM recurring_bills")
        ).one()
        assert tuple(bill) == ("out", "monthly_interval", "none", 1)
        kinds = dict(conn.execute(text("SELECT name, kind FROM buckets")).all())
        assert kinds == {
            "trip": "event",
            "daily": "monthly",
            "savings": "monthly",
            "custom": "monthly",
        }
        assert (
            conn.execute(
                text("SELECT recurring_bill_id FROM transactions WHERE id = :i"),
                {"i": ids["loose"]},
            ).scalar()
            is None
        )
        linked = conn.execute(
            text("SELECT recurring_bill_id FROM transactions WHERE id = :i"), {"i": ids["txn"]}
        ).scalar()
        assert linked == ids["bill"]
        assert conn.execute(text("SELECT COUNT(*) FROM bill_occurrences")).scalar() == 2
        periods = dict(conn.execute(text("SELECT id, period FROM bill_occurrences")).all())
        assert periods == {ids["paid"]: "2026-02", ids["open"]: "2026-03"}
        assert conn.execute(text("SELECT COUNT(*) FROM match_suggestions")).scalar() == 0
    engine.dispose()


def test_old_app_inserts_without_the_new_columns_still_work(tmp_path):
    db_url = _db_url(tmp_path, "oldapp.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO buckets (id, household_id, name, type, status, show_income, "
                "enable_settlement) VALUES (:b, :h, 'new', 'trip', 'active', true, false)"
            ),
            {"b": "b-new", "h": ids["hh"]},
        )
        conn.execute(
            text(
                "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, "
                "currency, frequency, interval_months, start_date, is_active, is_auto_pay) "
                "VALUES ('r-new', :h, :b, 'Rent', 500, 'EUR', 'monthly', 1, '2026-01-01', "
                "true, false)"
            ),
            {"h": ids["hh"], "b": ids["daily"]},
        )
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT kind FROM buckets WHERE id = 'b-new'")).scalar() == "monthly"
        )
        row = conn.execute(
            text("SELECT direction, rule_kind, rule_adjust FROM recurring_bills WHERE id = 'r-new'")
        ).one()
        assert tuple(row) == ("out", "monthly_interval", "none")
    engine.dispose()


def test_check_allows_a_fixed_cost_but_not_a_bare_expense(tmp_path):
    db_url = _db_url(tmp_path, "check.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
    assert _alembic(["upgrade", "head"], db_url).returncode == 0

    insert = text(
        "INSERT INTO transactions (id, household_id, amount, currency, exchange_rate, type, "
        "transaction_date, exclude_from_forecast, exclude_from_settlement, recurring_bill_id) "
        "VALUES (:i, :h, 10, 'EUR', 1, 'expense', '2026-03-05', false, false, :r)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"i": str(uuid.uuid4()), "h": ids["hh"], "r": ids["bill"]})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"i": str(uuid.uuid4()), "h": ids["hh"], "r": None})
    engine.dispose()


def test_downgrade_refuses_while_a_fixed_cost_exists_then_round_trips(tmp_path):
    db_url = _db_url(tmp_path, "down.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    fixed_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (id, household_id, amount, currency, exchange_rate, "
                "type, transaction_date, exclude_from_forecast, exclude_from_settlement, "
                "recurring_bill_id) VALUES (:i, :h, 10, 'EUR', 1, 'expense', '2026-03-05', "
                "false, false, :r)"
            ),
            {"i": fixed_id, "h": ids["hh"], "r": ids["bill"]},
        )

    down = _alembic(["downgrade", _previous_revision()], db_url)
    assert down.returncode != 0 and "Fixed-cost" in down.stderr

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET bucket_id = :b WHERE id = :i"),
            {"b": ids["daily"], "i": fixed_id},
        )
    down = _alembic(["downgrade", _previous_revision()], db_url)
    assert down.returncode == 0, down.stderr
    insp = inspect(engine)
    assert "match_suggestions" not in insp.get_table_names()
    assert "recurring_bill_id" not in {c["name"] for c in insp.get_columns("transactions")}
    assert "kind" not in {c["name"] for c in insp.get_columns("buckets")}
    assert "period" not in {c["name"] for c in insp.get_columns("bill_occurrences")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM transactions")).scalar() == 3

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    engine.dispose()


@pytest.mark.parametrize(
    "update",
    [
        "UPDATE recurring_bills SET direction = 'in'",
        "UPDATE recurring_bills SET rule_kind = 'monthly_day', rule_day = 5",
    ],
)
def test_downgrade_refuses_while_a_new_style_item_exists(tmp_path, update):
    db_url = _db_url(tmp_path, "downitem.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        _seed(conn)
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    with engine.begin() as conn:
        conn.execute(text(update))
    down = _alembic(["downgrade", _previous_revision()], db_url)
    assert down.returncode != 0 and "recurring item" in down.stderr
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE recurring_bills SET direction = 'out', rule_kind = 'monthly_interval'")
        )
    assert _alembic(["downgrade", _previous_revision()], db_url).returncode == 0
    engine.dispose()

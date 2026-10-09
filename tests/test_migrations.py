"""
Migration safety.

`entrypoint.sh` runs `alembic upgrade head` on every deploy against the live
database, so these guard the two things that matter: the chain applies cleanly
from scratch, and it ends up matching the ORM models.
"""

import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parent.parent


def _db_url(tmp_path, name):
    """A fresh database for one migration test: TEST_DATABASE_URL or SQLite."""
    from tests.conftest import TEST_DATABASE_URL, reset_pg_schema

    if TEST_DATABASE_URL:
        reset_pg_schema(TEST_DATABASE_URL)
        return TEST_DATABASE_URL
    return f"sqlite:///{tmp_path / name}"


def _alembic(args, db_url):
    import os

    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "APP_SECRET_KEY": "test-secret-key-at-least-32-chars-long!!",
        "DEBUG": "true",
        "PYTHONPATH": str(ROOT),
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_migrations_apply_from_scratch(tmp_path):
    db_url = _db_url(tmp_path, "mig.db")
    result = _alembic(["upgrade", "head"], db_url)
    assert result.returncode == 0, result.stderr

    tables = set(inspect(create_engine(db_url)).get_table_names())
    expected = {
        "users",
        "households",
        "household_members",
        "invitations",
        "categories",
        "buckets",
        "transactions",
        "transaction_splits",
        "recurring_bills",
        "bill_occurrences",
        "recurring_bill_splits",
        "notifications",
        "push_subscriptions",
        "refresh_tokens",
    }
    assert expected <= tables, f"missing: {expected - tables}"


def test_single_head(tmp_path):
    """Multiple heads make `upgrade head` ambiguous and break deploys."""
    result = _alembic(["heads"], _db_url(tmp_path, "h.db"))
    assert result.returncode == 0, result.stderr
    heads = [ln for ln in result.stdout.splitlines() if ln.strip() and "(head)" in ln]
    assert len(heads) == 1, f"expected one head, got:\n{result.stdout}"


def test_schema_matches_models(tmp_path):
    """Every ORM column must exist in the migrated schema.

    Catches the case where a model gains a field but nobody wrote a migration —
    which works locally (DEBUG runs create_all) and then 500s in production.
    """
    db_url = _db_url(tmp_path, "cmp.db")
    assert _alembic(["upgrade", "head"], db_url).returncode == 0

    import app.models  # noqa: F401
    from app.core.database import Base

    insp = inspect(create_engine(db_url))
    problems = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in insp.get_table_names():
            problems.append(f"table {table_name} missing from migrations")
            continue
        migrated = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name not in migrated:
                problems.append(f"{table_name}.{col.name} missing from migrations")
    assert not problems, "\n".join(problems)


def test_dedupe_migration_preserves_existing_notifications(tmp_path):
    """The new unique constraint must not drop or collide with existing rows."""
    import uuid

    from sqlalchemy import text

    db_url = _db_url(tmp_path, "data.db")
    # Migrate to just before the dedupe change.
    assert _alembic(["upgrade", "8c4f34f54a84"], db_url).returncode == 0

    engine = create_engine(db_url)
    hh_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
            {"i": hh_id},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, password_hash, session_version, totp_enabled, email_verified) "
                "VALUES (:i, 'u', 'U', 'x', 0, false, false)"
            ),
            {"i": user_id},
        )
        for n in range(4):
            conn.execute(
                text(
                    "INSERT INTO notifications (id, household_id, user_id, type, title, is_read) "
                    "VALUES (:i, :h, :u, 'general', :t, false)"
                ),
                {"i": str(uuid.uuid4()), "h": hh_id, "u": user_id, "t": f"note {n}"},
            )

    assert _alembic(["upgrade", "head"], db_url).returncode == 0

    with engine.connect() as conn:
        # All rows survived, all with a NULL dedupe_key — and multiple NULLs
        # coexisting proves the unique constraint does not affect ad-hoc rows.
        assert conn.execute(text("SELECT COUNT(*) FROM notifications")).scalar() == 4
        nulls = conn.execute(
            text("SELECT COUNT(*) FROM notifications WHERE dedupe_key IS NULL")
        ).scalar()
        assert nulls == 4


def test_downgrade_then_upgrade_round_trips(tmp_path):
    db_url = _db_url(tmp_path, "rt.db")
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    down = _alembic(["downgrade", "8c4f34f54a84"], db_url)
    assert down.returncode == 0, down.stderr
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr


def test_notification_enum_members_are_all_migrated():
    """Every NotificationType member must exist in the PostgreSQL enum.

    notifications.type is a native ENUM on PostgreSQL, so adding a member to
    the Python enum without an ALTER TYPE makes inserts fail at runtime with
    "invalid input value for enum notificationtype". SQLite renders the column
    as VARCHAR, so no amount of normal testing catches it — this reads the
    migrations instead.
    """
    import re

    from app.models import NotificationType

    migrations = "\n".join(p.read_text() for p in (ROOT / "alembic" / "versions").glob("*.py"))

    # Values in the original CREATE TYPE, plus any added later via ALTER TYPE.
    created = set()
    idx = migrations.find("CREATE TYPE notificationtype AS ENUM")
    if idx != -1:
        # The statement is built from concatenated Python string literals, so
        # scan the following window rather than matching a single-line pattern.
        window = migrations[idx : idx + 400]
        window = window[: window.find(";")] if ";" in window else window
        created |= set(re.findall(r"['\"]([a-z_]+)['\"]", window))
    created |= set(
        re.findall(
            r"ALTER TYPE notificationtype ADD VALUE (?:IF NOT EXISTS )?['\"]([a-z_]+)['\"]",
            migrations,
        )
    )
    # The migration may build the list from a Python tuple.
    for block in re.findall(r"NEW_VALUES\s*=\s*\(([^)]*)\)", migrations):
        created |= set(re.findall(r"['\"]([a-z_]+)['\"]", block))

    missing = {t.value for t in NotificationType} - created
    assert not missing, (
        f"NotificationType member(s) {sorted(missing)} have no ALTER TYPE migration; "
        f"inserting them will fail on PostgreSQL"
    )


def test_security_hardening_migration_preserves_data(tmp_path):
    """Phase 1 columns are additive: existing rows survive with safe defaults."""
    import uuid

    from sqlalchemy import text

    db_url = _db_url(tmp_path, "sec.db")
    assert _alembic(["upgrade", "b3c4d5e6f7a8"], db_url).returncode == 0

    engine = create_engine(db_url)
    hh_id, user_id, tx_id, bucket_id = (str(uuid.uuid4()) for _ in range(4))
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
            {"i": hh_id},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, display_name, password_hash, session_version, "
                "totp_enabled, totp_secret, email_verified) "
                "VALUES (:i, 'u', 'U', 'x', 0, true, 'PLAINSECRET', false)"
            ),
            {"i": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO buckets (id, household_id, name, type, status, show_income, enable_settlement) "
                "VALUES (:b, :h, 'B', 'custom', 'active', true, false)"
            ),
            {"b": bucket_id, "h": hh_id},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, exchange_rate, "
                "type, paid_by, transaction_date, exclude_from_forecast, exclude_from_settlement) "
                "VALUES (:i, :b, :h, 12.5, 'EUR', 1, 'expense', :u, '2026-01-01', false, false)"
            ),
            {"i": tx_id, "b": bucket_id, "h": hh_id, "u": user_id},
        )

    def check():
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT totp_secret, failed_logins, locked_until, last_totp_step "
                    "FROM users WHERE id = :i"
                ),
                {"i": user_id},
            ).one()
            assert tuple(row) == ("PLAINSECRET", 0, None, None)
            assert (
                conn.execute(
                    text("SELECT deleted_at FROM transactions WHERE id = :i"), {"i": tx_id}
                ).scalar()
                is None
            )
            assert (
                conn.execute(
                    text("SELECT archived_at FROM households WHERE id = :i"), {"i": hh_id}
                ).scalar()
                is None
            )

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    check()

    down = _alembic(["downgrade", "b3c4d5e6f7a8"], db_url)
    assert down.returncode == 0, down.stderr
    with engine.connect() as conn:
        assert conn.execute(text("SELECT totp_secret FROM users")).scalar() == "PLAINSECRET"
        assert conn.execute(text("SELECT COUNT(*) FROM transactions")).scalar() == 1

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    check()


def test_stock_migration_tables_and_barcode_uniqueness(tmp_path):
    """Phase 6: stock/price tables exist; barcode is unique per household only
    when set (many products may have no barcode)."""
    import uuid

    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    db_url = _db_url(tmp_path, "stock.db")
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr

    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert {"products", "stock_items", "stock_movements", "price_snapshots"} <= tables

    hh1, hh2 = str(uuid.uuid4()), str(uuid.uuid4())

    def add_product(conn, hh, barcode):
        conn.execute(
            text(
                "INSERT INTO products (id, household_id, name, barcode) VALUES (:i, :h, 'Milk', :b)"
            ),
            {"i": str(uuid.uuid4()), "h": hh, "b": barcode},
        )

    with engine.begin() as conn:
        for hh in (hh1, hh2):
            conn.execute(
                text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
                {"i": hh},
            )
        add_product(conn, hh1, None)
        add_product(conn, hh1, None)  # NULL barcodes never collide
        add_product(conn, hh1, "5201054017906")
        add_product(conn, hh2, "5201054017906")  # other household: fine
    with pytest.raises(IntegrityError), engine.begin() as conn:
        add_product(conn, hh1, "5201054017906")
    engine.dispose()

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "stock_mig", ROOT / "alembic" / "versions" / "a5b6c7d8e9f0_stock_and_prices.py"
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    down = _alembic(["downgrade", mig.down_revision], db_url)
    assert down.returncode == 0, down.stderr
    tables = set(inspect(create_engine(db_url)).get_table_names())
    assert not {"products", "stock_items", "stock_movements", "price_snapshots"} & tables
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr


def test_notification_mutes_migration_chain_and_round_trip(tmp_path):
    """2d §7.6: d0e1f2a3b4c5 follows 2c's c9d0e1f2a3b4 and round-trips."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mutes_mig", ROOT / "alembic" / "versions" / "d0e1f2a3b4c5_notification_mutes.py"
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert (mig.revision, mig.down_revision) == ("d0e1f2a3b4c5", "c9d0e1f2a3b4")

    db_url = _db_url(tmp_path, "mutes.db")
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    cols = {c["name"] for c in inspect(create_engine(db_url)).get_columns("notification_mutes")}
    assert cols == {"user_id", "household_id", "type"}
    down = _alembic(["downgrade", "c9d0e1f2a3b4"], db_url)
    assert down.returncode == 0, down.stderr
    assert "notification_mutes" not in inspect(create_engine(db_url)).get_table_names()
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr


def test_shopping_lines_migration_round_trip_and_active_tick_index(tmp_path):
    """Pantry §3.1: e1f2a3b4c5d6 follows d0e1f2a3b4c5, adds shopping_lines and
    round-trips; the partial unique index allows one active tick per item,
    any number of cleared ones, and never constrains one-off lines."""
    import importlib.util
    import uuid

    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    spec = importlib.util.spec_from_file_location(
        "shopping_mig", ROOT / "alembic" / "versions" / "e1f2a3b4c5d6_shopping_lines.py"
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert (mig.revision, mig.down_revision) == ("e1f2a3b4c5d6", "d0e1f2a3b4c5")

    db_url = _db_url(tmp_path, "shopping.db")
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    engine = create_engine(db_url)
    cols = {c["name"] for c in inspect(engine).get_columns("shopping_lines")}
    assert cols == {
        "id",
        "household_id",
        "stock_item_id",
        "name",
        "quantity",
        "checked_at",
        "created_by",
        "created_at",
        "cleared_at",
    }

    hh, product, item = (str(uuid.uuid4()) for _ in range(3))

    def add_line(conn, stock_item_id, cleared=None, name=None):
        conn.execute(
            text(
                "INSERT INTO shopping_lines "
                "(id, household_id, stock_item_id, name, cleared_at, created_at) "
                "VALUES (:i, :h, :s, :n, :c, '2026-10-01 09:00:00')"
            ),
            {"i": str(uuid.uuid4()), "h": hh, "s": stock_item_id, "n": name, "c": cleared},
        )

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
            {"i": hh},
        )
        conn.execute(
            text("INSERT INTO products (id, household_id, name) VALUES (:i, :h, 'Milk')"),
            {"i": product, "h": hh},
        )
        conn.execute(
            text(
                "INSERT INTO stock_items (id, household_id, product_id, quantity, min_quantity, "
                "track_price) VALUES (:i, :h, :p, 0, 1, true)"
            ),
            {"i": item, "h": hh, "p": product},
        )
        add_line(conn, item)  # the active tick
        add_line(conn, item, cleared="2026-10-01 10:00:00")  # cleared ticks never collide
        add_line(conn, item, cleared="2026-10-02 10:00:00")
        add_line(conn, None, name="Foil")  # one-off lines are not ticks
        add_line(conn, None, name="Foil")
    with pytest.raises(IntegrityError), engine.begin() as conn:
        add_line(conn, item)  # a second active tick
    engine.dispose()

    down = _alembic(["downgrade", "d0e1f2a3b4c5"], db_url)
    assert down.returncode == 0, down.stderr
    assert "shopping_lines" not in inspect(create_engine(db_url)).get_table_names()
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr


def test_stock_movements_client_id_migration_round_trip(tmp_path):
    """Pantry §4.8: e1f2a3b4c5d6 also adds stock_movements.client_id (the
    stepper's dedupe key), indexed, and drops it on downgrade."""
    db_url = _db_url(tmp_path, "client_id.db")
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    insp = inspect(create_engine(db_url))
    assert "client_id" in {c["name"] for c in insp.get_columns("stock_movements")}
    assert "ix_stock_movements_client_id" in {
        i["name"] for i in insp.get_indexes("stock_movements")
    }

    down = _alembic(["downgrade", "d0e1f2a3b4c5"], db_url)
    assert down.returncode == 0, down.stderr
    insp = inspect(create_engine(db_url))
    assert "client_id" not in {c["name"] for c in insp.get_columns("stock_movements")}
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr


def test_polish_migration_round_trip(tmp_path):
    """Polish M1: f2a3b4c5d6e7 follows b0c1d2e3f4a5 and is additive: an index
    on shopping_lines.stock_item_id, cash_movements.client_id (indexed with
    the household, not unique), and price_snapshots.source defaulting to
    'posokanei' for existing rows. The
    downgrade drops them all and leaves main's ingest_attempts alone."""
    import importlib.util
    import uuid

    from sqlalchemy import text

    spec = importlib.util.spec_from_file_location(
        "polish_mig", ROOT / "alembic" / "versions" / "f2a3b4c5d6e7_polish_round.py"
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert (mig.revision, mig.down_revision) == ("f2a3b4c5d6e7", "b0c1d2e3f4a5")

    db_url = _db_url(tmp_path, "polish.db")
    up = _alembic(["upgrade", "b0c1d2e3f4a5"], db_url)
    assert up.returncode == 0, up.stderr
    hh, product = str(uuid.uuid4()), str(uuid.uuid4())
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
            {"i": hh},
        )
        conn.execute(
            text("INSERT INTO products (id, household_id, name) VALUES (:i, :h, 'Milk')"),
            {"i": product, "h": hh},
        )
        conn.execute(
            text(
                "INSERT INTO price_snapshots (id, product_id, retailer, price, is_discount, "
                "snapshot_date) VALUES (:i, :p, 'ab', 1.59, false, '2026-10-01')"
            ),
            {"i": str(uuid.uuid4()), "p": product},
        )
    engine.dispose()

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    engine = create_engine(db_url)
    insp = inspect(engine)
    col = next(c for c in insp.get_columns("ingest_attempts") if c["name"] == "summary_version")
    assert col["nullable"] and col["default"] is None
    tcol = next(c for c in insp.get_columns("transactions") if c["name"] == "ingest_token_id")
    assert tcol["nullable"]
    fk = next(
        f
        for f in insp.get_foreign_keys("transactions")
        if f["constrained_columns"] == ["ingest_token_id"]
    )
    assert (
        fk["referred_table"] == "personal_api_tokens"
        and fk["options"].get("ondelete") == "SET NULL"
    )
    assert "client_id" in {c["name"] for c in insp.get_columns("cash_movements")}
    idx = {i["name"]: i for i in insp.get_indexes("cash_movements")}
    assert idx["ix_cash_movements_hh_client_id"]["column_names"] == ["household_id", "client_id"]
    assert not idx["ix_cash_movements_hh_client_id"]["unique"]
    assert "ix_shopping_lines_stock_item_id" in {
        i["name"] for i in insp.get_indexes("shopping_lines")
    }
    with engine.begin() as conn:
        assert conn.execute(text("SELECT source FROM price_snapshots")).scalar() == "posokanei"
        conn.execute(
            text(
                "INSERT INTO price_snapshots (id, product_id, retailer, price, is_discount, "
                "snapshot_date) VALUES (:i, :p, 'lidl', 1.29, false, '2026-10-02')"
            ),
            {"i": str(uuid.uuid4()), "p": product},
        )
        sources = conn.execute(text("SELECT source FROM price_snapshots")).scalars().all()
        assert sources == ["posokanei", "posokanei"]
    engine.dispose()

    down = _alembic(["downgrade", "b0c1d2e3f4a5"], db_url)
    assert down.returncode == 0, down.stderr
    insp = inspect(create_engine(db_url))
    assert "client_id" not in {c["name"] for c in insp.get_columns("cash_movements")}
    assert "source" not in {c["name"] for c in insp.get_columns("price_snapshots")}
    assert "ingest_attempts" in insp.get_table_names()
    assert "summary_version" not in {c["name"] for c in insp.get_columns("ingest_attempts")}
    assert "ingest_token_id" not in {c["name"] for c in insp.get_columns("transactions")}
    assert "ix_shopping_lines_stock_item_id" not in {
        i["name"] for i in insp.get_indexes("shopping_lines")
    }
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr

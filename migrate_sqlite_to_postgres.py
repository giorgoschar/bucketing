#!/usr/bin/env python3
"""
One-time migration: copy all data from a local SQLite expenses.db to a
PostgreSQL database.

Usage:
    python migrate_sqlite_to_postgres.py \
        --source sqlite:///./expenses.db \
        --target postgresql://expenses_user:password@host:5432/expenses

The target database must already exist and have all tables created
(run `alembic upgrade head` against it first).

Tables are migrated in FK-safe order. Existing rows in the target are
skipped (INSERT OR IGNORE semantics via on_conflict_do_nothing).
"""
import argparse
import sys

from sqlalchemy import create_engine, inspect, text, Boolean
# ---------------------------------------------------------------------------
# FK-safe insertion order (parents before children)
# ---------------------------------------------------------------------------
TABLE_ORDER = [
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
]


def migrate(source_url: str, target_url: str, dry_run: bool = False) -> None:
    print(f"Source : {source_url}")
    print(f"Target : {target_url}")
    if dry_run:
        print("DRY RUN — no data will be written.\n")

    src_engine = create_engine(source_url, connect_args={"check_same_thread": False} if "sqlite" in source_url else {})
    tgt_engine = create_engine(target_url)

        # Build a map of {table: {col_name}} for all boolean columns in the target
    tgt_inspector = inspect(tgt_engine)
    bool_cols: dict[str, set[str]] = {}
    for table in TABLE_ORDER:
        bool_cols[table] = {
            col["name"]
            for col in tgt_inspector.get_columns(table)
            if isinstance(col["type"], Boolean)
        }

    with src_engine.connect() as src_conn, tgt_engine.connect() as tgt_conn:
        for table in TABLE_ORDER:
            rows = src_conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
            if not rows:
                print(f"  {table}: empty, skipping")
                continue

            if dry_run:
                print(f"  {table}: would copy {len(rows)} row(s)")
                continue

            cols = list(rows[0].keys())
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(f":{c}" for c in cols)
            stmt = text(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'
                f" ON CONFLICT DO NOTHING"
            )

            table_bool_cols = bool_cols.get(table, set())

            inserted = 0
            with tgt_conn.begin():
                for row in rows:
                    data = dict(row)
                    # SQLite stores booleans as 0/1 — cast to Python bool for Postgres
                    for col in table_bool_cols:
                        if col in data and data[col] is not None:
                            data[col] = bool(data[col])
                    result = tgt_conn.execute(stmt, data)
                    inserted += result.rowcount

            print(f"  {table}: {inserted}/{len(rows)} row(s) inserted ({len(rows) - inserted} skipped as duplicates)")

    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate expenses data from SQLite to PostgreSQL")
    parser.add_argument("--source", required=True, help="SQLAlchemy URL of source SQLite DB")
    parser.add_argument("--target", required=True, help="SQLAlchemy URL of target PostgreSQL DB")
    parser.add_argument("--dry-run", action="store_true", help="Print row counts without writing anything")
    args = parser.parse_args()

    if "sqlite" not in args.source:
        print("ERROR: --source should be a sqlite:// URL", file=sys.stderr)
        sys.exit(1)
    if "postgresql" not in args.target and "postgres" not in args.target:
        print("ERROR: --target should be a postgresql:// URL", file=sys.stderr)
        sys.exit(1)

    migrate(args.source, args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

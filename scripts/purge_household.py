#!/usr/bin/env python
"""Manually hard-delete ONE archived household and everything in it.

This is the only code path that removes a household. It is never run
automatically: a household is archived (not deleted) when its last member
leaves, and stays that way until an admin decides to purge it.

Usage:
    python scripts/purge_household.py <household_id>                      # dry run (default)
    python scripts/purge_household.py <household_id> --dry-run            # same
    python scripts/purge_household.py <household_id> --yes-delete-<household_id>

Refuses households that are not archived. Back up the database first.
"""

import os
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_args(argv: list[str]) -> Namespace:
    """`execute` is true only with the exact flag --yes-delete-<household_id>."""
    ids = [a for a in argv if not a.startswith("--")]
    if len(ids) != 1:
        raise SystemExit(
            "usage: purge_household.py <household_id> [--dry-run | --yes-delete-<household_id>]"
        )
    household_id = ids[0]
    execute = f"--yes-delete-{household_id}" in argv and "--dry-run" not in argv
    return Namespace(household_id=household_id, execute=execute)


def _household_tables():
    from app.core.database import Base

    return [
        t for t in Base.metadata.sorted_tables if "household_id" in t.c and t.name != "households"
    ]


def purge(db, household_id: str, execute: bool, uploads_dir: str = "uploads") -> int:
    """Return 0 on success (or dry run), non-zero if refused."""
    from sqlalchemy import delete, func, select

    from app.models import Household, Transaction

    household = db.get(Household, household_id)
    if household is None:
        print(f"No household with id {household_id}.")
        return 2
    if household.archived_at is None:
        print(
            f"Refusing: household '{household.name}' is not archived. "
            "Only households archived by their last member leaving can be purged."
        )
        return 3

    print(f"Household '{household.name}' ({household_id}), archived {household.archived_at}.")
    print("Rows that would be deleted:")
    for table in _household_tables():
        count = db.execute(
            select(func.count()).select_from(table).where(table.c.household_id == household_id)
        ).scalar_one()
        if count:
            print(f"  {table.name}: {count}")
    receipts = [
        r
        for (r,) in db.query(Transaction.receipt_path).filter(
            Transaction.household_id == household_id, Transaction.receipt_path.isnot(None)
        )
    ]
    print(f"  receipt files: {len(receipts)}")
    print("  (plus dependent rows such as transaction splits, via ON DELETE CASCADE)")

    if not execute:
        print(f"\nDry run: nothing deleted. To delete, re-run with --yes-delete-{household_id}")
        return 0

    db.execute(delete(Household).where(Household.id == household_id))
    db.commit()
    for name in receipts:
        for sub in ("", ".trash"):
            path = os.path.join(uploads_dir, sub, os.path.basename(name))
            if os.path.isfile(path):
                os.remove(path)
    print("Deleted.")
    return 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return purge(db, args.household_id, args.execute)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

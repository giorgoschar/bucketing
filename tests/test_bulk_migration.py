"""Migration c9d0e1f2a3b4 (2c spec §5.5): three additive tables, a clean
round trip from b8c9d0e1f2a3, and the dismissal pair CHECK."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.models import DuplicateDismissal, Transaction, TransactionType
from tests.test_migrations import _alembic, _db_url

TABLES = {"bulk_batches", "bulk_batch_rows", "duplicate_dismissals"}


def _tables(db_url):
    eng = create_engine(db_url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_upgrade_creates_the_tables_and_round_trips(tmp_path):
    db_url = _db_url(tmp_path, "bulk.db")
    before = _alembic(["upgrade", "b8c9d0e1f2a3"], db_url)
    assert before.returncode == 0, before.stderr
    assert not TABLES & _tables(db_url)

    up = _alembic(["upgrade", "c9d0e1f2a3b4"], db_url)
    assert up.returncode == 0, up.stderr
    assert TABLES <= _tables(db_url)
    eng = create_engine(db_url)
    insp = inspect(eng)
    assert "ix_bulk_batches_household_created" in {
        i["name"] for i in insp.get_indexes("bulk_batches")
    }
    assert "ix_bulk_batch_rows_transaction_id" in {
        i["name"] for i in insp.get_indexes("bulk_batch_rows")
    }
    row_cols = {c["name"] for c in insp.get_columns("bulk_batch_rows")}
    for field in ("bucket_id", "category_id", "paid_by", "payer_mode", "payment_method"):
        assert {f"old_{field}", f"new_{field}"} <= row_cols
    # The old_/new_ values carry no FKs, so history survives deletions.
    assert {fk["referred_table"] for fk in insp.get_foreign_keys("bulk_batch_rows")} == {
        "bulk_batches",
        "transactions",
    }
    eng.dispose()

    down = _alembic(["downgrade", "b8c9d0e1f2a3"], db_url)
    assert down.returncode == 0, down.stderr
    assert not TABLES & _tables(db_url)
    again = _alembic(["upgrade", "head"], db_url)
    assert again.returncode == 0, again.stderr


def test_dismissal_pair_must_be_ordered(db, make_household):
    hh = make_household()
    a, b = (
        Transaction(
            household_id=hh.household_id,
            bucket_id=hh.bucket_id,
            amount=Decimal("5"),
            type=TransactionType.expense,
            transaction_date=date(2026, 10, 1),
        )
        for _ in range(2)
    )
    db.add_all([a, b])
    db.commit()  # the rollback below must not drop the two rows
    lo, hi = sorted([a.id, b.id])
    db.add(DuplicateDismissal(household_id=hh.household_id, first_id=hi, second_id=lo))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(DuplicateDismissal(household_id=hh.household_id, first_id=lo, second_id=hi))
    db.commit()
    db.add(DuplicateDismissal(household_id=hh.household_id, first_id=lo, second_id=hi))
    with pytest.raises(IntegrityError):
        db.commit()

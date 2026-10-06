"""cash stash: stash movements, takes from a stash, and take-and-spend links

Low-maintenance cash: each member has a private stash (cash at home) and a
wallet. Cash taken into the wallet counts as spent unless it is logged or
still there (see app.services.cash).

- cash_movements.kind VARCHAR(8) -> VARCHAR(16): the kinds are now
  'stash_in' | 'take' | 'put_back' | 'still_have' (plus the legacy 'out');
  plain strings validated by a Python enum (app.models.CashKind), like
  payment_method, so adding a kind never needs ALTER TYPE
- cash_movements.stash_owner_id VARCHAR NULL -> users.id (+ index): whose
  stash a 'take' came out of; NULL means the bank (an ATM)
- cash_movements.transaction_id VARCHAR NULL -> transactions.id ON DELETE SET
  NULL (+ index): the cash expense a 'take' was made for ("I took this from my
  stash"), so the pair nets out of the not-yet-logged cash

Existing rows: an 'in' (cash withdrawn into the wallet) becomes a 'take' from
the bank, a 'count' becomes 'still_have'; an 'out' stays as it is (legacy:
still counted, no longer offered).

Downgrade turns bank takes back into 'in' and refuses while any active
movement has no meaning before this revision (a stash movement, a take from a
stash, a still_have): the previous code subtracts every kind but 'in' from the
wallet and shows every movement to the whole household, so they would read as
cash spent and a private stash would become public. Delete them first (soft
deleted rows are ignored). Take-and-spend links are simply dropped: the 'in'
stays an ordinary withdrawal.

The downgrade only drops what exists, so a development database that ran an
earlier draft of this revision (Shared/Private pockets: cash_movements.pocket,
transactions.cash_pocket) can be downgraded with it and upgraded again.

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-10-05 14:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cash_movements") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=8),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("stash_owner_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("transaction_id", sa.String(), nullable=True))
        batch.create_foreign_key(
            "fk_cash_movements_stash_owner_id",
            "users",
            ["stash_owner_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_cash_movements_transaction_id",
            "transactions",
            ["transaction_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_cash_movements_stash_owner_id", "cash_movements", ["stash_owner_id"])
    op.create_index("ix_cash_movements_transaction_id", "cash_movements", ["transaction_id"])

    op.execute("UPDATE cash_movements SET kind = 'take' WHERE kind = 'in'")
    op.execute("UPDATE cash_movements SET kind = 'still_have' WHERE kind = 'count'")


def downgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("cash_movements")}
    meaningless = "kind NOT IN ('in', 'out', 'take')"
    if "stash_owner_id" in cols:
        meaningless += " OR (kind = 'take' AND stash_owner_id IS NOT NULL)"
    if "pocket" in cols:
        meaningless += " OR pocket = 'private'"
    blocking = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM cash_movements WHERE deleted_at IS NULL AND ({meaningless})")
    ).scalar()
    if blocking:
        raise RuntimeError(
            f"Cannot downgrade: {blocking} cash movement(s) are stash movements, takes from "
            "a stash or wallet amounts, which the previous schema would read as spent cash "
            "visible to the whole household. Delete them first."
        )

    op.execute("UPDATE cash_movements SET kind = 'in' WHERE kind = 'take'")
    # Soft-deleted rows only (see above): fit them back into VARCHAR(8).
    op.execute("UPDATE cash_movements SET kind = 'count' WHERE kind = 'still_have'")

    if "cash_pocket" in {c["name"] for c in sa.inspect(conn).get_columns("transactions")}:
        with op.batch_alter_table("transactions") as batch:
            batch.drop_column("cash_pocket")

    indexes = {i["name"] for i in sa.inspect(conn).get_indexes("cash_movements")}
    for name in ("ix_cash_movements_transaction_id", "ix_cash_movements_stash_owner_id"):
        if name in indexes:
            op.drop_index(name, table_name="cash_movements")
    with op.batch_alter_table("cash_movements") as batch:
        if "stash_owner_id" in cols:
            batch.drop_constraint("fk_cash_movements_stash_owner_id", type_="foreignkey")
            batch.drop_column("stash_owner_id")
        if "transaction_id" in cols:
            batch.drop_constraint("fk_cash_movements_transaction_id", type_="foreignkey")
            batch.drop_column("transaction_id")
        if "pocket" in cols:
            batch.drop_column("pocket")
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=16),
            type_=sa.String(length=8),
            existing_nullable=False,
        )

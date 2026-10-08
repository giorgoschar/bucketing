"""polish round: shopping_lines.stock_item_id index, cash_movements.client_id,
price_snapshots.source

* ``ix_shopping_lines_stock_item_id``: untick by item and the per-item tick
  lookups (the partial unique index only covers active ticks).
* ``cash_movements.client_id``: the PWA's retry key; a save replayed within
  24 h returns the movement it already made. Indexed with the household, not
  unique: the replay window is 24 h.
* ``price_snapshots.source``: ``posokanei`` (the server default, so every
  existing row is one) or ``manual`` (a price the user logged).

Additive: the downgrade drops the two columns and the two indexes.

Revision ID: f2a3b4c5d6e7
Revises: b0c1d2e3f4a5
Create Date: 2026-10-08 18:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a3b4c5d6e7"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_shopping_lines_stock_item_id", "shopping_lines", ["stock_item_id"])
    with op.batch_alter_table("cash_movements") as batch:
        batch.add_column(sa.Column("client_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_cash_movements_hh_client_id", ["household_id", "client_id"])
    with op.batch_alter_table("price_snapshots") as batch:
        batch.add_column(
            sa.Column("source", sa.String(length=16), nullable=True, server_default="posokanei")
        )


def downgrade() -> None:
    with op.batch_alter_table("price_snapshots") as batch:
        batch.drop_column("source")
    with op.batch_alter_table("cash_movements") as batch:
        batch.drop_index("ix_cash_movements_hh_client_id")
        batch.drop_column("client_id")
    op.drop_index("ix_shopping_lines_stock_item_id", table_name="shopping_lines")

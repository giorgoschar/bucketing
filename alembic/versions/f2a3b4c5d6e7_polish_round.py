"""polish round: shopping_lines.stock_item_id index, cash_movements.client_id,
price_snapshots.source, ingest_attempts

* ``ix_shopping_lines_stock_item_id``: untick by item and the per-item tick
  lookups (the partial unique index only covers active ticks).
* ``cash_movements.client_id``: the PWA's retry key; a save replayed within
  24 h returns the movement it already made. Indexed with the household, not
  unique: the replay window is 24 h.
* ``price_snapshots.source``: ``posokanei`` (the server default, so every
  existing row is one) or ``manual`` (a price the user logged).

* ``ingest_attempts``: the last 50 Apple Pay ingest requests per member and
  household (pruned by the app on insert), with the outcome and the reason for a
  rejection, so a member can debug their Shortcut.

Additive: the downgrade drops the table, the two columns and the two indexes.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-08 18:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
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

    op.create_table(
        "ingest_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "token_id",
            sa.String(),
            sa.ForeignKey("personal_api_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("merchant", sa.String(length=80), nullable=True),
        sa.Column("amount_raw", sa.String(length=40), nullable=True),
        sa.Column(
            "transaction_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ingest_attempts_hh_created", "ingest_attempts", ["household_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_attempts_hh_created", table_name="ingest_attempts")
    op.drop_table("ingest_attempts")
    with op.batch_alter_table("price_snapshots") as batch:
        batch.drop_column("source")
    with op.batch_alter_table("cash_movements") as batch:
        batch.drop_index("ix_cash_movements_hh_client_id")
        batch.drop_column("client_id")
    op.drop_index("ix_shopping_lines_stock_item_id", table_name="shopping_lines")

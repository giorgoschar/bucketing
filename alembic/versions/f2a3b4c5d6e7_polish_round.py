"""polish round: shopping_lines.stock_item_id index, cash_movements.client_id,
price_snapshots.source

* ``ix_shopping_lines_stock_item_id``: untick by item and the per-item tick
  lookups (the partial unique index only covers active ticks).
* ``cash_movements.client_id``: the PWA's retry key; a save replayed within
  24 h returns the movement it already made. Indexed with the household, not
  unique: the replay window is 24 h.
* ``price_snapshots.source``: ``posokanei`` (the server default, so every
  existing row is one) or ``manual`` (a price the user logged).

* ``ingest_attempts.summary_version``: 1 on every row the summary code writes, NULL
  (no default) on rows that existed before, whose payload is the raw body. Readers
  show a payload only for version 1.

* ``transactions.ingest_token_id``: the ingest token that created the expense (NULL
  for everything else); it authorises the Shortcut's classify call.

* data step ``_wipe_legacy_raw_attempts`` (kept isolated; it can be dropped on its
  own): rows with no summary_version were written when the diagnostics stored the
  raw request body. Their ``payload`` and ``content_type`` are NULLed, and
  ``detail`` where the status could carry input (everything but 200/201/401/409/429,
  whose detail is fixed text). Idempotent; the downgrade cannot restore it.

Otherwise additive: the downgrade drops the two columns and the two indexes.

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

    with op.batch_alter_table("ingest_attempts") as batch:
        batch.add_column(sa.Column("summary_version", sa.SmallInteger(), nullable=True))
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(
            sa.Column(
                "ingest_token_id",
                sa.String(),
                sa.ForeignKey(
                    "personal_api_tokens.id",
                    name="fk_transactions_ingest_token_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
    _wipe_legacy_raw_attempts()


def _wipe_legacy_raw_attempts() -> None:
    """Remove the raw bodies main's first diagnostics stored (see the docstring).
    Only rows without a summary_version are touched, so it can run again."""
    op.execute(
        "UPDATE ingest_attempts SET payload = NULL, content_type = NULL, "
        "detail = CASE WHEN status IN (200, 201, 401, 409, 429) THEN detail ELSE NULL END "
        "WHERE summary_version IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("fk_transactions_ingest_token_id", type_="foreignkey")
        batch.drop_column("ingest_token_id")
    with op.batch_alter_table("ingest_attempts") as batch:
        batch.drop_column("summary_version")
    with op.batch_alter_table("price_snapshots") as batch:
        batch.drop_column("source")
    with op.batch_alter_table("cash_movements") as batch:
        batch.drop_index("ix_cash_movements_hh_client_id")
        batch.drop_column("client_id")
    op.drop_index("ix_shopping_lines_stock_item_id", table_name="shopping_lines")

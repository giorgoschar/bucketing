"""recurring_bills.payment_method: how a recurring item is paid by default

Without it every auto-paid and one-tap payment was recorded as "card"
(2d spec §7.0). Plain VARCHAR(16) like transactions.payment_method,
validated by app.models.PaymentMethod in Python, so adding a method never
needs ALTER TYPE.

Backfill, in this migration:
- in items get 'transfer' (what receive_occurrence always recorded);
- other items get the method of their most recent active linked
  transaction (recurring_bill_id), by transaction_date, then created_at
  (rows without one count as older), then id;
- items with none keep the 'card' default.

Additive: the old app ignores the column.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-07 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

BACKFILL_IN = "UPDATE recurring_bills SET payment_method = 'transfer' WHERE direction = 'in'"
# Only known methods are copied, so a stray legacy value never becomes a bill's default.
# (created_at IS NULL) sorts false before true on both dialects, so rows with a
# created_at come first whatever the dialect does with NULLs in DESC.
BACKFILL_OUT = (
    "UPDATE recurring_bills SET payment_method = ("
    "  SELECT t.payment_method FROM transactions t"
    "  WHERE t.recurring_bill_id = recurring_bills.id AND t.deleted_at IS NULL"
    "  AND t.payment_method IN ('card', 'cash', 'apple_pay', 'transfer', 'other')"
    "  ORDER BY t.transaction_date DESC, (t.created_at IS NULL), t.created_at DESC, t.id DESC"
    "  LIMIT 1"
    ") WHERE direction <> 'in' AND EXISTS ("
    "  SELECT 1 FROM transactions t"
    "  WHERE t.recurring_bill_id = recurring_bills.id AND t.deleted_at IS NULL"
    "  AND t.payment_method IN ('card', 'cash', 'apple_pay', 'transfer', 'other')"
    ")"
)


def upgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.add_column(
            sa.Column("payment_method", sa.String(16), nullable=False, server_default="card")
        )
    op.execute(BACKFILL_IN)
    op.execute(BACKFILL_OUT)


def downgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.drop_column("payment_method")

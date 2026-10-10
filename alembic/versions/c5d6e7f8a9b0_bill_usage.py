"""bill usage: recurring_bills.usage_unit, bill_occurrences.usage

* ``recurring_bills.usage_unit``: ``String(12)``, nullable. NULL means the item
  does not track usage (kWh, m3 ...).
* ``bill_occurrences.usage``: ``Numeric(12, 3)``, nullable. What the entry used.

Both are additive and nullable; no data is rewritten. The downgrade drops both
columns.

Revision ID: c5d6e7f8a9b0
Revises: f2a3b4c5d6e7
Create Date: 2026-10-09 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c5d6e7f8a9b0"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.add_column(sa.Column("usage_unit", sa.String(length=12), nullable=True))
    with op.batch_alter_table("bill_occurrences") as batch:
        batch.add_column(sa.Column("usage", sa.Numeric(12, 3), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bill_occurrences") as batch:
        batch.drop_column("usage")
    with op.batch_alter_table("recurring_bills") as batch:
        batch.drop_column("usage_unit")

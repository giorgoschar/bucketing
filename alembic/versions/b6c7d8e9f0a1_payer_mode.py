"""payer_mode on transactions and recurring bills

"Each paid their own share": an expense (or a bill's payments) where every
member paid their split directly, e.g. rent paid 800 / 300 straight to the
landlord. Nobody fronted money for anybody, so there is no single payer.

- transactions.payer_mode VARCHAR(16) NOT NULL server_default 'single'
- recurring_bills.payer_mode VARCHAR(16) NOT NULL server_default 'single'

Existing rows become 'single' (today's meaning), so nothing changes for them.
Plain String validated by a Python enum (app.models.PayerMode), like
payment_method: adding a mode never needs ALTER TYPE.

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-10-05 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a1"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("transactions", "recurring_bills"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "payer_mode", sa.String(length=16), nullable=False, server_default="single"
                )
            )


def downgrade() -> None:
    for table in ("recurring_bills", "transactions"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("payer_mode")

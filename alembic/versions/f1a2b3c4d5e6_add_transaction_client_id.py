"""add transactions.client_id for offline idempotency

A queued offline expense can be retried after its response was lost. Without a
client-supplied id the retry creates a second transaction.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e0f1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("client_id", sa.String(length=64), nullable=True))
        # NULLs do not collide, so existing rows are unaffected.
        batch.create_unique_constraint("uq_transaction_client_id", ["household_id", "client_id"])


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("uq_transaction_client_id", type_="unique")
        batch.drop_column("client_id")

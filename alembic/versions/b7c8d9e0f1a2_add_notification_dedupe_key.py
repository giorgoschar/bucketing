"""add notification dedupe_key

Makes scheduler-emitted notifications idempotent: the same bill occurrence can
never produce two notifications for the same user, no matter how many times the
job runs (server restarts, multiple uvicorn workers, catch-up runs).

Revision ID: b7c8d9e0f1a2
Revises: 8c4f34f54a84
Create Date: 2026-07-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "8c4f34f54a84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(sa.Column("dedupe_key", sa.String(length=200), nullable=True))
        # NULL dedupe_keys never collide, so ad-hoc notifications are unaffected.
        batch.create_unique_constraint("uq_notification_dedupe", ["user_id", "dedupe_key"])


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint("uq_notification_dedupe", type_="unique")
        batch.drop_column("dedupe_key")

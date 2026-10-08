"""notification_mutes: alert types a member turned off in a household

A row means muted; no row means on (2d spec §7.6). ``type`` holds a
NotificationType value as plain VARCHAR(32), validated in Python, so this
table never touches the native notificationtype enum.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-07 13:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_mutes",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "household_id", "type", name="pk_notification_mutes"),
    )


def downgrade() -> None:
    op.drop_table("notification_mutes")

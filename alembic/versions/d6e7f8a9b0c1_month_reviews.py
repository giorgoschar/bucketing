"""month reviews: month_reviews table, notificationtype 'month_review'

Phase B. A household marks a past month as reviewed; one row per household
and month. Purely additive.

The downgrade drops the table. The enum label stays (PostgreSQL cannot drop
one); month_review notifications are deleted first so the old code never reads
a value it does not know.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-10-10 09:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None

NEW_VALUES = ("month_review",)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in NEW_VALUES:
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "month_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("household_id", sa.String(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("household_id", "month", name="uq_month_review_household_month"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Compare as text: on PostgreSQL the label was added by this revision's
    # upgrade, and the cast keeps the statement valid either way.
    bind.execute(sa.text("DELETE FROM notifications WHERE CAST(type AS VARCHAR) = 'month_review'"))
    op.drop_table("month_reviews")

"""category rule dismissals: the "Not now" counter behind rule suggestions

Phase C. One row per household and folded pattern; two dismissals stop the
suggestion. Purely additive.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-10-11 09:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category_rule_dismissals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("household_id", sa.String(), nullable=False),
        sa.Column("pattern", sa.String(length=200), nullable=False),
        sa.Column("times", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("household_id", "pattern", name="uq_category_rule_dismissal"),
    )


def downgrade() -> None:
    op.drop_table("category_rule_dismissals")

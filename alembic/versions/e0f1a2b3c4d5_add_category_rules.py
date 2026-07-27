"""add category_rules

User-editable "merchant contains X -> category Y" mappings, checked before the
built-in keyword list so corrections stick.

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "category_rules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("household_id", sa.String(), nullable=False),
        sa.Column("pattern", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.String(), nullable=False),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("household_id", "pattern", name="uq_category_rule"),
    )
    op.create_index("ix_category_rules_household", "category_rules", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_category_rules_household", table_name="category_rules")
    op.drop_table("category_rules")

"""shopping_lines: shopping-list ticks and one-off lines (Plan › Pantry)

A row with ``stock_item_id`` is a tick on a computed shopping-list item; one
without is a one-off line (``name``). Active means ``cleared_at IS NULL``; a
partial unique index allows one active tick per stock item (pantry spec
§3.1). Additive: the downgrade drops the table.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-08 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None

_ACTIVE_TICK = "cleared_at IS NULL AND stock_item_id IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "shopping_lines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stock_item_id",
            sa.String(),
            sa.ForeignKey("stock_items.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_by",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_shopping_lines_household_id", "shopping_lines", ["household_id"])
    op.create_index(
        "uq_shopping_lines_active_tick",
        "shopping_lines",
        ["stock_item_id"],
        unique=True,
        sqlite_where=sa.text(_ACTIVE_TICK),
        postgresql_where=sa.text(_ACTIVE_TICK),
    )


def downgrade() -> None:
    op.drop_index("uq_shopping_lines_active_tick", table_name="shopping_lines")
    op.drop_index("ix_shopping_lines_household_id", table_name="shopping_lines")
    op.drop_table("shopping_lines")

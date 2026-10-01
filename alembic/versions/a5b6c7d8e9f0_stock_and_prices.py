"""stock and prices

Phase 6: household stock list, consumption log and PosoKanei price history.
Purely additive — four new tables and two new notificationtype labels; no
existing row is touched.

- products: per-household catalogue entry, optionally linked to PosoKanei.
  barcode is unique per household when set (partial index on PostgreSQL; a
  plain unique index on SQLite is equivalent because NULLs never collide).
  archived_at lets the UI "remove" a product without losing its history.
- stock_items: current quantity / threshold per product.
- stock_movements: buy/use/adjust log, used for run-out prediction.
- price_snapshots: one row per product, retailer and day.

Revision ID: a5b6c7d8e9f0
Revises: d2e3f4a5b6c7
Create Date: 2026-10-01

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'a5b6c7d8e9f0'
# NOTE: re-pointed to the Phase 5 head (f4a5b6c7d8e9) when merged after 4–5.
down_revision: str | None = 'd2e3f4a5b6c7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_VALUES = ("stock_low", "price_drop")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for value in NEW_VALUES:
            # Allowed inside a transaction on PostgreSQL 12+ as long as the new
            # label is not used in the same transaction (it is not).
            op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")

    op.create_table(
        "products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("household_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brand", sa.String(100), nullable=True),
        sa.Column("barcode", sa.String(32), nullable=True),
        sa.Column("posokanei_id", sa.String(64), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("unit_quantity", sa.Numeric(10, 3), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_products_household_id", "products", ["household_id"])
    op.create_index(
        "uq_products_household_barcode", "products", ["household_id", "barcode"],
        unique=True, postgresql_where=sa.text("barcode IS NOT NULL"),
    )

    op.create_table(
        "stock_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("household_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("min_quantity", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("track_price", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("product_id", name="uq_stock_items_product_id"),
    )
    op.create_index("ix_stock_items_household_id", "stock_items", ["household_id"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("stock_item_id", sa.String(), nullable=False),
        sa.Column("delta", sa.Numeric(10, 2), nullable=False),
        sa.Column("reason", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["stock_item_id"], ["stock_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_stock_movements_item_created", "stock_movements", ["stock_item_id", "created_at"]
    )

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("retailer", sa.String(40), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 4), nullable=True),
        sa.Column("is_discount", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("product_id", "retailer", "snapshot_date", name="uq_price_snapshot"),
    )
    op.create_index(
        "ix_price_snapshots_product_date", "price_snapshots", ["product_id", "snapshot_date"]
    )


def downgrade() -> None:
    # Drops only the tables this revision created. The two enum labels stay:
    # PostgreSQL cannot remove a value from an enum type (see a2b3c4d5e6f7).
    op.drop_index("ix_price_snapshots_product_date", table_name="price_snapshots")
    op.drop_table("price_snapshots")
    op.drop_index("ix_stock_movements_item_created", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_stock_items_household_id", table_name="stock_items")
    op.drop_table("stock_items")
    op.drop_index("uq_products_household_barcode", table_name="products")
    op.drop_index("ix_products_household_id", table_name="products")
    op.drop_table("products")

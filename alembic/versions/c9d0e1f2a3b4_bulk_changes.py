"""bulk changes: batches with per-row undo, and dismissed duplicate pairs

Additive only (2c spec §5.5). Three new tables and nothing altered, so plain
create_table works on SQLite and Postgres alike. Batch mode is only needed to
alter an existing SQLite table, as in a7b8c9d0e1f2.

- bulk_batches: one row per applied bulk change (who, when, what, totals,
  and the recurring item it moved with its old and new bucket).
- bulk_batch_rows: per transaction, the old and new value of every field
  the batch set. Plain VARCHARs with no FKs, so the history survives
  deletions; undo checks existence itself.
- duplicate_dismissals: "Keep both" pairs, smaller id first, unique.

Downgrade drops all three; the batch history is lost and nothing else reads it.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-07 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

BATCH_INDEX = "ix_bulk_batches_household_created"
ROW_INDEX = "ix_bulk_batch_rows_transaction_id"
DISMISS_INDEX = "ix_duplicate_dismissals_household"
ROW_FIELDS = (
    ("bucket_id", sa.String()),
    ("category_id", sa.String()),
    ("paid_by", sa.String()),
    ("payer_mode", sa.String(16)),
    ("payment_method", sa.String(16)),
)


def upgrade() -> None:
    op.create_table(
        "bulk_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "undone_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.Column("selection", sa.String(8), nullable=False),
        sa.Column("fields", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(200), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("total_out", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_in", sa.Numeric(12, 4), nullable=False),
        sa.Column(
            "bill_id",
            sa.String(),
            sa.ForeignKey("recurring_bills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bill_bucket_old", sa.String(), nullable=True),
        sa.Column("bill_bucket_new", sa.String(), nullable=True),
        sa.Column("bill_moved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(BATCH_INDEX, "bulk_batches", ["household_id", "created_at"])

    value_columns = []
    for name, type_ in ROW_FIELDS:
        value_columns.append(sa.Column(f"old_{name}", type_, nullable=True))
        value_columns.append(sa.Column(f"new_{name}", type_, nullable=True))
    op.create_table(
        "bulk_batch_rows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(),
            sa.ForeignKey("bulk_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *value_columns,
        sa.Column("occurrence_id", sa.String(), nullable=True),
        sa.Column("old_occurrence_paid_by", sa.String(), nullable=True),
        sa.Column("restored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("batch_id", "transaction_id", name="uq_bulk_batch_row"),
    )
    op.create_index(ROW_INDEX, "bulk_batch_rows", ["transaction_id"])

    op.create_table(
        "duplicate_dismissals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "first_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "second_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("first_id", "second_id", name="uq_duplicate_dismissal"),
        sa.CheckConstraint("first_id < second_id", name="ck_duplicate_dismissals_order"),
    )
    op.create_index(DISMISS_INDEX, "duplicate_dismissals", ["household_id"])


def downgrade() -> None:
    op.drop_index(DISMISS_INDEX, table_name="duplicate_dismissals")
    op.drop_table("duplicate_dismissals")
    op.drop_index(ROW_INDEX, table_name="bulk_batch_rows")
    op.drop_table("bulk_batch_rows")
    op.drop_index(BATCH_INDEX, table_name="bulk_batches")
    op.drop_table("bulk_batches")

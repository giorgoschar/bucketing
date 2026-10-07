"""planning redesign: recurring items, bucket kinds, Fixed costs, match suggestions

Additive only (spec §6.1); nothing is dropped or renamed, so the old app keeps
working on the same database.

- recurring_bills: direction ('out'/'in'), rule_kind, rule_day, rule_month,
  rule_adjust, rule_days, rule_weekday, rule_interval_weeks. Every existing
  row becomes out + monthly_interval, whose dates are the old generator's.
- buckets.kind ('monthly'/'event'): trip -> event, every other type -> monthly.
- transactions.recurring_bill_id (FK, SET NULL on delete, indexed), backfilled
  from the transaction of each paid bill occurrence.
- ck_transactions_bucket_unless_income also allows a bucket-less expense that
  is linked to a recurring item (a Fixed cost).
- match_suggestions, empty.
- bill_occurrences.period (indexed with bill_id): the rule period of each
  entry, before business-day adjustment. Every existing row is a
  monthly_interval entry, which is never adjusted, so its period is its due
  date's month.

SQLite cannot alter a CHECK in place, so transactions goes through batch mode
(a table copy), as in d8e9f0a1b2c3. Downgrade refuses while a bucket-less
expense exists, since the old CHECK would reject it; give it a bucket first.

Revision ID: a7b8c9d0e1f2
Revises: f0a1b2c3d4e5
Create Date: 2026-10-06 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_transactions_bucket_unless_income"
# Enums are stored by name, on SQLite and in the Postgres enums alike.
OLD_CHECK_SQL = "bucket_id IS NOT NULL OR type = 'income'"
NEW_CHECK_SQL = "bucket_id IS NOT NULL OR type = 'income' OR recurring_bill_id IS NOT NULL"
FK_NAME = "fk_transactions_recurring_bill_id"
TXN_INDEX = "ix_transactions_recurring_bill_id"
MATCH_INDEX = "ix_match_suggestions_household"
MATCH_OCC_INDEX = "ix_match_suggestions_occurrence"
PERIOD_INDEX = "ix_bill_occurrences_bill_period"
RULE_COLUMNS = (
    "direction",
    "rule_kind",
    "rule_day",
    "rule_month",
    "rule_adjust",
    "rule_days",
    "rule_weekday",
    "rule_interval_weeks",
)


def upgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.add_column(sa.Column("direction", sa.String(8), nullable=False, server_default="out"))
        batch.add_column(
            sa.Column("rule_kind", sa.String(24), nullable=False, server_default="monthly_interval")
        )
        batch.add_column(sa.Column("rule_day", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_month", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("rule_adjust", sa.String(24), nullable=False, server_default="none")
        )
        batch.add_column(sa.Column("rule_days", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_weekday", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_interval_weeks", sa.Integer(), nullable=True))

    with op.batch_alter_table("buckets") as batch:
        batch.add_column(sa.Column("kind", sa.String(8), nullable=False, server_default="monthly"))
    op.execute("UPDATE buckets SET kind = 'event' WHERE type = 'trip'")

    if op.get_bind().dialect.name == "postgresql":
        op.add_column("transactions", sa.Column("recurring_bill_id", sa.String(), nullable=True))
        op.create_foreign_key(
            FK_NAME,
            "transactions",
            "recurring_bills",
            ["recurring_bill_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_constraint(CHECK_NAME, "transactions", type_="check")
        op.create_check_constraint(CHECK_NAME, "transactions", NEW_CHECK_SQL)
    else:
        with op.batch_alter_table("transactions") as batch:
            batch.add_column(sa.Column("recurring_bill_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                FK_NAME, "recurring_bills", ["recurring_bill_id"], ["id"], ondelete="SET NULL"
            )
            batch.drop_constraint(CHECK_NAME, type_="check")
            batch.create_check_constraint(CHECK_NAME, NEW_CHECK_SQL)
    op.create_index(TXN_INDEX, "transactions", ["recurring_bill_id"])
    op.execute(
        "UPDATE transactions SET recurring_bill_id = ("
        "  SELECT o.bill_id FROM bill_occurrences o"
        "  WHERE o.transaction_id = transactions.id AND o.status = 'paid'"
        "  ORDER BY o.due_date LIMIT 1"
        ") WHERE id IN ("
        "  SELECT transaction_id FROM bill_occurrences"
        "  WHERE status = 'paid' AND transaction_id IS NOT NULL"
        ")"
    )

    op.create_table(
        "match_suggestions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "occurrence_id",
            sa.String(),
            sa.ForeignKey("bill_occurrences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("transaction_id", "occurrence_id", name="uq_match_suggestion"),
    )
    op.create_index(MATCH_INDEX, "match_suggestions", ["household_id", "dismissed"])
    op.create_index(MATCH_OCC_INDEX, "match_suggestions", ["occurrence_id"])

    op.add_column("bill_occurrences", sa.Column("period", sa.String(10), nullable=True))
    if op.get_bind().dialect.name == "postgresql":
        op.execute("UPDATE bill_occurrences SET period = to_char(due_date, 'YYYY-MM')")
    else:
        op.execute("UPDATE bill_occurrences SET period = strftime('%Y-%m', due_date)")
    op.create_index(PERIOD_INDEX, "bill_occurrences", ["bill_id", "period"])


def downgrade() -> None:
    """Refuses rather than lose data. Production rollback = restore the
    pre-migrate dump; this downgrade is for development databases."""
    conn = op.get_bind()
    new_style = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM recurring_bills "
            "WHERE direction <> 'out' OR rule_kind <> 'monthly_interval'"
        )
    ).scalar()
    if new_style:
        raise RuntimeError(
            f"Cannot downgrade: {new_style} recurring item(s) are incoming or use a new "
            "schedule rule; dropping the columns would turn them into plain monthly bills. "
            "Delete them first, or restore the pre-migrate dump."
        )
    fixed = conn.execute(
        sa.text("SELECT COUNT(*) FROM transactions WHERE bucket_id IS NULL AND type <> 'income'")
    ).scalar()
    if fixed:
        raise RuntimeError(
            f"Cannot downgrade: {fixed} Fixed-cost expense(s) have no bucket. "
            "Give them a bucket first."
        )
    op.drop_index(MATCH_OCC_INDEX, table_name="match_suggestions")
    op.drop_index(MATCH_INDEX, table_name="match_suggestions")
    op.drop_table("match_suggestions")

    op.drop_index(PERIOD_INDEX, table_name="bill_occurrences")
    with op.batch_alter_table("bill_occurrences") as batch:
        batch.drop_column("period")

    op.drop_index(TXN_INDEX, table_name="transactions")
    if conn.dialect.name == "postgresql":
        op.drop_constraint(CHECK_NAME, "transactions", type_="check")
        op.create_check_constraint(CHECK_NAME, "transactions", OLD_CHECK_SQL)
        op.drop_constraint(FK_NAME, "transactions", type_="foreignkey")
        op.drop_column("transactions", "recurring_bill_id")
    else:
        with op.batch_alter_table("transactions") as batch:
            batch.drop_constraint(CHECK_NAME, type_="check")
            batch.create_check_constraint(CHECK_NAME, OLD_CHECK_SQL)
            batch.drop_constraint(FK_NAME, type_="foreignkey")
            batch.drop_column("recurring_bill_id")

    with op.batch_alter_table("buckets") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("recurring_bills") as batch:
        for column in reversed(RULE_COLUMNS):
            batch.drop_column(column)

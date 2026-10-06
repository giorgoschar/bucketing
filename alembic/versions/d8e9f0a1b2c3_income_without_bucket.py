"""income without a bucket

transactions.bucket_id becomes nullable so income can be logged without a
bucket. Expenses and transfers still need one: the service and schema check
it, and ck_transactions_bucket_unless_income backs that up in the database.

Postgres alters the column in place. SQLite cannot drop NOT NULL or add a
CHECK with ALTER TABLE, so it goes through batch mode (table copy).

Downgrade refuses while bucket-less income exists rather than deleting it:
assign those rows a bucket first.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-10-05 16:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'd8e9f0a1b2c3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None

CHECK_NAME = 'ck_transactions_bucket_unless_income'
# The enum is stored by name, on SQLite and in the Postgres enum alike.
CHECK_SQL = "bucket_id IS NOT NULL OR type = 'income'"


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        op.alter_column('transactions', 'bucket_id',
                        existing_type=sa.String(), nullable=True)
        op.create_check_constraint(CHECK_NAME, 'transactions', CHECK_SQL)
    else:
        with op.batch_alter_table('transactions') as batch:
            batch.alter_column('bucket_id', existing_type=sa.String(), nullable=True)
            batch.create_check_constraint(CHECK_NAME, CHECK_SQL)


def downgrade() -> None:
    conn = op.get_bind()
    orphans = conn.execute(sa.text(
        "SELECT COUNT(*) FROM transactions WHERE bucket_id IS NULL"
    )).scalar()
    if orphans:
        raise RuntimeError(
            f"Cannot downgrade: {orphans} transaction(s) have no bucket. "
            "Assign them a bucket first."
        )
    if conn.dialect.name == 'postgresql':
        op.drop_constraint(CHECK_NAME, 'transactions', type_='check')
        op.alter_column('transactions', 'bucket_id',
                        existing_type=sa.String(), nullable=False)
    else:
        with op.batch_alter_table('transactions') as batch:
            batch.drop_constraint(CHECK_NAME, type_='check')
            batch.alter_column('bucket_id', existing_type=sa.String(), nullable=False)

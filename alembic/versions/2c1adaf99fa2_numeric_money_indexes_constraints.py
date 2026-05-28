"""numeric_money_indexes_constraints

Revision ID: 2c1adaf99fa2
Revises: e5f6a7b8c9d0
Create Date: 2026-05-28 12:15:52.697007

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c1adaf99fa2'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('bill_occurrences') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=4),
                              existing_nullable=True)
        batch_op.drop_index('uq_bill_occurrence')
        batch_op.create_unique_constraint('uq_bill_occurrence', ['bill_id', 'due_date'])

    op.create_index('ix_bill_occurrences_bill_status', 'bill_occurrences', ['bill_id', 'due_date', 'status'], unique=False)

    with op.batch_alter_table('buckets') as batch_op:
        batch_op.alter_column('budget',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=4),
                              existing_nullable=True)

    op.create_index('ix_categories_household_id', 'categories', ['household_id'], unique=False)

    with op.batch_alter_table('household_members') as batch_op:
        batch_op.create_unique_constraint('uq_household_member', ['household_id', 'user_id'])

    op.create_index('ix_household_members_household_id', 'household_members', ['household_id'], unique=False)

    with op.batch_alter_table('notifications') as batch_op:
        batch_op.alter_column('type',
                              existing_type=sa.VARCHAR(length=14),
                              type_=sa.Enum('bill_due', 'bill_overdue', 'bill_auto_paid', 'contract_expiring', 'general', name='notificationtype'),
                              existing_nullable=False)

    with op.batch_alter_table('recurring_bill_splits') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=4),
                              existing_nullable=False)

    with op.batch_alter_table('recurring_bills') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=4),
                              existing_nullable=True)

    with op.batch_alter_table('transaction_splits') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=4),
                              existing_nullable=False)

    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=4),
                              existing_nullable=False)
        batch_op.alter_column('exchange_rate',
                              existing_type=sa.FLOAT(),
                              type_=sa.Numeric(precision=12, scale=6),
                              existing_nullable=True)

    op.create_index('ix_transactions_bucket_id', 'transactions', ['bucket_id'], unique=False)
    op.create_index('ix_transactions_household_date', 'transactions', ['household_id', 'transaction_date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_transactions_household_date', table_name='transactions')
    op.drop_index('ix_transactions_bucket_id', table_name='transactions')

    with op.batch_alter_table('transactions') as batch_op:
        batch_op.alter_column('exchange_rate',
                              existing_type=sa.Numeric(precision=12, scale=6),
                              type_=sa.FLOAT(),
                              existing_nullable=True)
        batch_op.alter_column('amount',
                              existing_type=sa.Numeric(precision=12, scale=4),
                              type_=sa.FLOAT(),
                              existing_nullable=False)

    with op.batch_alter_table('transaction_splits') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.Numeric(precision=12, scale=4),
                              type_=sa.FLOAT(),
                              existing_nullable=False)

    with op.batch_alter_table('recurring_bills') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.Numeric(precision=12, scale=4),
                              type_=sa.FLOAT(),
                              existing_nullable=True)

    with op.batch_alter_table('recurring_bill_splits') as batch_op:
        batch_op.alter_column('amount',
                              existing_type=sa.Numeric(precision=12, scale=4),
                              type_=sa.FLOAT(),
                              existing_nullable=False)

    with op.batch_alter_table('notifications') as batch_op:
        batch_op.alter_column('type',
                              existing_type=sa.Enum('bill_due', 'bill_overdue', 'bill_auto_paid', 'contract_expiring', 'general', name='notificationtype'),
                              type_=sa.VARCHAR(length=14),
                              existing_nullable=False)

    with op.batch_alter_table('household_members') as batch_op:
        batch_op.drop_constraint('uq_household_member', type_='unique')

    op.drop_index('ix_household_members_household_id', table_name='household_members')
    op.drop_index('ix_categories_household_id', table_name='categories')

    with op.batch_alter_table('buckets') as batch_op:
        batch_op.alter_column('budget',
                              existing_type=sa.Numeric(precision=12, scale=4),
                              type_=sa.FLOAT(),
                              existing_nullable=True)

    op.drop_index('ix_bill_occurrences_bill_status', table_name='bill_occurrences')

    with op.batch_alter_table('bill_occurrences') as batch_op:
        batch_op.drop_constraint('uq_bill_occurrence', type_='unique')
        batch_op.create_index('uq_bill_occurrence', ['bill_id', 'due_date'], unique=True)
        batch_op.alter_column('amount',
                              existing_type=sa.Numeric(precision=12, scale=4),
                              type_=sa.FLOAT(),
                              existing_nullable=True)

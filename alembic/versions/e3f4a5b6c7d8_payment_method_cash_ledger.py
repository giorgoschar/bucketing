"""payment_method, merchant, cash_movements

Phase 4: how an expense was paid + the cash wallet ledger.

- transactions.payment_method VARCHAR(16) NOT NULL server_default 'card'
  (existing rows become 'card' — nothing is lost). Plain String validated by a
  Python enum (app.models.PaymentMethod); deliberately NOT a Postgres ENUM, so
  adding a method never needs ALTER TYPE.
- transactions.merchant VARCHAR(200) NULL
- cash_movements table (+ index on household_id, user_id, movement_date)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-01 14:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('transactions') as batch:
        batch.add_column(sa.Column('payment_method', sa.String(length=16),
                                   nullable=False, server_default='card'))
        batch.add_column(sa.Column('merchant', sa.String(length=200), nullable=True))

    op.create_table(
        'cash_movements',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('household_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('amount', sa.Numeric(12, 4), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('category_id', sa.String(), nullable=True),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('movement_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
    )
    op.create_index('ix_cash_movements_hh_user_date', 'cash_movements',
                    ['household_id', 'user_id', 'movement_date'])


def downgrade() -> None:
    op.drop_index('ix_cash_movements_hh_user_date', table_name='cash_movements')
    op.drop_table('cash_movements')
    with op.batch_alter_table('transactions') as batch:
        batch.drop_column('merchant')
        batch.drop_column('payment_method')

"""add_transaction_exclude_from_settlement

Additive column with a server default, so existing rows keep their current
behaviour (included in settle-up) and no data is rewritten.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-07-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'transactions',
        sa.Column(
            'exclude_from_settlement',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('transactions', 'exclude_from_settlement')

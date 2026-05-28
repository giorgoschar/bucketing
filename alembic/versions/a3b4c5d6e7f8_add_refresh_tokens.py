"""add_refresh_tokens

Revision ID: a3b4c5d6e7f8
Revises: 2c1adaf99fa2
Create Date: 2026-05-28 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = '2c1adaf99fa2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'refresh_tokens',
        sa.Column('id',           sa.String(),  nullable=False),
        sa.Column('user_id',      sa.String(),  nullable=False),
        sa.Column('household_id', sa.String(),  nullable=False),
        sa.Column('token_hash',   sa.String(),  nullable=False, unique=True),
        sa.Column('expires_at',   sa.DateTime(), nullable=False),
        sa.Column('revoked',      sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at',   sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'])


def downgrade() -> None:
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')

"""personal_api_tokens

Phase 5: per-member ingest tokens for the iOS Shortcut (Apple Pay automation).

- personal_api_tokens table: only the SHA-256 of a token is stored
  (token_hash, unique); prefix is the first 12 chars for display. Revocation
  sets revoked_at — rows are kept.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-10-01 16:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'personal_api_tokens',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('household_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=12), nullable=False),
        sa.Column('scopes', sa.String(length=100), nullable=False, server_default='ingest'),
        sa.Column('default_bucket_id', sa.String(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['default_bucket_id'], ['buckets.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('token_hash', name='uq_personal_api_tokens_token_hash'),
    )
    op.create_index('ix_personal_api_tokens_user_household', 'personal_api_tokens',
                    ['user_id', 'household_id'])


def downgrade() -> None:
    op.drop_index('ix_personal_api_tokens_user_household', table_name='personal_api_tokens')
    op.drop_table('personal_api_tokens')

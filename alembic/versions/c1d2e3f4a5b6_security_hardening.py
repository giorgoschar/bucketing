"""security_hardening

Phase 1 schema changes. All additive; no data is dropped or rewritten:

- refresh_tokens.session_version: tokens carry the user's session_version at issue.
- users.last_totp_step / failed_logins / locked_until: TOTP replay protection
  and per-account lockout.
- users.totp_secret widened to VARCHAR(512) so the encrypted value fits
  (existing plaintext secrets are kept as-is and still read).
- transactions.deleted_at (+ index): soft delete.
- households.archived_at: archive instead of delete.

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-10-01 00:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'c1d2e3f4a5b6'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'refresh_tokens',
        sa.Column('session_version', sa.Integer(), nullable=False, server_default='0'),
    )

    op.add_column('users', sa.Column('last_totp_step', sa.BigInteger(), nullable=True))
    op.add_column(
        'users',
        sa.Column('failed_logins', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('users', sa.Column('locked_until', sa.DateTime(), nullable=True))
    with op.batch_alter_table('users') as batch:
        batch.alter_column(
            'totp_secret',
            existing_type=sa.String(),
            type_=sa.String(length=512),
            existing_nullable=True,
        )

    op.add_column('transactions', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index('ix_transactions_deleted_at', 'transactions', ['deleted_at'])

    op.add_column('households', sa.Column('archived_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('households', 'archived_at')

    op.drop_index('ix_transactions_deleted_at', table_name='transactions')
    op.drop_column('transactions', 'deleted_at')

    # Encrypted secrets longer than the old (unbounded VARCHAR) type never
    # existed, so narrowing back is a no-op in practice; keep the type generic.
    with op.batch_alter_table('users') as batch:
        batch.alter_column(
            'totp_secret',
            existing_type=sa.String(length=512),
            type_=sa.String(),
            existing_nullable=True,
        )
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_logins')
    op.drop_column('users', 'last_totp_step')

    op.drop_column('refresh_tokens', 'session_version')

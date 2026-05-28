"""add_user_email

Revision ID: f1e2d3c4b5a6
Revises: 2c1adaf99fa2
Create Date: 2026-05-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1e2d3c4b5a6'
down_revision = '2c1adaf99fa2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email', sa.String(254), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='false'))
    op.create_index('ix_users_email', 'users', ['email'], unique=True)


def downgrade():
    op.drop_index('ix_users_email', table_name='users')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'email')

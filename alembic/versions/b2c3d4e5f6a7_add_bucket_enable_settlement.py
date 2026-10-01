"""add_bucket_enable_settlement

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-15 13:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('buckets', sa.Column('enable_settlement', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('buckets', 'enable_settlement')

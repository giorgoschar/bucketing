"""add_notifications_and_push_subscriptions

Revision ID: a1b2c3d4e5f6
Revises: 9bba00013182
Create Date: 2026-05-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9bba00013182'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id',           sa.String(),  nullable=False),
        sa.Column('household_id', sa.String(),  nullable=False),
        sa.Column('user_id',      sa.String(),  nullable=False),
        sa.Column('type',         sa.String(),  nullable=False),
        sa.Column('title',        sa.String(200), nullable=False),
        sa.Column('body',         sa.Text(),    nullable=True),
        sa.Column('link',         sa.String(),  nullable=True),
        sa.Column('is_read',      sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at',   sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'],      ['users.id'],      ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_notifications_household_id', 'notifications', ['household_id'])
    op.create_index('ix_notifications_user_id',      'notifications', ['user_id'])

    op.create_table(
        'push_subscriptions',
        sa.Column('id',           sa.String(), nullable=False),
        sa.Column('user_id',      sa.String(), nullable=False),
        sa.Column('household_id', sa.String(), nullable=False),
        sa.Column('endpoint',     sa.Text(),   nullable=False),
        sa.Column('p256dh',       sa.Text(),   nullable=False),
        sa.Column('auth',         sa.Text(),   nullable=False),
        sa.Column('created_at',   sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'],      ['users.id'],      ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('endpoint'),
    )
    op.create_index('ix_push_subscriptions_user_id', 'push_subscriptions', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_push_subscriptions_user_id', 'push_subscriptions')
    op.drop_table('push_subscriptions')
    op.drop_index('ix_notifications_user_id',      'notifications')
    op.drop_index('ix_notifications_household_id', 'notifications')
    op.drop_table('notifications')

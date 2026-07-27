"""add bucket start_date, end_date and goal_amount

Gives the trip and savings bucket types actual behaviour: trips get a date
range, savings buckets get a target amount and target date.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("buckets") as batch:
        batch.add_column(sa.Column("start_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("end_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("goal_amount", sa.Numeric(12, 4), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("buckets") as batch:
        batch.drop_column("goal_amount")
        batch.drop_column("end_date")
        batch.drop_column("start_date")

"""add unique constraint to bill_occurrences

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-27

This migration deduplicates any existing duplicate (bill_id, due_date) rows
(keeping the row that is already paid, or the alphabetically-first id otherwise)
then adds a unique constraint to prevent future duplicates.
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    # Deduplicate: for each (bill_id, due_date) keep the best row:
    # - prefer the row that already has a transaction_id (paid occurrence)
    # - fallback: keep the lexicographically smallest id
    op.execute("""
        DELETE FROM bill_occurrences
        WHERE id NOT IN (
            SELECT COALESCE(
                MAX(CASE WHEN transaction_id IS NOT NULL THEN id END),
                MIN(id)
            ) AS keep_id
            FROM bill_occurrences
            GROUP BY bill_id, due_date
        )
    """)

    # Add unique index (works on both SQLite and PostgreSQL)
    op.create_index(
        'uq_bill_occurrence',
        'bill_occurrences',
        ['bill_id', 'due_date'],
        unique=True,
    )


def downgrade():
    op.drop_index('uq_bill_occurrence', table_name='bill_occurrences')

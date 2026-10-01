"""indexes_and_tz

Phase 2 (Q4): indexes on hot join/filter columns. Indexes only; no data is
touched, so upgrade and downgrade are loss-free.

Added:
- transaction_splits(transaction_id), transaction_splits(user_id)
- transactions(paid_by), transactions(category_id)
- recurring_bills(household_id)
- notifications(user_id, household_id, created_at)

Already present (skipped): transactions(household_id, transaction_date),
transactions(bucket_id), transactions(deleted_at), household_members(household_id),
categories(household_id), bill_occurrences(bill_id, due_date, status),
refresh_tokens(user_id), notifications(user_id) and notifications(household_id)
(single-column; the new composite serves the notification list query).

Timezone note (Q6, decided in Task 2.1): DateTime columns deliberately stay
naive UTC (app/clock.py utcnow_naive). There is no column type change here;
"local" calendar dates are derived at the edges via APP_TIMEZONE.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-01 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None

_INDEXES = (
    ('ix_transaction_splits_transaction_id', 'transaction_splits', ['transaction_id']),
    ('ix_transaction_splits_user_id', 'transaction_splits', ['user_id']),
    ('ix_transactions_paid_by', 'transactions', ['paid_by']),
    ('ix_transactions_category_id', 'transactions', ['category_id']),
    ('ix_recurring_bills_household_id', 'recurring_bills', ['household_id']),
    ('ix_notifications_user_household_created', 'notifications',
     ['user_id', 'household_id', 'created_at']),
)


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table)

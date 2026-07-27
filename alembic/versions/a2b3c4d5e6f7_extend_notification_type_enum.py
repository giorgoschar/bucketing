"""extend notificationtype enum with bill_drift and budget_warning

On PostgreSQL notifications.type is a native ENUM (created in
2c1adaf99fa2), so adding members to the Python NotificationType is not enough:
inserting an unknown label fails with

    invalid input value for enum notificationtype: "budget_warning"

which would have broken the bill-drift and budget-threshold alerts in
production. SQLite renders Enum columns as VARCHAR with a CHECK, so the test
suite could never surface this — it was caught by running the app against a
real Postgres database.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = ("bill_drift", "budget_warning")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite stores these as VARCHAR; nothing to alter.
        return
    for value in NEW_VALUES:
        # Adding a label inside a transaction is allowed from PostgreSQL 12
        # onwards provided it is not *used* in the same transaction, which it
        # is not here. IF NOT EXISTS keeps the migration re-runnable.
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL cannot remove a value from an enum type. Dropping and
    # recreating would require rewriting every referencing row, which is a far
    # worse trade than leaving two unused labels in place.
    pass

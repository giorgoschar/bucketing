"""merge_api_and_email_heads

Revision ID: 8c4f34f54a84
Revises: a3b4c5d6e7f8, f1e2d3c4b5a6
Create Date: 2026-05-28 23:20:57.594199

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '8c4f34f54a84'
down_revision: str | None = ('a3b4c5d6e7f8', 'f1e2d3c4b5a6')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

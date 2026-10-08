"""users.oidc_subject for Pocket ID sign-in

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
"""

import sqlalchemy as sa

from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("oidc_subject", sa.String(255), nullable=True))
        batch.create_unique_constraint("uq_users_oidc_subject", ["oidc_subject"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_oidc_subject", type_="unique")
        batch.drop_column("oidc_subject")

"""ingest_attempts: log of Apple Pay Shortcut attempts

Every attempt on POST /api/v1/ingest/apple-pay is recorded — including ones
rejected before the endpoint runs (bad token, rate limit, payload validation)
— so a payment that does not arrive can be diagnosed from Settings →
Automations instead of from a bare "422" in the container log.

household_id / token_id are nullable: an attempt nobody's token can be matched
to is attributed to no one.

Revision ID: a7b8c9d0e1f2
Revises: e9f0a1b2c3d4
Create Date: 2026-10-08 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "token_id",
            sa.String(),
            sa.ForeignKey("personal_api_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("token_prefix", sa.String(length=12), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column(
            "transaction_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ingest_attempts_household_created",
        "ingest_attempts",
        ["household_id", "created_at"],
    )
    op.create_index(
        "ix_ingest_attempts_prefix_created",
        "ingest_attempts",
        ["token_prefix", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_attempts_prefix_created", table_name="ingest_attempts")
    op.drop_index("ix_ingest_attempts_household_created", table_name="ingest_attempts")
    op.drop_table("ingest_attempts")

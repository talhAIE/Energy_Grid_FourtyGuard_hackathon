"""Add controlled provider polling fields to integration jobs.

Revision ID: 20260827_0004
Revises: 20260827_0003
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0004"
down_revision: str | Sequence[str] | None = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "integration_jobs",
        sa.Column("provider_status", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "integration_jobs",
        sa.Column(
            "poll_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("integration_jobs", "poll_attempts", server_default=None)
    op.add_column(
        "integration_jobs",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "integration_jobs",
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_integration_jobs_provider_status",
        "integration_jobs",
        ["provider_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_integration_jobs_provider_status", table_name="integration_jobs")
    op.drop_column("integration_jobs", "raw_response_json")
    op.drop_column("integration_jobs", "last_polled_at")
    op.drop_column("integration_jobs", "poll_attempts")
    op.drop_column("integration_jobs", "provider_status")

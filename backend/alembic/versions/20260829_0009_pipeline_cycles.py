"""Add durable manually advanced pipeline cycles.

Revision ID: 20260829_0009
Revises: 20260829_0008
Create Date: 2026-08-29 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0009"
down_revision: str | Sequence[str] | None = "20260829_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_cycles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("integration_job_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_source", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("forecast_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_advanced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("data_freshness_status", sa.String(length=20), nullable=False),
        sa.Column("zone_forecast_count", sa.Integer(), nullable=False),
        sa.Column("recommendation_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_job_id"],
            ["integration_jobs.id"],
            name="fk_pipeline_cycles_integration_job_id_integration_jobs",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_cycles"),
        sa.UniqueConstraint(
            "integration_job_id",
            name="uq_pipeline_cycles_integration_job_id",
        ),
    )
    op.create_index(
        "ix_pipeline_cycles_integration_job_id",
        "pipeline_cycles",
        ["integration_job_id"],
    )
    op.create_index("ix_pipeline_cycles_status", "pipeline_cycles", ["status"])
    op.create_index("ix_pipeline_cycles_forecast_for", "pipeline_cycles", ["forecast_for"])
    op.create_index("ix_pipeline_cycles_started_at", "pipeline_cycles", ["started_at"])
    op.create_index(
        "ix_pipeline_cycles_status_forecast_for",
        "pipeline_cycles",
        ["status", "forecast_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_cycles_status_forecast_for", table_name="pipeline_cycles")
    op.drop_index("ix_pipeline_cycles_started_at", table_name="pipeline_cycles")
    op.drop_index("ix_pipeline_cycles_forecast_for", table_name="pipeline_cycles")
    op.drop_index("ix_pipeline_cycles_status", table_name="pipeline_cycles")
    op.drop_index("ix_pipeline_cycles_integration_job_id", table_name="pipeline_cycles")
    op.drop_table("pipeline_cycles")

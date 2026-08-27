"""Add FortyGuard heatmap submission context.

Revision ID: 20260827_0003
Revises: 20260827_0002
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0003"
down_revision: str | Sequence[str] | None = "20260827_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "heatmap_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("requested_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity_m", sa.Integer(), nullable=False),
        sa.Column("analytic_type", sa.String(length=40), nullable=False),
        sa.Column(
            "aoi_geometry",
            geoalchemy2.Geometry("MULTIPOLYGON", srid=4326),
            nullable=False,
        ),
        sa.Column("date_time_json", sa.JSON(), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["integration_jobs.id"], name="fk_heatmap_runs_job_id"),
        sa.PrimaryKeyConstraint("id", name="pk_heatmap_runs"),
        sa.UniqueConstraint("job_id", name="uq_heatmap_runs_job_id"),
    )
    op.create_index("ix_heatmap_runs_job_id", "heatmap_runs", ["job_id"], unique=False)
    op.create_index(
        "ix_heatmap_runs_requested_time",
        "heatmap_runs",
        ["requested_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_heatmap_runs_requested_time", table_name="heatmap_runs")
    op.drop_index("ix_heatmap_runs_job_id", table_name="heatmap_runs")
    op.drop_table("heatmap_runs")

"""Add normalized zone temperature observations.

Revision ID: 20260827_0005
Revises: 20260827_0004
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0005"
down_revision: str | Sequence[str] | None = "20260827_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "zone_temperature_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=False),
        sa.Column("observed_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mean_c", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("min_c", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("max_c", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("stddev_c", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("tile_count", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=False),
        sa.Column("is_forecast", sa.Boolean(), nullable=False),
        sa.Column("data_status", sa.String(length=30), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["heatmap_runs.id"],
            name="fk_zone_temperature_observations_source_run_id_heatmap_runs",
        ),
        sa.ForeignKeyConstraint(
            ["zone_id"],
            ["zones.id"],
            name="fk_zone_temperature_observations_zone_id_zones",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_zone_temperature_observations"),
        sa.UniqueConstraint(
            "zone_id",
            "source_run_id",
            name="uq_zone_temperature_observations_zone_run",
        ),
    )
    op.create_index(
        "ix_zone_temperature_observations_zone_id",
        "zone_temperature_observations",
        ["zone_id"],
        unique=False,
    )
    op.create_index(
        "ix_zone_temperature_observations_observed_for",
        "zone_temperature_observations",
        ["observed_for"],
        unique=False,
    )
    op.create_index(
        "ix_zone_temperature_observations_source_run_id",
        "zone_temperature_observations",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_zone_temperature_observations_zone_time",
        "zone_temperature_observations",
        ["zone_id", "observed_for"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_zone_temperature_observations_zone_time",
        table_name="zone_temperature_observations",
    )
    op.drop_index(
        "ix_zone_temperature_observations_source_run_id",
        table_name="zone_temperature_observations",
    )
    op.drop_index(
        "ix_zone_temperature_observations_observed_for",
        table_name="zone_temperature_observations",
    )
    op.drop_index(
        "ix_zone_temperature_observations_zone_id",
        table_name="zone_temperature_observations",
    )
    op.drop_table("zone_temperature_observations")

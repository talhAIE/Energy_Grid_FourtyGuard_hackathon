"""Add persisted Phase 9 zone demand and risk forecasts.

Revision ID: 20260829_0007
Revises: 20260827_0006
Create Date: 2026-08-29 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0007"
down_revision: str | Sequence[str] | None = "20260827_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "zone_forecasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zone_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("forecast_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estimate_type", sa.String(length=30), nullable=False),
        sa.Column("city_forecast_mw", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("allocation_weight", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column("temperature_c", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("city_temperature_c", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("heat_anomaly_c", sa.Numeric(precision=8, scale=3), nullable=False),
        sa.Column("temperature_ramp_c_per_hour", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("temperature_stddev_c", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("baseline_mw", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("predicted_mw", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("uplift_pct", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("uncertainty_penalty", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("risk_score", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("data_freshness_status", sa.String(length=20), nullable=False),
        sa.Column("explanation_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="fk_zone_forecasts_model_version_id_model_versions",
        ),
        sa.ForeignKeyConstraint(["zone_id"], ["zones.id"], name="fk_zone_forecasts_zone_id_zones"),
        sa.PrimaryKeyConstraint("id", name="pk_zone_forecasts"),
        sa.UniqueConstraint(
            "zone_id",
            "model_version_id",
            "forecast_for",
            name="uq_zone_forecasts_zone_model_time",
        ),
    )
    op.create_index("ix_zone_forecasts_zone_id", "zone_forecasts", ["zone_id"], unique=False)
    op.create_index(
        "ix_zone_forecasts_model_version_id", "zone_forecasts", ["model_version_id"], unique=False
    )
    op.create_index(
        "ix_zone_forecasts_forecast_for", "zone_forecasts", ["forecast_for"], unique=False
    )
    op.create_index(
        "ix_zone_forecasts_generated_at", "zone_forecasts", ["generated_at"], unique=False
    )
    op.create_index(
        "ix_zone_forecasts_zone_time", "zone_forecasts", ["zone_id", "forecast_for"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_zone_forecasts_zone_time", table_name="zone_forecasts")
    op.drop_index("ix_zone_forecasts_generated_at", table_name="zone_forecasts")
    op.drop_index("ix_zone_forecasts_forecast_for", table_name="zone_forecasts")
    op.drop_index("ix_zone_forecasts_model_version_id", table_name="zone_forecasts")
    op.drop_index("ix_zone_forecasts_zone_id", table_name="zone_forecasts")
    op.drop_table("zone_forecasts")

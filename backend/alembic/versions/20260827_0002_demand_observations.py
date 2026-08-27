"""Add normalized EIA demand observations.

Revision ID: 20260827_0002
Revises: 20260827_0001
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0002"
down_revision: str | Sequence[str] | None = "20260827_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demand_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("city_id", sa.Uuid(), nullable=False),
        sa.Column("period_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_area_code", sa.String(length=80), nullable=False),
        sa.Column("demand_mw", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("is_actual", sa.Boolean(), nullable=False),
        sa.Column("quality_flag", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["city_id"],
            ["cities.id"],
            name="fk_demand_observations_city_id_cities",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_demand_observations"),
        sa.UniqueConstraint(
            "city_id",
            "source",
            "source_area_code",
            "period_utc",
            name="uq_demand_observations_source_area_period",
        ),
    )
    op.create_index(
        "ix_demand_observations_city_id",
        "demand_observations",
        ["city_id"],
        unique=False,
    )
    op.create_index(
        "ix_demand_observations_period_utc",
        "demand_observations",
        ["period_utc"],
        unique=False,
    )
    op.create_index(
        "ix_demand_observations_city_period",
        "demand_observations",
        ["city_id", "period_utc"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_demand_observations_city_period", table_name="demand_observations")
    op.drop_index("ix_demand_observations_period_utc", table_name="demand_observations")
    op.drop_index("ix_demand_observations_city_id", table_name="demand_observations")
    op.drop_table("demand_observations")

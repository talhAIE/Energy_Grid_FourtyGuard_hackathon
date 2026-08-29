"""Add baseline demand model versions.

Revision ID: 20260827_0006
Revises: 20260827_0005
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0006"
down_revision: str | Sequence[str] | None = "20260827_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("city_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("algorithm", sa.String(length=100), nullable=False),
        sa.Column("feature_schema_version", sa.String(length=30), nullable=False),
        sa.Column("feature_columns", sa.JSON(), nullable=False),
        sa.Column("quality_policy", sa.String(length=100), nullable=False),
        sa.Column("source_dataset_version", sa.String(length=150), nullable=False),
        sa.Column("training_data_sha256", sa.String(length=64), nullable=False),
        sa.Column("trained_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trained_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("training_row_count", sa.Integer(), nullable=False),
        sa.Column("validation_row_count", sa.Integer(), nullable=False),
        sa.Column("mae_mw", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("rmse_mw", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("mape_percent", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("validation_predictions_path", sa.String(length=500), nullable=False),
        sa.Column("artifact_metadata", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["city_id"],
            ["cities.id"],
            name="fk_model_versions_city_id_cities",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_versions"),
        sa.UniqueConstraint("city_id", "version", name="uq_model_versions_city_version"),
    )
    op.create_index("ix_model_versions_city_id", "model_versions", ["city_id"], unique=False)
    op.create_index("ix_model_versions_is_active", "model_versions", ["is_active"], unique=False)
    op.create_index(
        "ix_model_versions_city_active",
        "model_versions",
        ["city_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_versions_city_active", table_name="model_versions")
    op.drop_index("ix_model_versions_is_active", table_name="model_versions")
    op.drop_index("ix_model_versions_city_id", table_name="model_versions")
    op.drop_table("model_versions")

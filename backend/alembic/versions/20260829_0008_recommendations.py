"""Add Phase 10 safety-bounded recommendations and immutable decisions.

Revision ID: 20260829_0008
Revises: 20260829_0007
Create Date: 2026-08-29 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0008"
down_revision: str | Sequence[str] | None = "20260829_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("zone_forecast_id", sa.Uuid(), nullable=False),
        sa.Column("action_code", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["zone_forecast_id"],
            ["zone_forecasts.id"],
            name="fk_recommendations_zone_forecast_id_zone_forecasts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendations"),
        sa.UniqueConstraint(
            "zone_forecast_id",
            name="uq_recommendations_zone_forecast_id",
        ),
    )
    op.create_index("ix_recommendations_zone_forecast_id", "recommendations", ["zone_forecast_id"])
    op.create_index("ix_recommendations_status", "recommendations", ["status"])
    op.create_index("ix_recommendations_expires_at", "recommendations", ["expires_at"])
    op.create_index(
        "ix_recommendations_status_expires_at",
        "recommendations",
        ["status", "expires_at"],
    )

    op.create_table(
        "recommendation_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("operator_name", sa.String(length=120), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendations.id"],
            name="fk_recommendation_decisions_recommendation_id_recommendations",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendation_decisions"),
        sa.UniqueConstraint(
            "recommendation_id",
            name="uq_recommendation_decisions_recommendation_id",
        ),
    )
    op.create_index(
        "ix_recommendation_decisions_recommendation_id",
        "recommendation_decisions",
        ["recommendation_id"],
    )
    op.create_index(
        "ix_recommendation_decisions_decided_at",
        "recommendation_decisions",
        ["decided_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendation_decisions_decided_at", table_name="recommendation_decisions")
    op.drop_index(
        "ix_recommendation_decisions_recommendation_id",
        table_name="recommendation_decisions",
    )
    op.drop_table("recommendation_decisions")
    op.drop_index("ix_recommendations_status_expires_at", table_name="recommendations")
    op.drop_index("ix_recommendations_expires_at", table_name="recommendations")
    op.drop_index("ix_recommendations_status", table_name="recommendations")
    op.drop_index("ix_recommendations_zone_forecast_id", table_name="recommendations")
    op.drop_table("recommendations")

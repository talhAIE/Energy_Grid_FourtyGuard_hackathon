"""Create core PostGIS schema.

Revision ID: 20260827_0001
Revises:
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "cities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("MULTIPOLYGON", srid=4326), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_cities"),
        sa.UniqueConstraint("name", "country_code", name="uq_cities_name_country"),
    )
    op.create_index("ix_cities_name", "cities", ["name"], unique=False)

    op.create_table(
        "zones",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("city_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("geometry", geoalchemy2.Geometry("MULTIPOLYGON", srid=4326), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("allocation_weight", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], name="fk_zones_city_id_cities"),
        sa.PrimaryKeyConstraint("id", name="pk_zones"),
        sa.UniqueConstraint("city_id", "code", name="uq_zones_city_code"),
    )
    op.create_index("ix_zones_city_id", "zones", ["city_id"], unique=False)

    op.create_table(
        "integration_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("external_activity_id", sa.String(length=255), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_integration_jobs"),
        sa.UniqueConstraint(
            "provider",
            "request_hash",
            name="uq_integration_jobs_provider_request_hash",
        ),
    )
    op.create_index("ix_integration_jobs_status", "integration_jobs", ["status"], unique=False)
    op.create_index(
        "ix_integration_jobs_external_activity_id",
        "integration_jobs",
        ["external_activity_id"],
        unique=False,
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_integration_jobs_external_activity_id", table_name="integration_jobs")
    op.drop_index("ix_integration_jobs_status", table_name="integration_jobs")
    op.drop_table("integration_jobs")
    op.drop_index("ix_zones_city_id", table_name="zones")
    op.drop_table("zones")
    op.drop_index("ix_cities_name", table_name="cities")
    op.drop_table("cities")

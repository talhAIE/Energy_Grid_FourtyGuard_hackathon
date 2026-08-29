from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ModelVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A traceable city-level baseline demand-model artifact and its validation metrics."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("city_id", "version", name="uq_model_versions_city_version"),
    )

    city_id: Mapped[UUID] = mapped_column(ForeignKey("cities.id"), index=True)
    version: Mapped[str] = mapped_column(String(100))
    algorithm: Mapped[str] = mapped_column(String(100))
    feature_schema_version: Mapped[str] = mapped_column(String(30))
    feature_columns: Mapped[list[str]] = mapped_column(JSON)
    quality_policy: Mapped[str] = mapped_column(String(100))
    source_dataset_version: Mapped[str] = mapped_column(String(150))
    training_data_sha256: Mapped[str] = mapped_column(String(64))
    trained_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trained_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    training_row_count: Mapped[int] = mapped_column(Integer)
    validation_row_count: Mapped[int] = mapped_column(Integer)
    mae_mw: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    rmse_mw: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    mape_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    artifact_path: Mapped[str] = mapped_column(String(500))
    validation_predictions_path: Mapped[str] = mapped_column(String(500))
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

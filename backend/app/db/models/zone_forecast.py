from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ZoneForecast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A traceable, explicitly proxy demand/risk forecast for one zone and hour."""

    __tablename__ = "zone_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "zone_id",
            "model_version_id",
            "forecast_for",
            name="uq_zone_forecasts_zone_model_time",
        ),
    )

    zone_id: Mapped[UUID] = mapped_column(ForeignKey("zones.id"), index=True)
    model_version_id: Mapped[UUID] = mapped_column(ForeignKey("model_versions.id"), index=True)
    forecast_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    estimate_type: Mapped[str] = mapped_column(String(30), default="proxy")
    city_forecast_mw: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    allocation_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10))
    temperature_c: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    city_temperature_c: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    heat_anomaly_c: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    temperature_ramp_c_per_hour: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3), nullable=True
    )
    temperature_stddev_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    baseline_mw: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    predicted_mw: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    uplift_pct: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    uncertainty_penalty: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    risk_level: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[str] = mapped_column(String(20))
    data_freshness_status: Mapped[str] = mapped_column(String(20))
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSONB)

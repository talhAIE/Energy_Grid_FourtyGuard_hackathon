from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class ZoneTemperatureObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One normalized heatmap temperature result for a zone and source heatmap run."""

    __tablename__ = "zone_temperature_observations"
    __table_args__ = (
        UniqueConstraint(
            "zone_id",
            "source_run_id",
            name="uq_zone_temperature_observations_zone_run",
        ),
    )

    zone_id: Mapped[UUID] = mapped_column(ForeignKey("zones.id"), index=True)
    observed_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    mean_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    min_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    max_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    stddev_c: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    tile_count: Mapped[int] = mapped_column(Integer, default=0)
    source_run_id: Mapped[UUID] = mapped_column(ForeignKey("heatmap_runs.id"), index=True)
    is_forecast: Mapped[bool] = mapped_column(Boolean, default=False)
    data_status: Mapped[str] = mapped_column(String(30), default="available")
    source_retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

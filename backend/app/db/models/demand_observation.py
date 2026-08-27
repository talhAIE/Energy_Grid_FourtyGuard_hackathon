from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class DemandObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A normalized hourly electricity-demand observation from a traceable source."""

    __tablename__ = "demand_observations"
    __table_args__ = (
        UniqueConstraint(
            "city_id",
            "source",
            "source_area_code",
            "period_utc",
            name="uq_demand_observations_source_area_period",
        ),
    )

    city_id: Mapped[UUID] = mapped_column(ForeignKey("cities.id"), index=True)
    period_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(50))
    source_area_code: Mapped[str] = mapped_column(String(80))
    demand_mw: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    is_actual: Mapped[bool] = mapped_column(Boolean, default=True)
    quality_flag: Mapped[str | None] = mapped_column(String(100), nullable=True)

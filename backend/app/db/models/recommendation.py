from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Recommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A bounded proposed operator action; it never performs the action itself."""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("zone_forecast_id", name="uq_recommendations_zone_forecast_id"),
    )

    zone_forecast_id: Mapped[UUID] = mapped_column(ForeignKey("zone_forecasts.id"), index=True)
    action_code: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reason_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

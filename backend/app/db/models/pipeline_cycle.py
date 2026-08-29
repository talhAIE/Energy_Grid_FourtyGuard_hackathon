from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class PipelineCycle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable state for one manually advanced heatmap-to-recommendation pipeline cycle."""

    __tablename__ = "pipeline_cycles"
    __table_args__ = (
        UniqueConstraint("integration_job_id", name="uq_pipeline_cycles_integration_job_id"),
    )

    integration_job_id: Mapped[UUID] = mapped_column(ForeignKey("integration_jobs.id"), index=True)
    trigger_source: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), index=True)
    forecast_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_advanced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    data_freshness_status: Mapped[str] = mapped_column(String(20), default="unavailable")
    zone_forecast_count: Mapped[int] = mapped_column(Integer, default=0)
    recommendation_count: Mapped[int] = mapped_column(Integer, default=0)

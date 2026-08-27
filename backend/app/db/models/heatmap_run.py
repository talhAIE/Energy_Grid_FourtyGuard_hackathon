from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class HeatmapRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Safe, reproducible context for one FortyGuard heatmap submission."""

    __tablename__ = "heatmap_runs"
    __table_args__ = (UniqueConstraint("job_id", name="uq_heatmap_runs_job_id"),)

    job_id: Mapped[UUID] = mapped_column(ForeignKey("integration_jobs.id"), index=True)
    requested_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    granularity_m: Mapped[int] = mapped_column()
    analytic_type: Mapped[str] = mapped_column(String(40))
    aoi_geometry: Mapped[object] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    date_time_json: Mapped[dict[str, object]] = mapped_column(JSON)
    source_kind: Mapped[str] = mapped_column(String(30), default="live")

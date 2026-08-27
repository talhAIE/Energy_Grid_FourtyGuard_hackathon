from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks an asynchronous request to an external data provider."""

    __tablename__ = "integration_jobs"
    __table_args__ = (
        UniqueConstraint(
            "provider", "request_hash", name="uq_integration_jobs_provider_request_hash"
        ),
    )

    provider: Mapped[str] = mapped_column(String(50))
    operation: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), index=True)
    external_activity_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


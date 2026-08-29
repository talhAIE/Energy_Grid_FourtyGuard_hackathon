from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class RecommendationDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An immutable human response to one recommendation."""

    __tablename__ = "recommendation_decisions"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            name="uq_recommendation_decisions_recommendation_id",
        ),
    )

    recommendation_id: Mapped[UUID] = mapped_column(ForeignKey("recommendations.id"), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    operator_name: Mapped[str] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

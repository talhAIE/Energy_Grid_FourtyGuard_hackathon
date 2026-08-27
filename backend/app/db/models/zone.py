from decimal import Decimal
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class Zone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An operational zone used for heat and demand-risk calculations."""

    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("city_id", "code", name="uq_zones_city_code"),)

    city_id: Mapped[UUID] = mapped_column(ForeignKey("cities.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(50))
    geometry: Mapped[object] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    allocation_weight: Mapped[Decimal] = mapped_column(Numeric(12, 10), default=Decimal("0"))


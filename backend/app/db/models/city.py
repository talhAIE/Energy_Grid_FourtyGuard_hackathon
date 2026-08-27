from geoalchemy2 import Geometry
from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin, UUIDPrimaryKeyMixin


class City(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A configured demonstration city and its optional boundary."""

    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("name", "country_code", name="uq_cities_name_country"),)

    name: Mapped[str] = mapped_column(String(120), index=True)
    timezone: Mapped[str] = mapped_column(String(64))
    country_code: Mapped[str] = mapped_column(String(2), default="US")
    geometry: Mapped[object | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True
    )


import json
from pathlib import Path

from geoalchemy2.shape import from_shape
from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models.city import City
from app.services.zone_geometry import normalize_geojson_geometry

SEED_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"


def load_demo_boundary():
    """Load the version-controlled Houston demo analysis boundary."""
    boundary_path = SEED_DATA_DIR / "houston_demo_boundary.geojson"
    return normalize_geojson_geometry(json.loads(boundary_path.read_text(encoding="utf-8")))


def seed_city() -> None:
    """Create the configured demo city once and add its demo analysis boundary."""
    settings = get_settings()
    session_factory = get_session_factory()
    boundary = load_demo_boundary()

    with session_factory() as session:
        statement = select(City).where(
            City.name == settings.demo_city_name,
            City.country_code == "US",
        )
        city = session.scalar(statement)
        if city is None:
            session.add(
                City(
                    name=settings.demo_city_name,
                    timezone=settings.demo_timezone,
                    country_code="US",
                    geometry=from_shape(boundary.shape, srid=4326),
                )
            )
            session.commit()
            print(f"Created demo city: {settings.demo_city_name}")
            return

        if city.geometry is None:
            city.geometry = from_shape(boundary.shape, srid=4326)
            session.commit()
            print(f"Added demo boundary to city: {settings.demo_city_name}")
            return

        print(f"Demo city already exists: {settings.demo_city_name}")


if __name__ == "__main__":
    seed_city()

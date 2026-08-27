from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models.city import City


def seed_city() -> None:
    """Create the configured demo city once, without changing an existing record."""
    settings = get_settings()
    session_factory = get_session_factory()

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
                )
            )
            session.commit()
            print(f"Created demo city: {settings.demo_city_name}")
            return

        print(f"Demo city already exists: {settings.demo_city_name}")


if __name__ == "__main__":
    seed_city()


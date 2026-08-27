import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import get_session_factory
from app.db.models.city import City
from app.db.models.zone import Zone
from app.schemas.zones import ZoneCreate
from app.services.zone_service import ZoneConflictError, ZoneValidationError, create_zone

SEED_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"


def seed_zones() -> None:
    """Create the version-controlled Houston zones without duplicating existing codes."""
    zone_file = SEED_DATA_DIR / "houston_zones.geojson"
    feature_collection = json.loads(zone_file.read_text(encoding="utf-8"))
    features = feature_collection.get("features")
    if feature_collection.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("Houston seed data must be a GeoJSON FeatureCollection.")

    expected_weight = sum(
        (Decimal(str(feature["properties"]["allocation_weight"])) for feature in features),
        start=Decimal("0"),
    )
    if expected_weight != Decimal("1"):
        raise ValueError("Houston seed-zone allocation weights must sum to exactly 1.0.")

    settings = get_settings()
    session_factory = get_session_factory()
    created_count = 0

    with session_factory() as session:
        city = session.scalar(
            select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
        )
        if city is None or city.geometry is None:
            raise RuntimeError("Seed the configured demo city and boundary before seeding zones.")

        for feature in features:
            properties = feature.get("properties") or {}
            code = properties.get("code")
            if not isinstance(code, str):
                raise ValueError("Every seed zone requires a string code.")
            existing_zone = session.scalar(
                select(Zone).where(Zone.city_id == city.id, Zone.code == code)
            )
            if existing_zone is not None:
                continue

            payload = ZoneCreate(
                name=properties.get("name"),
                code=code,
                geometry=feature,
                allocation_weight=properties.get("allocation_weight"),
                active=True,
            )
            try:
                create_zone(session=session, payload=payload)
            except (ZoneConflictError, ZoneValidationError) as exc:
                session.rollback()
                raise RuntimeError(f"Failed to seed zone '{code}': {exc}") from exc
            created_count += 1

        stored_weight = sum(
            (
                Decimal(weight)
                for weight in session.scalars(
                    select(Zone.allocation_weight).where(
                        Zone.city_id == city.id,
                        Zone.active.is_(True),
                    )
                ).all()
            ),
            start=Decimal("0"),
        )
        if stored_weight != Decimal("1"):
            raise RuntimeError(
                "Active zone allocation weights must total 1.0 after seeding; "
                f"found {stored_weight}."
            )

    print(f"Created {created_count} zone(s).")


if __name__ == "__main__":
    seed_zones()

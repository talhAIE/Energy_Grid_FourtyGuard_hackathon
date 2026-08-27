from decimal import Decimal

from geoalchemy2.shape import from_shape, to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.city import City
from app.db.models.zone import Zone
from app.schemas.zones import ZoneCreate, ZoneData
from app.services.audit_service import record_audit_event
from app.services.zone_geometry import (
    ZoneGeometryError,
    geometry_overlap_area,
    normalize_geojson_geometry,
)

OVERLAP_TOLERANCE = 1e-12


class ZoneValidationError(ValueError):
    """Raised when a zone violates the product's zone validation rules."""


class ZoneConflictError(ValueError):
    """Raised when a zone duplicates a code or overlaps an existing zone."""


class ZoneNotReadyError(RuntimeError):
    """Raised when the configured demo city/boundary does not exist yet."""


def list_zones(*, session: Session, active_only: bool) -> list[ZoneData]:
    """Return configured zones in a predictable map-friendly order."""
    city = _get_demo_city(session)
    statement = select(Zone).where(Zone.city_id == city.id).order_by(Zone.code)
    if active_only:
        statement = statement.where(Zone.active.is_(True))
    return [_to_zone_data(zone) for zone in session.scalars(statement).all()]


def create_zone(*, session: Session, payload: ZoneCreate) -> ZoneData:
    """Validate, persist, and audit a new zone for the configured demo city."""
    city = _get_demo_city(session)
    if city.geometry is None:
        raise ZoneNotReadyError("The demo city boundary is not seeded yet.")

    try:
        candidate = normalize_geojson_geometry(payload.geometry)
    except ZoneGeometryError as exc:
        raise ZoneValidationError(str(exc)) from exc

    city_boundary = to_shape(city.geometry)
    if not city_boundary.covers(candidate.shape):
        raise ZoneValidationError(
            "Zone geometry must fall inside the configured demo analysis boundary."
        )

    duplicate_code = session.scalar(
        select(Zone).where(Zone.city_id == city.id, Zone.code == payload.code)
    )
    if duplicate_code is not None:
        raise ZoneConflictError(f"Zone code '{payload.code}' already exists for this city.")

    existing_zones = session.scalars(select(Zone).where(Zone.city_id == city.id)).all()
    for existing_zone in existing_zones:
        overlap_area = geometry_overlap_area(candidate.shape, to_shape(existing_zone.geometry))
        if overlap_area > OVERLAP_TOLERANCE:
            raise ZoneConflictError(f"Zone overlaps existing zone '{existing_zone.code}'.")

    added_weight = payload.allocation_weight if payload.active else Decimal("0")
    proposed_weight = _active_weight_total(session, city_id=city.id) + added_weight
    if proposed_weight > Decimal("1"):
        raise ZoneValidationError("Active zone allocation weights cannot exceed 1.0.")

    zone = Zone(
        city_id=city.id,
        name=payload.name.strip(),
        code=payload.code,
        geometry=from_shape(candidate.shape, srid=4326),
        active=payload.active,
        allocation_weight=payload.allocation_weight,
    )
    session.add(zone)
    session.flush()
    record_audit_event(
        session,
        event_type="zone.created",
        entity_type="zone",
        entity_id=zone.id,
        payload={
            "code": zone.code,
            "name": zone.name,
            "allocation_weight": str(zone.allocation_weight),
        },
    )
    session.commit()
    session.refresh(zone)
    return _to_zone_data(zone)


def _get_demo_city(session: Session) -> City:
    settings = get_settings()
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None:
        raise ZoneNotReadyError("The configured demo city is not seeded yet.")
    return city


def _active_weight_total(session: Session, *, city_id) -> Decimal:
    statement = select(Zone.allocation_weight).where(
        Zone.city_id == city_id,
        Zone.active.is_(True),
    )
    active_weights = session.scalars(statement).all()
    return sum((Decimal(weight) for weight in active_weights), start=Decimal("0"))


def _to_zone_data(zone: Zone) -> ZoneData:
    geometry = normalize_geojson_geometry(to_shape(zone.geometry).__geo_interface__).geojson
    return ZoneData(
        id=zone.id,
        city_id=zone.city_id,
        name=zone.name,
        code=zone.code,
        geometry=geometry,
        active=zone.active,
        allocation_weight=zone.allocation_weight,
    )

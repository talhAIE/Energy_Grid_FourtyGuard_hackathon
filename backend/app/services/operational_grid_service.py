"""Create approved, provider-sized operational planning cells inside the demo boundary."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import box
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.city import City
from app.db.models.zone import Zone
from app.services.audit_service import record_audit_event
from app.services.heatmap_submission_geometry import normalize_heatmap_aoi
from app.services.zone_geometry import normalize_geojson_geometry

MIN_ZONE_COUNT = 4
MAX_ZONE_COUNT = 12


class OperationalGridError(ValueError):
    """Raised when a requested planning grid is not safe for the configured provider."""


@dataclass(frozen=True)
class OperationalGridResult:
    active_zone_count: int
    deactivated_zone_count: int
    columns: int
    rows: int


def activate_operational_grid(
    session: Session, *, columns: int, rows: int
) -> OperationalGridResult:
    """Replace active zones with a non-overlapping, provider-size-validated planning grid.

    Existing zones are retained as inactive records to preserve prior forecasts and audit history.
    This function never submits a provider request or runs a forecast.
    """
    requested_count = columns * rows
    if not MIN_ZONE_COUNT <= requested_count <= MAX_ZONE_COUNT:
        raise OperationalGridError(
            f"The operational plan must contain {MIN_ZONE_COUNT} to {MAX_ZONE_COUNT} zones."
        )

    settings = get_settings()
    city = session.scalar(
        select(City).where(
            City.name == settings.demo_city_name,
            City.country_code == "US",
        )
    )
    if city is None or city.geometry is None:
        raise OperationalGridError("The demo city boundary is not available.")

    boundary = to_shape(city.geometry)
    min_x, min_y, max_x, max_y = boundary.bounds
    cell_width = (max_x - min_x) / columns
    cell_height = (max_y - min_y) / rows
    cells = []
    for row in range(rows):
        for column in range(columns):
            candidate = boundary.intersection(
                box(
                    min_x + column * cell_width,
                    min_y + row * cell_height,
                    min_x + (column + 1) * cell_width,
                    min_y + (row + 1) * cell_height,
                )
            )
            if candidate.is_empty:
                continue
            normalized = normalize_geojson_geometry(candidate.__geo_interface__)
            _validate_provider_area(candidate.__geo_interface__)
            cells.append((row, column, normalized))

    if len(cells) != requested_count:
        raise OperationalGridError(
            "The approved boundary cannot create the requested number of non-empty grid zones."
        )

    existing = session.scalars(select(Zone).where(Zone.city_id == city.id)).all()
    existing_by_code = {zone.code: zone for zone in existing}
    active_existing = [zone for zone in existing if zone.active]
    for zone in active_existing:
        zone.active = False

    base_weight = (Decimal("1") / Decimal(len(cells))).quantize(
        Decimal("0.0000000001"), rounding=ROUND_DOWN
    )
    last_weight = Decimal("1") - base_weight * (len(cells) - 1)
    for index, (row, column, normalized) in enumerate(cells, start=1):
        code = f"GRID_{columns}X{rows}_R{row + 1:02d}_C{column + 1:02d}"
        zone = existing_by_code.get(code)
        if zone is None:
            session.add(
                Zone(
                    city_id=city.id,
                    name=_grid_name(row=row, column=column, rows=rows, columns=columns),
                    code=code,
                    geometry=from_shape(normalized.shape, srid=4326),
                    active=True,
                    allocation_weight=last_weight if index == len(cells) else base_weight,
                )
            )
            continue
        zone.name = _grid_name(row=row, column=column, rows=rows, columns=columns)
        zone.geometry = from_shape(normalized.shape, srid=4326)
        zone.active = True
        zone.allocation_weight = last_weight if index == len(cells) else base_weight
    session.flush()
    record_audit_event(
        session,
        event_type="zone_plan.activated",
        entity_type="city",
        entity_id=city.id,
        payload={
            "plan_type": "approved_operational_grid",
            "columns": columns,
            "rows": rows,
            "active_zone_count": len(cells),
            "deactivated_zone_count": len(active_existing),
            "provider_area_validated": True,
        },
    )
    session.commit()
    return OperationalGridResult(
        active_zone_count=len(cells),
        deactivated_zone_count=len(active_existing),
        columns=columns,
        rows=rows,
    )


def _validate_provider_area(geometry: dict) -> None:
    feature_collection = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": geometry}],
    }
    try:
        normalize_heatmap_aoi(feature_collection)
    except ValueError as exc:
        raise OperationalGridError(
            "A generated zone exceeds the configured FortyGuard sampling boundary."
        ) from exc


def _grid_name(*, row: int, column: int, rows: int, columns: int) -> str:
    vertical = ("South", "South-central", "Central", "North-central", "North")[
        min(4, row * 5 // rows)
    ]
    horizontal = ("West", "West-inner", "Central-west", "Central-east", "East-inner", "East")[
        min(5, column * 6 // columns)
    ]
    return f"{vertical} {horizontal} planning cell"

"""Normalize completed FortyGuard thermal tiles into zone temperature observations."""

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from geoalchemy2.shape import to_shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.heatmap_run import HeatmapRun
from app.db.models.integration_job import IntegrationJob
from app.db.models.zone import Zone
from app.db.models.zone_temperature_observation import ZoneTemperatureObservation
from app.schemas.temperatures import ZoneTemperatureData
from app.services.audit_service import record_audit_event
from app.services.zone_geometry import ZoneGeometryError, normalize_geojson_geometry

TEMPERATURE_PROPERTY_NAMES = (
    "temperature_c",
    "temperature",
    "temp_c",
    "temp",
    "tcm",
    "value",
)
GEOMETRY_OVERLAP_EPSILON = 1e-12
TEMPERATURE_SCALE = Decimal("0.001")


class HeatmapNormalizationError(ValueError):
    """Raised when a completed provider payload cannot safely become temperature observations."""


@dataclass(frozen=True)
class HeatmapTile:
    """One validated thermal tile and its Celsius temperature value."""

    geometry: BaseGeometry
    temperature_c: Decimal


@dataclass(frozen=True)
class NormalizationResult:
    """Safe summary of one completed run's aggregation outcome."""

    source_run_id: UUID
    available_zone_count: int
    missing_zone_count: int
    no_overlap: bool
    reused: bool


def normalize_completed_heatmap(
    session: Session,
    *,
    job: IntegrationJob,
    provider_response: dict[str, Any],
    execution_time: datetime,
) -> NormalizationResult:
    """Aggregate one completed heatmap using centroid assignment without committing the session."""
    heatmap_run = session.scalar(select(HeatmapRun).where(HeatmapRun.job_id == job.id))
    if heatmap_run is None:
        raise HeatmapNormalizationError("Completed heatmap job has no stored heatmap run.")

    existing = session.scalars(
        select(ZoneTemperatureObservation).where(
            ZoneTemperatureObservation.source_run_id == heatmap_run.id
        )
    ).all()
    if existing:
        return NormalizationResult(
            source_run_id=heatmap_run.id,
            available_zone_count=sum(item.data_status == "available" for item in existing),
            missing_zone_count=sum(item.data_status == "missing" for item in existing),
            no_overlap=False,
            reused=True,
        )

    tiles = parse_temperature_tiles(provider_response)
    run_aoi = to_shape(heatmap_run.aoi_geometry)
    zones = _overlapping_active_zones(session=session, run_aoi=run_aoi)
    if not zones:
        record_audit_event(
            session,
            event_type="heatmap.normalized_no_overlap",
            entity_type="integration_job",
            entity_id=job.id,
            payload={"source_run_id": str(heatmap_run.id), "tile_count": len(tiles)},
        )
        return NormalizationResult(
            source_run_id=heatmap_run.id,
            available_zone_count=0,
            missing_zone_count=0,
            no_overlap=True,
            reused=False,
        )

    temperatures_by_zone: dict[UUID, list[Decimal]] = {zone.id: [] for zone, _ in zones}
    for tile in tiles:
        matched_zones = [
            (zone, geometry)
            for zone, geometry in zones
            if geometry.covers(tile.geometry.centroid)
        ]
        if matched_zones:
            selected_zone, _ = min(matched_zones, key=lambda pair: pair[0].code)
            temperatures_by_zone[selected_zone.id].append(tile.temperature_c)

    is_forecast = heatmap_run.requested_time > execution_time
    available_count = 0
    missing_count = 0
    for zone, _ in zones:
        values = temperatures_by_zone[zone.id]
        if values:
            mean_c, min_c, max_c, stddev_c = _temperature_statistics(values)
            data_status = "available"
            available_count += 1
        else:
            mean_c = min_c = max_c = stddev_c = None
            data_status = "missing"
            missing_count += 1
        session.add(
            ZoneTemperatureObservation(
                zone_id=zone.id,
                observed_for=heatmap_run.requested_time,
                mean_c=mean_c,
                min_c=min_c,
                max_c=max_c,
                stddev_c=stddev_c,
                tile_count=len(values),
                source_run_id=heatmap_run.id,
                is_forecast=is_forecast,
                data_status=data_status,
                source_retrieved_at=execution_time,
            )
        )
    session.flush()
    record_audit_event(
        session,
        event_type="heatmap.normalized",
        entity_type="integration_job",
        entity_id=job.id,
        payload={
            "source_run_id": str(heatmap_run.id),
            "tile_count": len(tiles),
            "available_zone_count": available_count,
            "missing_zone_count": missing_count,
            "assignment_method": "tile_centroid",
        },
    )
    return NormalizationResult(
        source_run_id=heatmap_run.id,
        available_zone_count=available_count,
        missing_zone_count=missing_count,
        no_overlap=False,
        reused=False,
    )


def parse_temperature_tiles(provider_response: dict[str, Any]) -> list[HeatmapTile]:
    """Extract a valid FeatureCollection and Celsius-valued tiles from a completed response."""
    map_data = _extract_map_data(provider_response)
    if map_data.get("type") != "FeatureCollection":
        raise HeatmapNormalizationError(
            "Completed heatmap map_data must be a GeoJSON FeatureCollection."
        )
    features = map_data.get("features")
    if not isinstance(features, list):
        raise HeatmapNormalizationError("Completed heatmap map_data must include a features list.")

    tiles: list[HeatmapTile] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise HeatmapNormalizationError(f"Heatmap tile {index} is not a GeoJSON Feature.")
        try:
            geometry = normalize_geojson_geometry(feature).shape
        except ZoneGeometryError as exc:
            raise HeatmapNormalizationError(f"Heatmap tile {index} has invalid geometry.") from exc
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise HeatmapNormalizationError(f"Heatmap tile {index} has no properties object.")
        tiles.append(
            HeatmapTile(
                geometry=geometry,
                temperature_c=_extract_temperature(properties=properties, index=index),
            )
        )
    return tiles


def list_zone_temperatures(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    zone_id: UUID | None = None,
    include_missing: bool = True,
) -> list[ZoneTemperatureData]:
    """Return a chronological, bounded zone temperature timeline from persisted observations."""
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    if end_utc <= start_utc:
        raise HeatmapNormalizationError("End time must be later than start time.")

    statement = (
        select(ZoneTemperatureObservation)
        .where(
            ZoneTemperatureObservation.observed_for >= start_utc,
            ZoneTemperatureObservation.observed_for <= end_utc,
        )
        .order_by(ZoneTemperatureObservation.observed_for, ZoneTemperatureObservation.zone_id)
    )
    if zone_id is not None:
        statement = statement.where(ZoneTemperatureObservation.zone_id == zone_id)
    if not include_missing:
        statement = statement.where(ZoneTemperatureObservation.data_status == "available")
    observations = session.scalars(statement).all()
    return [_to_temperature_data(observation) for observation in observations]


def _extract_map_data(provider_response: dict[str, Any]) -> dict[str, Any]:
    try:
        data = provider_response["data"]
        result = data["result"] if isinstance(data, dict) else None
        map_data = result["map_data"] if isinstance(result, dict) else None
    except (KeyError, TypeError) as exc:
        raise HeatmapNormalizationError(
            "Completed heatmap response has no map_data result."
        ) from exc
    if isinstance(map_data, str):
        try:
            map_data = json.loads(map_data)
        except json.JSONDecodeError as exc:
            raise HeatmapNormalizationError(
                "Completed heatmap map_data is not valid JSON."
            ) from exc
    if not isinstance(map_data, dict):
        raise HeatmapNormalizationError("Completed heatmap map_data is not a GeoJSON object.")
    return map_data


def _extract_temperature(*, properties: dict[str, Any], index: int) -> Decimal:
    for name in TEMPERATURE_PROPERTY_NAMES:
        if name not in properties:
            continue
        try:
            value = Decimal(str(properties[name]))
        except (InvalidOperation, ValueError) as exc:
            raise HeatmapNormalizationError(
                f"Heatmap tile {index} has an invalid {name} temperature value."
            ) from exc
        if not value.is_finite() or not math.isfinite(float(value)):
            raise HeatmapNormalizationError(
                f"Heatmap tile {index} has an invalid temperature value."
            )
        return value
    raise HeatmapNormalizationError(
        f"Heatmap tile {index} has no supported Celsius property "
        f"({', '.join(TEMPERATURE_PROPERTY_NAMES)})."
    )


def _overlapping_active_zones(
    *, session: Session, run_aoi: BaseGeometry
) -> list[tuple[Zone, BaseGeometry]]:
    candidates = session.scalars(
        select(Zone).where(Zone.active.is_(True)).order_by(Zone.code)
    ).all()
    overlapping: list[tuple[Zone, BaseGeometry]] = []
    for zone in candidates:
        geometry = to_shape(zone.geometry)
        if geometry.intersection(run_aoi).area > GEOMETRY_OVERLAP_EPSILON:
            overlapping.append((zone, geometry))
    return overlapping


def _temperature_statistics(
    values: list[Decimal],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    count = Decimal(len(values))
    mean = sum(values, start=Decimal("0")) / count
    variance = sum(((value - mean) ** 2 for value in values), start=Decimal("0")) / count
    stddev = variance.sqrt() if len(values) > 1 else Decimal("0")
    return (
        mean.quantize(TEMPERATURE_SCALE, rounding=ROUND_HALF_UP),
        min(values).quantize(TEMPERATURE_SCALE, rounding=ROUND_HALF_UP),
        max(values).quantize(TEMPERATURE_SCALE, rounding=ROUND_HALF_UP),
        stddev.quantize(TEMPERATURE_SCALE, rounding=ROUND_HALF_UP),
    )


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_temperature_data(observation: ZoneTemperatureObservation) -> ZoneTemperatureData:
    return ZoneTemperatureData(
        id=observation.id,
        zone_id=observation.zone_id,
        observed_for=observation.observed_for,
        mean_c=observation.mean_c,
        min_c=observation.min_c,
        max_c=observation.max_c,
        stddev_c=observation.stddev_c,
        tile_count=observation.tile_count,
        source_run_id=observation.source_run_id,
        is_forecast=observation.is_forecast,
        data_status=observation.data_status,
        source_retrieved_at=observation.source_retrieved_at,
    )

"""Validation and safe normalization for FortyGuard heatmap AOIs."""

import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon, box, mapping

from app.services.zone_geometry import (
    NormalizedGeometry,
    ZoneGeometryError,
    normalize_geojson_geometry,
)

EARTH_RADIUS_M = 6_371_008.8
SQUARE_METERS_PER_SQUARE_MILE = 2_589_988.110336
US_REGIONS = (
    box(-125.0, 24.0, -66.0, 50.0),  # Continental United States
    box(-170.0, 51.0, -129.0, 72.0),  # Alaska
    box(-161.0, 18.0, -154.0, 23.0),  # Hawaii
    box(-68.0, 17.0, -64.0, 19.0),  # Puerto Rico / U.S. Virgin Islands
)


class HeatmapGeometryError(ValueError):
    """Raised when an AOI is invalid or outside the supported demo area."""


@dataclass(frozen=True)
class NormalizedHeatmapAoi:
    """A valid single-polygon AOI in provider and database-friendly shapes."""

    normalized_geometry: NormalizedGeometry
    provider_geojson: dict[str, Any]
    area_sq_mi: float


def normalize_heatmap_aoi(value: dict[str, Any]) -> NormalizedHeatmapAoi:
    """Require one closed Polygon Feature inside an approximate supported U.S. envelope."""
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise HeatmapGeometryError("polygon_aoi must be a GeoJSON FeatureCollection.")
    features = value.get("features")
    if not isinstance(features, list) or len(features) != 1:
        raise HeatmapGeometryError("polygon_aoi must contain exactly one Polygon feature.")
    feature = features[0]
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise HeatmapGeometryError("polygon_aoi must contain a GeoJSON Feature.")
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise HeatmapGeometryError("polygon_aoi must contain one Polygon geometry.")

    try:
        normalized = normalize_geojson_geometry(feature)
    except ZoneGeometryError as exc:
        raise HeatmapGeometryError(str(exc)) from exc

    polygon = normalized.shape.geoms[0]
    if not any(region.covers(polygon) for region in US_REGIONS):
        raise HeatmapGeometryError("The heatmap AOI must be within a supported U.S. region.")

    area_sq_mi = _polygon_area_sq_mi(polygon)
    if area_sq_mi <= 0:
        raise HeatmapGeometryError("The heatmap AOI must have a positive area.")

    return NormalizedHeatmapAoi(
        normalized_geometry=normalized,
        provider_geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": mapping(polygon),
                }
            ],
        },
        area_sq_mi=area_sq_mi,
    )


def _polygon_area_sq_mi(polygon: Polygon) -> float:
    """Estimate a small WGS84 polygon's area with a local equal-distance projection."""
    reference_latitude_radians = math.radians(polygon.centroid.y)

    def ring_area_square_meters(coordinates: Any) -> float:
        projected = [
            (
                EARTH_RADIUS_M * math.radians(longitude) * math.cos(reference_latitude_radians),
                EARTH_RADIUS_M * math.radians(latitude),
            )
            for longitude, latitude, *_ in coordinates
        ]
        return abs(
            sum(
                (x1 * y2) - (x2 * y1)
                for (x1, y1), (x2, y2) in zip(projected, projected[1:])
            )
            / 2
        )

    area_square_meters = ring_area_square_meters(polygon.exterior.coords)
    area_square_meters -= sum(ring_area_square_meters(ring.coords) for ring in polygon.interiors)
    return area_square_meters / SQUARE_METERS_PER_SQUARE_MILE

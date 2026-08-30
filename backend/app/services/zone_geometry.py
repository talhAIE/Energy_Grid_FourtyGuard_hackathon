import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry


class ZoneGeometryError(ValueError):
    """Raised when supplied GeoJSON cannot safely represent an operational zone."""


@dataclass(frozen=True)
class NormalizedGeometry:
    """A validated WGS84 multipolygon and its canonical GeoJSON representation."""

    shape: MultiPolygon
    geojson: dict[str, Any]


def normalize_geojson_geometry(value: dict[str, Any]) -> NormalizedGeometry:
    """Validate GeoJSON Feature/Polygon/MultiPolygon and normalize to MultiPolygon."""
    geometry = _extract_geometry(value)
    _validate_coordinates(geometry)

    try:
        candidate = shape(geometry)
    except (TypeError, ValueError) as exc:
        raise ZoneGeometryError("Geometry is not valid GeoJSON.") from exc

    if isinstance(candidate, Polygon):
        candidate = MultiPolygon([candidate])
    if not isinstance(candidate, MultiPolygon):
        raise ZoneGeometryError("Geometry must be a Polygon or MultiPolygon.")
    if candidate.is_empty or not candidate.is_valid:
        raise ZoneGeometryError("Geometry is empty, self-intersecting, or otherwise invalid.")

    return NormalizedGeometry(shape=candidate, geojson=mapping(candidate))


def _extract_geometry(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ZoneGeometryError("Geometry must be a GeoJSON object.")
    geometry = value.get("geometry") if value.get("type") == "Feature" else value
    if not isinstance(geometry, dict):
        raise ZoneGeometryError("GeoJSON Feature must include a geometry object.")
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ZoneGeometryError("Geometry type must be Polygon or MultiPolygon.")
    return geometry


def _validate_coordinates(geometry: dict[str, Any]) -> None:
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list | tuple) or not coordinates:
        raise ZoneGeometryError("Geometry coordinates are required.")

    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    for polygon in polygons:
        if not isinstance(polygon, list | tuple) or not polygon:
            raise ZoneGeometryError("Each polygon must include at least one linear ring.")
        for ring in polygon:
            if not isinstance(ring, list | tuple) or len(ring) < 4:
                raise ZoneGeometryError("Each linear ring must contain at least four positions.")
            if ring[0] != ring[-1]:
                raise ZoneGeometryError(
                    "Each linear ring must be closed (first position equals last)."
                )
            for position in ring:
                _validate_position(position)


def _validate_position(position: Any) -> None:
    if not isinstance(position, list | tuple) or len(position) < 2:
        raise ZoneGeometryError("Each coordinate position must contain longitude and latitude.")
    longitude, latitude = position[0], position[1]
    if isinstance(longitude, bool) or isinstance(latitude, bool):
        raise ZoneGeometryError("Longitude and latitude must be numeric values.")
    try:
        longitude = float(longitude)
        latitude = float(latitude)
    except (TypeError, ValueError) as exc:
        raise ZoneGeometryError("Longitude and latitude must be numeric values.") from exc
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ZoneGeometryError("Longitude and latitude must be finite values.")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ZoneGeometryError("Coordinates fall outside valid longitude/latitude ranges.")


def geometry_overlap_area(left: BaseGeometry, right: BaseGeometry) -> float:
    """Return overlap area in degree units for small demo-zone conflict checks."""
    return left.intersection(right).area

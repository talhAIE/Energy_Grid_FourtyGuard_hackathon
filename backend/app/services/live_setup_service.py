"""Prepare a bounded, all-zone live sample set for the dashboard."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from geoalchemy2.shape import to_shape
from shapely.geometry import box, mapping
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.demand_observation import DemandObservation
from app.db.models.zone import Zone
from app.schemas.heatmaps import HeatmapDateTime, HeatmapJobData, HeatmapSubmitRequest
from app.services.forecast_model_service import (
    ModelNotAvailableError,
    bootstrap_demand_history_model,
    get_active_model_summary,
)
from app.services.heatmap_submission_service import submit_heatmap

SAMPLE_HALF_WIDTH_DEGREES = 0.006
MIN_SAMPLE_HALF_WIDTH_DEGREES = 0.00025


class LiveSetupError(ValueError):
    """Raised when the database does not yet have enough safe live inputs."""


@dataclass(frozen=True)
class LiveZoneSample:
    zone_id: str
    zone_code: str
    zone_name: str
    job: HeatmapJobData


@dataclass(frozen=True)
class LiveSetupResult:
    forecast_for: datetime
    model_version: str
    model_quality_policy: str
    model_reused: bool
    samples: list[LiveZoneSample]


def prepare_live_dashboard(
    session: Session, *, settings: Settings | None = None
) -> LiveSetupResult:
    """Activate a demand-history bootstrap if needed and submit one tiny sample per zone.

    Each request is restricted to a box contained within its operational zone.  The
    provider returns a temperature proxy for that small sample; it is not treated
    as a feeder measurement or a full-zone temperature census.
    """
    settings = settings or get_settings()
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None:
        raise LiveSetupError("The configured city is missing. Seed the city before live setup.")
    target_time = _next_forecast_time(session=session, city=city, settings=settings)
    try:
        active_model = get_active_model_summary(session=session, settings=settings)
        model_reused = True
    except ModelNotAvailableError:
        bootstrap = bootstrap_demand_history_model(session=session, settings=settings)
        active_model = get_active_model_summary(session=session, settings=settings)
        model_reused = bootstrap.reused_existing_version
    zones = session.scalars(
        select(Zone)
        .where(Zone.city_id == city.id, Zone.active.is_(True))
        .order_by(Zone.code)
    ).all()
    if not zones:
        raise LiveSetupError("No active operational zones are configured.")
    samples = [
        LiveZoneSample(
            zone_id=str(zone.id),
            zone_code=zone.code,
            zone_name=zone.name,
            job=submit_heatmap(
                session=session,
                settings=settings,
                payload=HeatmapSubmitRequest(
                    polygon_aoi=_sample_aoi(zone),
                    date_time=HeatmapDateTime(
                        start_date=target_time.date(),
                        start_time=target_time.timetz().replace(tzinfo=None),
                        filter_type=1,
                    ),
                    granularity=100,
                    analytic_type="tcm",
                ),
            ),
        )
        for zone in zones
    ]
    return LiveSetupResult(
        forecast_for=target_time,
        model_version=active_model.version,
        model_quality_policy=active_model.quality_policy,
        model_reused=model_reused,
        samples=samples,
    )


def _next_forecast_time(*, session: Session, city: City, settings: Settings) -> datetime:
    latest = session.scalar(
        select(func.max(DemandObservation.period_utc)).where(
            DemandObservation.city_id == city.id,
            DemandObservation.is_actual.is_(True),
        )
    )
    if latest is None:
        raise LiveSetupError("Import live EIA demand history before starting the dashboard.")
    latest_utc = latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest.astimezone(UTC)
    target = latest_utc + timedelta(hours=1)
    if target > datetime.now(UTC) + timedelta(hours=settings.fortyguard_max_forecast_hours):
        raise LiveSetupError(
            "The latest EIA demand record is too far ahead for the live provider window."
        )
    return target.replace(minute=0, second=0, microsecond=0)


def _sample_aoi(zone: Zone) -> dict[str, object]:
    shape = to_shape(zone.geometry)
    point = shape.representative_point()
    half_width = SAMPLE_HALF_WIDTH_DEGREES
    while half_width >= MIN_SAMPLE_HALF_WIDTH_DEGREES:
        candidate = box(
            point.x - half_width,
            point.y - half_width,
            point.x + half_width,
            point.y + half_width,
        )
        if shape.covers(candidate):
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"source": f"live_zone_sample_{zone.code}"},
                        "geometry": mapping(candidate),
                    }
                ],
            }
        half_width /= 2
    raise LiveSetupError(f"Zone {zone.code} has no usable interior area for a safe live sample.")

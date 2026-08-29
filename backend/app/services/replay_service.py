"""Load a deterministic, scrubbed Houston fallback scenario without external network calls."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from geoalchemy2.shape import from_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.demand_observation import DemandObservation
from app.db.models.heatmap_run import HeatmapRun
from app.db.models.integration_job import IntegrationJob
from app.db.models.model_version import ModelVersion
from app.db.models.pipeline_cycle import PipelineCycle
from app.db.models.zone import Zone
from app.db.models.zone_forecast import ZoneForecast
from app.db.models.zone_temperature_observation import ZoneTemperatureObservation
from app.services.audit_service import record_audit_event
from app.services.forecast_model_service import ALGORITHM, FEATURE_COLUMNS, QUALITY_POLICY
from app.services.recommendation_service import (
    RecommendationGenerationResult,
    generate_recommendations,
)
from app.services.zone_geometry import normalize_geojson_geometry

REPLAY_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "replay"
SEED_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"
FIXTURE_NAME = "houston_watch_to_critical.json"
REPLAY_MODEL_VERSION = "replay-houston-baseline-v1"
REPLAY_SOURCE = "REPLAY"
REPLAY_AREA_CODE = "HOUSTON_DEMO"


class ReplayModeError(ValueError):
    """Raised when the offline scenario cannot be loaded safely in the current configuration."""


@dataclass(frozen=True)
class ReplayLoadResult:
    cycle: PipelineCycle
    job: IntegrationJob
    zone_forecast_count: int
    recommendation_result: RecommendationGenerationResult
    reused: bool
    scenario: str


def load_replay(session: Session, *, settings: Settings | None = None) -> ReplayLoadResult:
    """Persist the replay fixture through normal models, with no provider or EIA request."""
    settings = settings or get_settings()
    if not settings.replay_mode:
        raise ReplayModeError("Set REPLAY_MODE=true before loading the offline scenario.")
    fixture = _load_fixture()
    base_time = _next_hour(datetime.now(UTC))
    city = _ensure_city(session=session, settings=settings)
    zones = _ensure_zones(session=session, city=city)
    model = _ensure_replay_model(session=session, city=city, settings=settings, base_time=base_time)
    all_forecasts: list[ZoneForecast] = []
    final_job: IntegrationJob | None = None
    final_run: HeatmapRun | None = None

    for item in fixture["hours"]:
        slot = base_time + timedelta(hours=int(item["offset"]))
        _ensure_replay_demand_history(session=session, city=city, slot=slot)
        job, heatmap_run = _ensure_replay_heatmap_run(
            session=session,
            city=city,
            slot=slot,
            fixture_version=fixture["fixture_version"],
        )
        forecasts = _ensure_hourly_replay_outputs(
            session=session,
            zones=zones,
            model=model,
            heatmap_run=heatmap_run,
            slot=slot,
            hour=item,
            retrieved_at=base_time,
        )
        all_forecasts.extend(forecasts)
        final_job, final_run = job, heatmap_run

    assert final_job is not None and final_run is not None
    final_forecasts = [
        forecast for forecast in all_forecasts if forecast.forecast_for == final_run.requested_time
    ]
    recommendation_result = generate_recommendations(
        session=session,
        zone_forecasts=final_forecasts,
        settings=settings,
    )
    cycle, reused = _ensure_completed_replay_cycle(
        session=session,
        job=final_job,
        forecast_for=final_run.requested_time,
        zone_forecast_count=len(final_forecasts),
        recommendation_count=recommendation_result.created_count,
    )
    record_audit_event(
        session,
        event_type="replay.loaded",
        entity_type="pipeline_cycle",
        entity_id=cycle.id,
        payload={
            "fixture_name": FIXTURE_NAME,
            "fixture_version": fixture["fixture_version"],
            "scenario": fixture["scenario"],
            "zone_forecast_count": len(all_forecasts),
            "network_calls": 0,
        },
    )
    session.commit()
    session.refresh(cycle)
    session.refresh(final_job)
    return ReplayLoadResult(
        cycle=cycle,
        job=final_job,
        zone_forecast_count=len(all_forecasts),
        recommendation_result=recommendation_result,
        reused=reused,
        scenario=fixture["scenario"],
    )


def run_replay_cycle(session: Session, *, settings: Settings | None = None) -> ReplayLoadResult:
    """Load/reuse the fixture and record a local advance without any external request."""
    result = load_replay(session=session, settings=settings)
    result.cycle.last_advanced_at = datetime.now(UTC)
    record_audit_event(
        session,
        event_type="replay.cycle_run",
        entity_type="pipeline_cycle",
        entity_id=result.cycle.id,
        payload={"network_calls": 0, "scenario": result.scenario},
    )
    session.commit()
    session.refresh(result.cycle)
    return result


def _load_fixture() -> dict[str, Any]:
    try:
        fixture = json.loads((REPLAY_DATA_DIR / FIXTURE_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayModeError("The scrubbed replay fixture is unavailable or unreadable.") from exc
    hours = fixture.get("hours")
    if (
        fixture.get("fixture_version") != "1"
        or not isinstance(fixture.get("scenario"), str)
        or not isinstance(hours, list)
        or len(hours) != 12
    ):
        raise ReplayModeError(
            "The replay fixture does not meet the expected 12-hour scenario contract."
        )
    return fixture


def _ensure_city(*, session: Session, settings: Settings) -> City:
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    boundary = normalize_geojson_geometry(
        json.loads((SEED_DATA_DIR / "houston_demo_boundary.geojson").read_text(encoding="utf-8"))
    )
    if city is None:
        city = City(
            name=settings.demo_city_name,
            timezone=settings.demo_timezone,
            country_code="US",
            geometry=from_shape(boundary.shape, srid=4326),
        )
        session.add(city)
        session.flush()
    elif city.geometry is None:
        city.geometry = from_shape(boundary.shape, srid=4326)
        session.flush()
    return city


def _ensure_zones(*, session: Session, city: City) -> list[Zone]:
    feature_collection = json.loads(
        (SEED_DATA_DIR / "houston_zones.geojson").read_text(encoding="utf-8")
    )
    features = feature_collection["features"]
    for feature in features:
        properties = feature["properties"]
        existing = session.scalar(
            select(Zone).where(Zone.city_id == city.id, Zone.code == properties["code"])
        )
        if existing is None:
            geometry = normalize_geojson_geometry(feature)
            session.add(
                Zone(
                    city_id=city.id,
                    name=properties["name"],
                    code=properties["code"],
                    geometry=from_shape(geometry.shape, srid=4326),
                    active=True,
                    allocation_weight=Decimal(str(properties["allocation_weight"])),
                )
            )
    session.flush()
    zones = session.scalars(
        select(Zone).where(Zone.city_id == city.id, Zone.active.is_(True)).order_by(Zone.code)
    ).all()
    if len(zones) != 8:
        raise ReplayModeError("Replay requires the eight configured Houston active zones.")
    return zones


def _ensure_replay_model(
    *,
    session: Session,
    city: City,
    settings: Settings,
    base_time: datetime,
) -> ModelVersion:
    model = session.scalar(
        select(ModelVersion).where(
            ModelVersion.city_id == city.id,
            ModelVersion.version == REPLAY_MODEL_VERSION,
        )
    )
    artifact_path = Path(settings.model_artifact_dir) / "replay" / f"{REPLAY_MODEL_VERSION}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "version": REPLAY_MODEL_VERSION,
                "algorithm": ALGORITHM,
                "feature_columns": list(FEATURE_COLUMNS),
                "intercept": 0,
                "coefficients": [0 for _ in FEATURE_COLUMNS],
                "fixture": FIXTURE_NAME,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if model is None:
        model = ModelVersion(
            city_id=city.id,
            version=REPLAY_MODEL_VERSION,
            algorithm=ALGORITHM,
            feature_schema_version="replay-v1",
            feature_columns=list(FEATURE_COLUMNS),
            quality_policy=QUALITY_POLICY,
            source_dataset_version="replay-fixture-v1",
            training_data_sha256=hashlib.sha256(FIXTURE_NAME.encode("utf-8")).hexdigest(),
            trained_from=base_time - timedelta(hours=48),
            trained_to=base_time,
            training_row_count=96,
            validation_row_count=24,
            mae_mw=Decimal("0"),
            rmse_mw=Decimal("0"),
            mape_percent=Decimal("0"),
            artifact_path=str(artifact_path.resolve()),
            validation_predictions_path=str(artifact_path.with_suffix(".validation.csv").resolve()),
            artifact_metadata={"data_mode": "replay", "fixture": FIXTURE_NAME},
            is_active=True,
            activated_at=base_time,
        )
        session.add(model)
    active_models = session.scalars(
        select(ModelVersion).where(
            ModelVersion.city_id == city.id,
            ModelVersion.is_active.is_(True),
        )
    ).all()
    for active_model in active_models:
        if active_model.id != model.id:
            active_model.is_active = False
            active_model.activated_at = None
    model.is_active = True
    model.activated_at = base_time
    session.flush()
    return model


def _ensure_replay_demand_history(*, session: Session, city: City, slot: datetime) -> None:
    for offset in range(-24, 1):
        period = slot + timedelta(hours=offset)
        existing = session.scalar(
            select(DemandObservation.id).where(
                DemandObservation.city_id == city.id,
                DemandObservation.source == REPLAY_SOURCE,
                DemandObservation.source_area_code == REPLAY_AREA_CODE,
                DemandObservation.period_utc == period,
            )
        )
        if existing is None:
            session.add(
                DemandObservation(
                    city_id=city.id,
                    period_utc=period,
                    source=REPLAY_SOURCE,
                    source_area_code=REPLAY_AREA_CODE,
                    demand_mw=Decimal("52000") + Decimal(max(offset, 0) * 250),
                    is_actual=True,
                    quality_flag="replay_fixture",
                )
            )


def _ensure_replay_heatmap_run(
    *,
    session: Session,
    city: City,
    slot: datetime,
    fixture_version: str,
) -> tuple[IntegrationJob, HeatmapRun]:
    request_hash = hashlib.sha256(
        f"{FIXTURE_NAME}:{fixture_version}:{slot.isoformat()}".encode("utf-8")
    ).hexdigest()
    job = session.scalar(
        select(IntegrationJob).where(
            IntegrationJob.provider == "replay",
            IntegrationJob.request_hash == request_hash,
        )
    )
    if job is None:
        job = IntegrationJob(
            provider="replay",
            operation="heatmap",
            status="completed",
            external_activity_id=f"replay-{request_hash[:12]}",
            request_hash=request_hash,
            requested_at=slot,
            completed_at=slot,
            provider_status="completed",
            poll_attempts=0,
        )
        session.add(job)
        session.flush()
    heatmap_run = session.scalar(select(HeatmapRun).where(HeatmapRun.job_id == job.id))
    if heatmap_run is None:
        heatmap_run = HeatmapRun(
            job_id=job.id,
            requested_time=slot,
            granularity_m=80,
            analytic_type="tcm",
            aoi_geometry=city.geometry,
            date_time_json={"fixture": FIXTURE_NAME, "filter_type": 1},
            source_kind="replay",
        )
        session.add(heatmap_run)
        session.flush()
    return job, heatmap_run


def _ensure_hourly_replay_outputs(
    *,
    session: Session,
    zones: list[Zone],
    model: ModelVersion,
    heatmap_run: HeatmapRun,
    slot: datetime,
    hour: dict[str, Any],
    retrieved_at: datetime,
) -> list[ZoneForecast]:
    city_temperature = Decimal(str(hour["city_temperature_c"]))
    city_demand = Decimal(str(hour["city_demand_mw"]))
    medical_risk = Decimal(str(hour["medical_center_risk"]))
    offsets = {
        "KATY_WEST": Decimal("-1.0"),
        "ENERGY_CORRIDOR": Decimal("-0.5"),
        "GALLERIA_UPTOWN": Decimal("0.5"),
        "DOWNTOWN": Decimal("1.0"),
        "MEDICAL_CENTER": Decimal("3.0"),
        "EAST_HOUSTON": Decimal("-0.5"),
        "PORT_HOUSTON": Decimal("-0.5"),
        "NORTH_HOUSTON": Decimal("-1.125"),
    }
    weight_total = sum((Decimal(zone.allocation_weight) for zone in zones), start=Decimal("0"))
    raw_weights = {
        zone.id: Decimal(zone.allocation_weight)
        * (Decimal("1") + max(Decimal("-0.5"), min(Decimal("1"), offsets[zone.code] / 5)))
        for zone in zones
    }
    raw_weight_total = sum(raw_weights.values(), start=Decimal("0"))
    forecasts: list[ZoneForecast] = []
    for zone in zones:
        temperature = city_temperature + offsets[zone.code]
        existing_temperature = session.scalar(
            select(ZoneTemperatureObservation).where(
                ZoneTemperatureObservation.zone_id == zone.id,
                ZoneTemperatureObservation.source_run_id == heatmap_run.id,
            )
        )
        if existing_temperature is None:
            session.add(
                ZoneTemperatureObservation(
                    zone_id=zone.id,
                    observed_for=slot,
                    mean_c=temperature,
                    min_c=temperature - Decimal("0.8"),
                    max_c=temperature + Decimal("0.8"),
                    stddev_c=Decimal("0.8"),
                    tile_count=12,
                    source_run_id=heatmap_run.id,
                    is_forecast=True,
                    data_status="available",
                    source_retrieved_at=retrieved_at,
                )
            )
        forecast = session.scalar(
            select(ZoneForecast).where(
                ZoneForecast.zone_id == zone.id,
                ZoneForecast.model_version_id == model.id,
                ZoneForecast.forecast_for == slot,
            )
        )
        if forecast is None:
            baseline = city_demand * Decimal(zone.allocation_weight) / weight_total
            predicted = city_demand * raw_weights[zone.id] / raw_weight_total
            uplift = ((predicted - baseline) / baseline) * Decimal("100")
            risk_score = _risk_score_for_zone(
                zone_code=zone.code,
                medical_risk=medical_risk,
            )
            forecast = ZoneForecast(
                zone_id=zone.id,
                model_version_id=model.id,
                forecast_for=slot,
                generated_at=slot,
                estimate_type="proxy",
                city_forecast_mw=city_demand,
                allocation_weight=Decimal(zone.allocation_weight),
                temperature_c=temperature,
                city_temperature_c=city_temperature,
                heat_anomaly_c=offsets[zone.code],
                temperature_ramp_c_per_hour=Decimal("0.5"),
                temperature_stddev_c=Decimal("0.8"),
                baseline_mw=baseline,
                predicted_mw=predicted,
                uplift_pct=uplift,
                uncertainty_penalty=Decimal("0.104"),
                risk_score=risk_score,
                risk_level=_risk_level(risk_score),
                confidence="high",
                data_freshness_status="fresh",
                explanation_json={
                    "data_mode": "replay",
                    "fixture": FIXTURE_NAME,
                    "scenario": "watch_to_high_to_critical",
                    "risk": {"formula_version": "replay-scenario-v1"},
                },
            )
            session.add(forecast)
        forecasts.append(forecast)
    session.flush()
    return forecasts


def _ensure_completed_replay_cycle(
    *,
    session: Session,
    job: IntegrationJob,
    forecast_for: datetime,
    zone_forecast_count: int,
    recommendation_count: int,
) -> tuple[PipelineCycle, bool]:
    cycle = session.scalar(
        select(PipelineCycle).where(PipelineCycle.integration_job_id == job.id)
    )
    if cycle is not None:
        return cycle, True
    now = datetime.now(UTC)
    cycle = PipelineCycle(
        integration_job_id=job.id,
        trigger_source="demo",
        status="completed",
        forecast_for=forecast_for,
        started_at=now,
        last_advanced_at=now,
        completed_at=now,
        data_freshness_status="fresh",
        zone_forecast_count=zone_forecast_count,
        recommendation_count=recommendation_count,
    )
    session.add(cycle)
    session.flush()
    return cycle, False


def _risk_score_for_zone(*, zone_code: str, medical_risk: Decimal) -> Decimal:
    adjustments = {
        "MEDICAL_CENTER": Decimal("0"),
        "DOWNTOWN": Decimal("-10"),
        "GALLERIA_UPTOWN": Decimal("-14"),
        "ENERGY_CORRIDOR": Decimal("-18"),
        "PORT_HOUSTON": Decimal("-16"),
        "EAST_HOUSTON": Decimal("-22"),
        "KATY_WEST": Decimal("-26"),
        "NORTH_HOUSTON": Decimal("-28"),
    }
    return max(Decimal("0"), min(Decimal("100"), medical_risk + adjustments[zone_code]))


def _risk_level(score: Decimal) -> str:
    if score < Decimal("40"):
        return "low"
    if score < Decimal("65"):
        return "watch"
    if score < Decimal("80"):
        return "high"
    return "critical"


def _next_hour(value: datetime) -> datetime:
    rounded = value.replace(minute=0, second=0, microsecond=0)
    return rounded + timedelta(hours=1)

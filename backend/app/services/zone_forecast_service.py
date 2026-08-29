"""Allocate a safeguarded city estimate into transparent zone-level proxy risk forecasts."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.model_version import ModelVersion
from app.db.models.zone import Zone
from app.db.models.zone_forecast import ZoneForecast
from app.db.models.zone_temperature_observation import ZoneTemperatureObservation
from app.services.audit_service import record_audit_event
from app.services.forecast_model_service import ForecastResult

VALUE_SCALE = Decimal("0.001")
WEIGHT_SCALE = Decimal("0.000001")
RISK_FORMULA_VERSION = "zone-risk-v1"
RISK_INTERCEPT = Decimal("-3")
RISK_MULTIPLIER = Decimal("8")
RISK_COEFFICIENTS = {
    "demand_uplift": Decimal("0.45"),
    "heat_anomaly": Decimal("0.30"),
    "temperature_ramp": Decimal("0.15"),
    "uncertainty": Decimal("0.10"),
}


class ZoneForecastError(ValueError):
    """Raised when complete city inputs cannot safely become a zone forecast set."""


class ZoneForecastNotFoundError(Exception):
    """Raised when a requested stored zone forecast set or timeline does not exist."""


@dataclass(frozen=True)
class ZoneForecastGenerationResult:
    """One persisted forecast set, or the existing equivalent set reused without overwrite."""

    forecast_for: datetime
    city_forecast_mw: Decimal
    model_version: str
    forecasts: list[ZoneForecast]
    reused: bool


def generate_zone_forecasts(
    session: Session,
    *,
    city_forecast: ForecastResult,
    settings: Settings | None = None,
) -> ZoneForecastGenerationResult:
    """Persist one proxy forecast per active zone while preserving historical forecast records."""
    settings = settings or get_settings()
    city = _get_demo_city(session=session, settings=settings)
    model = session.scalar(
        select(ModelVersion).where(
            ModelVersion.city_id == city.id,
            ModelVersion.version == city_forecast.model_version,
        )
    )
    if model is None:
        raise ZoneForecastError("The city forecast does not reference a stored model version.")

    zones = session.scalars(
        select(Zone)
        .where(Zone.city_id == city.id, Zone.active.is_(True))
        .order_by(Zone.code)
    ).all()
    if not zones:
        raise ZoneForecastError("Zone forecasts require active zones.")
    forecast_for = _ensure_utc(city_forecast.forecast_for)
    existing = session.scalars(
        select(ZoneForecast)
        .join(Zone, ZoneForecast.zone_id == Zone.id)
        .where(
            Zone.city_id == city.id,
            ZoneForecast.model_version_id == model.id,
            ZoneForecast.forecast_for == forecast_for,
        )
        .order_by(Zone.code)
    ).all()
    if existing:
        if len(existing) != len(zones):
            raise ZoneForecastError(
                "A partial stored zone forecast set exists for this model and time; it will not be "
                "silently overwritten. Inspect the audit history before retrying."
            )
        return ZoneForecastGenerationResult(
            forecast_for=forecast_for,
            city_forecast_mw=Decimal(existing[0].city_forecast_mw),
            model_version=model.version,
            forecasts=existing,
            reused=True,
        )

    current_temperatures = _latest_zone_temperatures(
        session=session,
        city_id=city.id,
        observed_for=forecast_for,
    )
    required_zone_ids = {zone.id for zone in zones}
    if set(current_temperatures) != required_zone_ids:
        raise ZoneForecastError(
            "Zone forecasts require complete same-time zone-temperature coverage; partial inputs "
            "are not allocated."
        )
    if any(
        observation.data_status != "available" or observation.mean_c is None
        for observation in current_temperatures.values()
    ):
        raise ZoneForecastError(
            "Zone forecasts require available temperatures for every active zone."
        )
    previous_temperatures = _latest_zone_temperatures(
        session=session,
        city_id=city.id,
        observed_for=forecast_for - timedelta(hours=1),
    )
    total_allocation_weight = sum(
        (Decimal(zone.allocation_weight) for zone in zones), start=Decimal("0")
    )
    if total_allocation_weight <= 0:
        raise ZoneForecastError("Zone forecasts require positive active-zone allocation weights.")

    city_temperature = Decimal(city_forecast.city_temperature_c)
    raw_exposure_weights: dict[UUID, Decimal] = {}
    heat_anomalies: dict[UUID, Decimal] = {}
    for zone in zones:
        temperature = Decimal(current_temperatures[zone.id].mean_c)
        anomaly = temperature - city_temperature
        heat_anomalies[zone.id] = anomaly
        raw_exposure_weights[zone.id] = (
            Decimal(zone.allocation_weight)
            / total_allocation_weight
            * _heat_exposure_multiplier(anomaly=anomaly, settings=settings)
        )
    exposure_total = sum(raw_exposure_weights.values(), start=Decimal("0"))
    if exposure_total <= 0:
        raise ZoneForecastError("Zone heat exposure weights could not be calculated safely.")

    generated_at = datetime.now(UTC)
    stored: list[ZoneForecast] = []
    for zone in zones:
        current = current_temperatures[zone.id]
        prior = previous_temperatures.get(zone.id)
        temperature = Decimal(current.mean_c)
        anomaly = heat_anomalies[zone.id]
        ramp = _temperature_ramp(current=current, prior=prior)
        freshness = _freshness_status(
            source_retrieved_at=current.source_retrieved_at,
            generated_at=generated_at,
            settings=settings,
        )
        normalized_weight = raw_exposure_weights[zone.id] / exposure_total
        baseline_mw = (
            Decimal(city_forecast.predicted_demand_mw)
            * Decimal(zone.allocation_weight)
            / total_allocation_weight
        )
        predicted_mw = Decimal(city_forecast.predicted_demand_mw) * normalized_weight
        uplift_pct = (
            ((predicted_mw - baseline_mw) / baseline_mw) * Decimal("100")
            if baseline_mw > 0
            else Decimal("0")
        )
        uncertainty = _uncertainty_penalty(
            temperature_stddev=current.stddev_c,
            has_ramp=ramp is not None,
            freshness=freshness,
            settings=settings,
        )
        risk_score, risk_signals = _risk_score(
            uplift_pct=uplift_pct,
            heat_anomaly_c=anomaly,
            ramp_c_per_hour=ramp,
            uncertainty_penalty=uncertainty,
            settings=settings,
        )
        confidence = _confidence(
            temperature_stddev=current.stddev_c,
            has_ramp=ramp is not None,
            freshness=freshness,
            uncertainty_penalty=uncertainty,
        )
        forecast = ZoneForecast(
            zone_id=zone.id,
            model_version_id=model.id,
            forecast_for=forecast_for,
            generated_at=generated_at,
            estimate_type="proxy",
            city_forecast_mw=_quantize(city_forecast.predicted_demand_mw),
            allocation_weight=Decimal(zone.allocation_weight).quantize(WEIGHT_SCALE),
            temperature_c=_quantize(temperature),
            city_temperature_c=_quantize(city_temperature),
            heat_anomaly_c=_quantize(anomaly),
            temperature_ramp_c_per_hour=_quantize(ramp) if ramp is not None else None,
            temperature_stddev_c=_quantize(Decimal(current.stddev_c))
            if current.stddev_c is not None
            else None,
            baseline_mw=_quantize(baseline_mw),
            predicted_mw=_quantize(predicted_mw),
            uplift_pct=_quantize(uplift_pct),
            uncertainty_penalty=_quantize(uncertainty),
            risk_score=risk_score,
            risk_level=_risk_level(risk_score),
            confidence=confidence,
            data_freshness_status=freshness,
            explanation_json=_explanation(
                zone=zone,
                normalized_weight=normalized_weight,
                heat_multiplier=_heat_exposure_multiplier(anomaly=anomaly, settings=settings),
                risk_signals=risk_signals,
                current=current,
                prior=prior,
                settings=settings,
            ),
        )
        session.add(forecast)
        stored.append(forecast)

    session.flush()
    record_audit_event(
        session,
        event_type="zone_forecasts.generated",
        entity_type="model_version",
        entity_id=model.id,
        payload={
            "forecast_for": forecast_for.isoformat(),
            "zone_count": len(stored),
            "city_forecast_mw": _text(city_forecast.predicted_demand_mw),
            "estimate_type": "proxy",
            "risk_formula_version": RISK_FORMULA_VERSION,
        },
    )
    session.commit()
    for forecast in stored:
        session.refresh(forecast)
    return ZoneForecastGenerationResult(
        forecast_for=forecast_for,
        city_forecast_mw=Decimal(city_forecast.predicted_demand_mw),
        model_version=model.version,
        forecasts=stored,
        reused=False,
    )


def get_latest_zone_forecast_set(
    session: Session,
    *,
    settings: Settings | None = None,
) -> ZoneForecastGenerationResult:
    """Return the latest complete stored forecast set for the configured city."""
    city = _get_demo_city(session=session, settings=settings or get_settings())
    latest = session.scalar(
        select(ZoneForecast.generated_at)
        .join(Zone, ZoneForecast.zone_id == Zone.id)
        .where(Zone.city_id == city.id)
        .order_by(ZoneForecast.generated_at.desc())
        .limit(1)
    )
    if latest is None:
        raise ZoneForecastNotFoundError("No zone forecast has been generated yet.")
    forecasts = session.scalars(
        select(ZoneForecast)
        .join(Zone, ZoneForecast.zone_id == Zone.id)
        .where(Zone.city_id == city.id, ZoneForecast.generated_at == latest)
        .order_by(Zone.code)
    ).all()
    if not forecasts:
        raise ZoneForecastNotFoundError("No zone forecast has been generated yet.")
    model = session.get(ModelVersion, forecasts[0].model_version_id)
    if model is None:
        raise ZoneForecastNotFoundError(
            "The latest zone forecast references a missing model version."
        )
    return ZoneForecastGenerationResult(
        forecast_for=forecasts[0].forecast_for,
        city_forecast_mw=Decimal(forecasts[0].city_forecast_mw),
        model_version=model.version,
        forecasts=forecasts,
        reused=True,
    )


def list_zone_forecasts(
    session: Session,
    *,
    zone_id: UUID,
    start: datetime | None = None,
    end: datetime | None = None,
    settings: Settings | None = None,
) -> list[ZoneForecast]:
    """Return a bounded historical/future forecast timeline for one configured-city zone."""
    settings = settings or get_settings()
    city = _get_demo_city(session=session, settings=settings)
    zone = session.scalar(select(Zone).where(Zone.id == zone_id, Zone.city_id == city.id))
    if zone is None:
        raise ZoneForecastNotFoundError("The requested zone was not found for the demo city.")
    now = datetime.now(UTC)
    start_utc = _ensure_utc(start) if start is not None else now - timedelta(days=7)
    end_utc = _ensure_utc(end) if end is not None else now + timedelta(days=1)
    if end_utc <= start_utc:
        raise ZoneForecastError("End time must be later than start time.")
    if end_utc - start_utc > timedelta(days=366):
        raise ZoneForecastError("Zone forecast range cannot exceed 366 days.")
    return session.scalars(
        select(ZoneForecast)
        .where(
            ZoneForecast.zone_id == zone.id,
            ZoneForecast.forecast_for >= start_utc,
            ZoneForecast.forecast_for <= end_utc,
        )
        .order_by(ZoneForecast.forecast_for, ZoneForecast.generated_at)
    ).all()


def _latest_zone_temperatures(
    *,
    session: Session,
    city_id: UUID,
    observed_for: datetime,
) -> dict[UUID, ZoneTemperatureObservation]:
    observations = session.scalars(
        select(ZoneTemperatureObservation)
        .join(Zone, ZoneTemperatureObservation.zone_id == Zone.id)
        .where(
            Zone.city_id == city_id,
            Zone.active.is_(True),
            ZoneTemperatureObservation.observed_for == observed_for,
        )
        .order_by(ZoneTemperatureObservation.source_retrieved_at.desc())
    ).all()
    latest: dict[UUID, ZoneTemperatureObservation] = {}
    for observation in observations:
        latest.setdefault(observation.zone_id, observation)
    return latest


def _heat_exposure_multiplier(*, anomaly: Decimal, settings: Settings) -> Decimal:
    normalized_anomaly = max(
        Decimal("-0.50"),
        min(Decimal("1"), anomaly / settings.zone_risk_heat_anomaly_scale_c),
    )
    return Decimal("1") + normalized_anomaly


def _temperature_ramp(
    *,
    current: ZoneTemperatureObservation,
    prior: ZoneTemperatureObservation | None,
) -> Decimal | None:
    if (
        prior is None
        or prior.data_status != "available"
        or prior.mean_c is None
        or current.mean_c is None
    ):
        return None
    return Decimal(current.mean_c) - Decimal(prior.mean_c)


def _freshness_status(
    *,
    source_retrieved_at: datetime,
    generated_at: datetime,
    settings: Settings,
) -> str:
    maximum_age = timedelta(minutes=settings.zone_forecast_max_temperature_age_minutes)
    return "fresh" if generated_at - _ensure_utc(source_retrieved_at) <= maximum_age else "stale"


def _uncertainty_penalty(
    *,
    temperature_stddev: Decimal | None,
    has_ramp: bool,
    freshness: str,
    settings: Settings,
) -> Decimal:
    spatial_variability = (
        _unit_interval(Decimal(temperature_stddev) / settings.zone_risk_temperature_stddev_scale_c)
        if temperature_stddev is not None
        else Decimal("0.50")
    )
    penalty = spatial_variability * Decimal("0.65")
    if not has_ramp:
        penalty += Decimal("0.20")
    if freshness == "stale":
        penalty += Decimal("0.25")
    return min(Decimal("1"), penalty)


def _risk_score(
    *,
    uplift_pct: Decimal,
    heat_anomaly_c: Decimal,
    ramp_c_per_hour: Decimal | None,
    uncertainty_penalty: Decimal,
    settings: Settings,
) -> tuple[Decimal, dict[str, Decimal]]:
    signals = {
        "demand_uplift": _unit_interval(
            max(Decimal("0"), uplift_pct) / settings.zone_risk_uplift_scale_percent
        ),
        "heat_anomaly": _unit_interval(
            max(Decimal("0"), heat_anomaly_c) / settings.zone_risk_heat_anomaly_scale_c
        ),
        "temperature_ramp": _unit_interval(
            max(Decimal("0"), ramp_c_per_hour or Decimal("0"))
            / settings.zone_risk_temperature_ramp_scale_c_per_hour
        ),
        "uncertainty": _unit_interval(uncertainty_penalty),
    }
    weighted_signal = sum(
        (RISK_COEFFICIENTS[name] * value for name, value in signals.items()),
        start=Decimal("0"),
    )
    logit = RISK_INTERCEPT + RISK_MULTIPLIER * weighted_signal
    score = Decimal(str(100 / (1 + math.exp(-float(logit)))))
    return _quantize(score), signals


def _risk_level(score: Decimal) -> str:
    if score < Decimal("40"):
        return "low"
    if score < Decimal("65"):
        return "watch"
    if score < Decimal("80"):
        return "high"
    return "critical"


def _confidence(
    *,
    temperature_stddev: Decimal | None,
    has_ramp: bool,
    freshness: str,
    uncertainty_penalty: Decimal,
) -> str:
    if freshness == "stale" or uncertainty_penalty >= Decimal("0.70"):
        return "low"
    if temperature_stddev is None or not has_ramp or uncertainty_penalty >= Decimal("0.35"):
        return "medium"
    return "high"


def _explanation(
    *,
    zone: Zone,
    normalized_weight: Decimal,
    heat_multiplier: Decimal,
    risk_signals: dict[str, Decimal],
    current: ZoneTemperatureObservation,
    prior: ZoneTemperatureObservation | None,
    settings: Settings,
) -> dict[str, Any]:
    return {
        "allocation": {
            "method": "allocation_weight_adjusted_by_heat_anomaly",
            "zone_code": zone.code,
            "heat_exposure_multiplier": _text(heat_multiplier),
            "normalized_exposure_weight": _text(normalized_weight),
        },
        "risk": {
            "formula_version": RISK_FORMULA_VERSION,
            "intercept": _text(RISK_INTERCEPT),
            "logistic_multiplier": _text(RISK_MULTIPLIER),
            "coefficients": {name: _text(value) for name, value in RISK_COEFFICIENTS.items()},
            "normalized_signals": {name: _text(value) for name, value in risk_signals.items()},
            "normalization_scales": {
                "uplift_percent": _text(settings.zone_risk_uplift_scale_percent),
                "heat_anomaly_c": _text(settings.zone_risk_heat_anomaly_scale_c),
                "temperature_ramp_c_per_hour": _text(
                    settings.zone_risk_temperature_ramp_scale_c_per_hour
                ),
                "temperature_stddev_c": _text(settings.zone_risk_temperature_stddev_scale_c),
            },
        },
        "data_quality": {
            "temperature_source_run_id": str(current.source_run_id),
            "temperature_retrieved_at": _ensure_utc(current.source_retrieved_at).isoformat(),
            "prior_temperature_available": prior is not None
            and prior.data_status == "available"
            and prior.mean_c is not None,
        },
    }


def _get_demo_city(*, session: Session, settings: Settings) -> City:
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None:
        raise ZoneForecastError(
            "The configured demo city is missing. Seed the city before forecasting."
        )
    return city


def _unit_interval(value: Decimal) -> Decimal:
    return max(Decimal("0"), min(Decimal("1"), value))


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _quantize(value: Decimal) -> Decimal:
    return Decimal(value).quantize(VALUE_SCALE, rounding=ROUND_HALF_UP)


def _text(value: Decimal) -> str:
    return format(value, "f")

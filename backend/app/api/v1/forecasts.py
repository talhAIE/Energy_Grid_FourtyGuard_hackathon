from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.db.models.model_version import ModelVersion
from app.schemas.zone_forecasts import (
    ZoneForecastData,
    ZoneForecastSetData,
    ZoneForecastSetResponse,
    ZoneForecastTimelineResponse,
)
from app.services.zone_forecast_service import (
    ZoneForecastError,
    ZoneForecastNotFoundError,
    get_latest_zone_forecast_set,
    list_zone_forecasts,
)

router = APIRouter()


@router.get(
    "/latest",
    response_model=ZoneForecastSetResponse,
    summary="Get the latest zone risk set",
)
def get_latest_forecasts(session: Session = Depends(get_db_session)) -> ZoneForecastSetResponse:
    """Return all zones produced by the most recent proxy forecast run."""
    try:
        result = get_latest_zone_forecast_set(session=session)
    except ZoneForecastNotFoundError as exc:
        raise _http_error(404, "forecast_not_found", str(exc)) from exc
    return ZoneForecastSetResponse(
        data=ZoneForecastSetData(
            forecast_for=result.forecast_for,
            generated_at=result.forecasts[0].generated_at,
            model_version=result.model_version,
            city_forecast_mw=result.city_forecast_mw,
            forecasts=[
                _to_data(forecast, model_version=result.model_version)
                for forecast in result.forecasts
            ],
        )
    )


@router.get(
    "/zones/{zone_id}",
    response_model=ZoneForecastTimelineResponse,
    summary="Get a zone's forecast and risk timeline",
)
def get_zone_forecast_timeline(
    zone_id: UUID,
    start: datetime | None = Query(
        default=None,
        description="Optional inclusive ISO-8601 UTC start.",
    ),
    end: datetime | None = Query(default=None, description="Optional inclusive ISO-8601 UTC end."),
    session: Session = Depends(get_db_session),
) -> ZoneForecastTimelineResponse:
    """Return at most 366 days of stored proxy forecasts; default range is recent/future week."""
    try:
        forecasts = list_zone_forecasts(session=session, zone_id=zone_id, start=start, end=end)
    except ZoneForecastNotFoundError as exc:
        raise _http_error(404, "zone_not_found", str(exc)) from exc
    except ZoneForecastError as exc:
        raise _http_error(422, "invalid_forecast_range", str(exc)) from exc
    model_versions = {
        model.id: model.version
        for model in session.scalars(
            select(ModelVersion).where(
                ModelVersion.id.in_({item.model_version_id for item in forecasts})
            )
        ).all()
    }
    return ZoneForecastTimelineResponse(
        data=[
            _to_data(forecast, model_version=model_versions.get(forecast.model_version_id))
            for forecast in forecasts
        ],
        count=len(forecasts),
    )


def _to_data(forecast, *, model_version: str | None = None) -> ZoneForecastData:
    return ZoneForecastData(
        id=forecast.id,
        zone_id=forecast.zone_id,
        forecast_for=forecast.forecast_for,
        generated_at=forecast.generated_at,
        model_version=model_version or "unavailable",
        estimate_type=forecast.estimate_type,
        city_forecast_mw=forecast.city_forecast_mw,
        allocation_weight=forecast.allocation_weight,
        temperature_c=forecast.temperature_c,
        city_temperature_c=forecast.city_temperature_c,
        heat_anomaly_c=forecast.heat_anomaly_c,
        temperature_ramp_c_per_hour=forecast.temperature_ramp_c_per_hour,
        temperature_stddev_c=forecast.temperature_stddev_c,
        baseline_mw=forecast.baseline_mw,
        predicted_mw=forecast.predicted_mw,
        uplift_pct=forecast.uplift_pct,
        uncertainty_penalty=forecast.uncertainty_penalty,
        risk_score=forecast.risk_score,
        risk_level=forecast.risk_level,
        confidence=forecast.confidence,
        data_freshness_status=forecast.data_freshness_status,
        explanation=forecast.explanation_json,
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

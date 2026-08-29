from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.forecasts import (
    ActiveModelData,
    ActiveModelResponse,
    ForecastRunData,
    ForecastRunRequest,
    ForecastRunResponse,
)
from app.services.forecast_model_service import (
    ForecastInputError,
    ModelArtifactError,
    ModelNotAvailableError,
    get_active_model_summary,
    run_city_forecast,
)

router = APIRouter()


@router.get(
    "/models/active",
    response_model=ActiveModelResponse,
    summary="Get the active city-level baseline demand model",
)
def get_active_model(session: Session = Depends(get_db_session)) -> ActiveModelResponse:
    """Return model metadata and validation metrics; the artifact remains server-side."""
    try:
        result = get_active_model_summary(session=session)
    except ModelNotAvailableError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "model_not_available", str(exc)
        ) from exc
    return ActiveModelResponse(data=ActiveModelData(**result.__dict__))


@router.post(
    "/run",
    response_model=ForecastRunResponse,
    summary="Run one city-level baseline demand estimate",
)
def post_forecast_run(
    payload: ForecastRunRequest,
    session: Session = Depends(get_db_session),
) -> ForecastRunResponse:
    """Forecast only with a named active model and complete, same-time input data."""
    try:
        result = run_city_forecast(session=session, forecast_for=payload.forecast_for)
    except ModelNotAvailableError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "model_not_available", str(exc)
        ) from exc
    except ModelArtifactError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "model_artifact_unavailable",
            str(exc),
        ) from exc
    except ForecastInputError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "forecast_input_not_ready", str(exc)
        ) from exc
    return ForecastRunResponse(data=ForecastRunData(**result.__dict__))


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

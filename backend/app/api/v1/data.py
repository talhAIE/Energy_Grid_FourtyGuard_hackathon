from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.demand import (
    DemandObservationListResponse,
    EiaImportRequest,
    EiaImportResponse,
    EiaImportResultData,
)
from app.services.demand_data_service import (
    DemandDataNotReadyError,
    import_eia_demand,
    list_demand_observations,
)
from app.services.eia_client import (
    EiaConfigurationError,
    EiaRequestError,
    EiaResponseError,
    EiaValidationError,
)

router = APIRouter()


@router.post(
    "/eia/import",
    response_model=EiaImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import configured EIA hourly demand data",
)
def post_eia_import(
    payload: EiaImportRequest,
    session: Session = Depends(get_db_session),
) -> EiaImportResponse:
    """Import a short historical range; later phases move recurring work to a worker."""
    try:
        result = import_eia_demand(session=session, start=payload.start, end=payload.end)
    except EiaValidationError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_date_range", str(exc)
        ) from exc
    except EiaConfigurationError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "eia_not_configured", str(exc)
        ) from exc
    except DemandDataNotReadyError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "demand_data_not_ready", str(exc)
        ) from exc
    except EiaRequestError as exc:
        raise _http_error(status.HTTP_502_BAD_GATEWAY, "eia_request_failed", str(exc)) from exc
    except EiaResponseError as exc:
        raise _http_error(status.HTTP_502_BAD_GATEWAY, "eia_invalid_response", str(exc)) from exc

    return EiaImportResponse(data=EiaImportResultData(**result.__dict__))


@router.get(
    "/demand",
    response_model=DemandObservationListResponse,
    summary="List stored hourly demand observations",
)
def get_demand(
    start: datetime = Query(description="Inclusive ISO-8601 start time. UTC is recommended."),
    end: datetime = Query(description="Inclusive ISO-8601 end time. UTC is recommended."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    session: Session = Depends(get_db_session),
) -> DemandObservationListResponse:
    """Read bounded persisted demand data; this route never contacts EIA."""
    try:
        observations, total = list_demand_observations(
            session=session,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
    except EiaValidationError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_date_range", str(exc)
        ) from exc
    except DemandDataNotReadyError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "demand_data_not_ready", str(exc)
        ) from exc
    return DemandObservationListResponse(
        data=observations,
        count=len(observations),
        total=total,
        limit=limit,
        offset=offset,
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.heatmaps import HeatmapSubmitRequest, HeatmapSubmitResponse
from app.services.fortyguard_client import (
    FortyGuardConfigurationError,
    FortyGuardRequestError,
    FortyGuardResponseError,
)
from app.services.heatmap_submission_service import (
    HeatmapDuplicateError,
    HeatmapNotReadyError,
    HeatmapValidationError,
    submit_heatmap,
)

router = APIRouter()


@router.post(
    "/submit",
    response_model=HeatmapSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an asynchronous FortyGuard heatmap task",
)
def post_heatmap_submit(
    payload: HeatmapSubmitRequest,
    session: Session = Depends(get_db_session),
) -> HeatmapSubmitResponse:
    """Return after submission acknowledgement only; task polling is implemented in Phase 5."""
    try:
        job = submit_heatmap(session=session, payload=payload)
    except HeatmapValidationError as exc:
        raise _http_error(status.HTTP_400_BAD_REQUEST, "invalid_heatmap_request", str(exc)) from exc
    except HeatmapNotReadyError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "heatmap_not_ready", str(exc)
        ) from exc
    except FortyGuardConfigurationError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "fortyguard_not_configured", str(exc)
        ) from exc
    except FortyGuardRequestError as exc:
        raise _http_error(
            status.HTTP_502_BAD_GATEWAY, "fortyguard_submission_failed", str(exc)
        ) from exc
    except FortyGuardResponseError as exc:
        raise _http_error(
            status.HTTP_502_BAD_GATEWAY, "fortyguard_invalid_response", str(exc)
        ) from exc
    except HeatmapDuplicateError as exc:
        raise _http_error(
            status.HTTP_409_CONFLICT, "heatmap_submission_not_repeatable", str(exc)
        ) from exc
    return HeatmapSubmitResponse(data=job)


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

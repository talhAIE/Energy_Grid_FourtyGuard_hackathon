"""Development-only route for preparing a complete live dashboard input set."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db_session
from app.schemas.live_setup import LiveSetupData, LiveSetupResponse, LiveZoneSampleData
from app.services.fortyguard_client import (
    FortyGuardConfigurationError,
    FortyGuardRequestError,
    FortyGuardResponseError,
)
from app.services.heatmap_submission_service import (
    HeatmapBudgetExceededError,
    HeatmapDuplicateError,
)
from app.services.live_setup_service import LiveSetupError, prepare_live_dashboard

router = APIRouter()


@router.post("/setup", response_model=LiveSetupResponse, status_code=status.HTTP_202_ACCEPTED)
def post_live_setup(session: Session = Depends(get_db_session)) -> LiveSetupResponse:
    """Submit one bounded live temperature sample for every active zone."""
    if get_settings().app_env.lower() not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "live_setup_disabled", "message": "Live setup is development-only."},
        )
    try:
        result = prepare_live_dashboard(session=session)
    except LiveSetupError as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "live_setup_not_ready", str(exc)
        ) from exc
    except HeatmapBudgetExceededError as exc:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "heatmap_submission_budget_exceeded",
            str(exc),
        ) from exc
    except HeatmapDuplicateError as exc:
        raise _error(
            status.HTTP_409_CONFLICT, "heatmap_submission_not_repeatable", str(exc)
        ) from exc
    except FortyGuardConfigurationError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE, "fortyguard_not_configured", str(exc)
        ) from exc
    except (FortyGuardRequestError, FortyGuardResponseError) as exc:
        raise _error(status.HTTP_502_BAD_GATEWAY, "fortyguard_submission_failed", str(exc)) from exc
    return LiveSetupResponse(
        data=LiveSetupData(
            forecast_for=result.forecast_for,
            model_version=result.model_version,
            model_quality_policy=result.model_quality_policy,
            model_reused=result.model_reused,
            samples=[
                LiveZoneSampleData(
                    zone_id=sample.zone_id,
                    zone_code=sample.zone_code,
                    zone_name=sample.zone_name,
                    job=sample.job,
                )
                for sample in result.samples
            ],
        )
    )


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db_session
from app.schemas.cycles import CycleData, CycleResponse, CycleRunRequest
from app.schemas.replay import ReplayLoadData, ReplayLoadResponse
from app.services.fortyguard_client import (
    FortyGuardConfigurationError,
    FortyGuardRequestError,
    FortyGuardResponseError,
)
from app.services.heatmap_submission_service import (
    HeatmapBudgetExceededError,
    HeatmapDuplicateError,
    HeatmapNotReadyError,
    HeatmapValidationError,
)
from app.services.pipeline_cycle_service import (
    CycleProgress,
    PipelineCycleError,
    advance_cycle,
    get_cycle,
    start_cycle,
)
from app.services.replay_service import ReplayModeError, load_replay, run_replay_cycle

router = APIRouter()
demo_router = APIRouter()


@router.post(
    "/run",
    response_model=CycleResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit or advance one manual forecast pipeline cycle",
)
def post_cycle_run(
    payload: CycleRunRequest,
    session: Session = Depends(get_db_session),
) -> CycleResponse:
    """Development-only one-shot orchestration; repeat the call to make the next bounded poll."""
    _require_development_control()
    return _start_response(session=session, payload=payload, trigger_source="manual")


@router.get("/{cycle_id}", response_model=CycleResponse, summary="Get stored pipeline cycle state")
def get_cycle_by_id(
    cycle_id: UUID,
    session: Session = Depends(get_db_session),
) -> CycleResponse:
    """Read durable status and data freshness without polling FortyGuard."""
    try:
        progress = get_cycle(session=session, cycle_id=cycle_id)
    except PipelineCycleError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "pipeline_cycle_not_found", str(exc)) from exc
    return CycleResponse(data=_to_data(progress))


@router.post(
    "/{cycle_id}/advance",
    response_model=CycleResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Advance one pipeline cycle once",
)
def post_cycle_advance(
    cycle_id: UUID,
    session: Session = Depends(get_db_session),
) -> CycleResponse:
    """Development-only: issue at most one provider poll and return promptly."""
    _require_development_control()
    try:
        progress = advance_cycle(session=session, cycle_id=cycle_id)
    except PipelineCycleError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "pipeline_cycle_not_found", str(exc)) from exc
    return CycleResponse(data=_to_data(progress))


@demo_router.post(
    "/run-cycle",
    response_model=CycleResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run one development/demo pipeline cycle step",
)
def post_demo_run_cycle(
    payload: CycleRunRequest | None = None,
    session: Session = Depends(get_db_session),
) -> CycleResponse:
    """Run the offline fixture when enabled; otherwise use the safe live demo path."""
    _require_development_control()
    if get_settings().replay_mode:
        try:
            replay = run_replay_cycle(session=session)
        except ReplayModeError as exc:
            raise _http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "replay_unavailable",
                str(exc),
            ) from exc
        return CycleResponse(
            data=_to_data(
                CycleProgress(cycle=replay.cycle, job=replay.job, reused=replay.reused)
            )
        )
    if payload is None:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "heatmap_request_required",
            "A heatmap request is required unless REPLAY_MODE=true.",
        )
    return _start_response(session=session, payload=payload, trigger_source="demo")


@demo_router.post(
    "/load-replay",
    response_model=ReplayLoadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Load the scrubbed offline Houston replay scenario",
)
def post_load_replay(session: Session = Depends(get_db_session)) -> ReplayLoadResponse:
    """Development/test-only fixture loader with no external network calls."""
    _require_development_control()
    try:
        replay = load_replay(session=session)
    except ReplayModeError as exc:
        raise _http_error(status.HTTP_409_CONFLICT, "replay_mode_disabled", str(exc)) from exc
    return ReplayLoadResponse(
        data=ReplayLoadData(
            scenario=replay.scenario,
            cycle_id=replay.cycle.id,
            job_id=replay.job.id,
            zone_forecast_count=replay.zone_forecast_count,
            recommendations_created_count=replay.recommendation_result.created_count,
            recommendations_reused_count=replay.recommendation_result.reused_count,
            reused=replay.reused,
        )
    )


def _start_response(
    *,
    session: Session,
    payload: CycleRunRequest,
    trigger_source: str,
) -> CycleResponse:
    try:
        progress = start_cycle(
            session=session,
            payload=payload.heatmap,
            trigger_source=trigger_source,
        )
    except HeatmapValidationError as exc:
        raise _http_error(status.HTTP_400_BAD_REQUEST, "invalid_heatmap_request", str(exc)) from exc
    except HeatmapNotReadyError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "heatmap_not_ready",
            str(exc),
        ) from exc
    except FortyGuardConfigurationError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "fortyguard_not_configured",
            str(exc),
        ) from exc
    except FortyGuardRequestError as exc:
        raise _http_error(
            status.HTTP_502_BAD_GATEWAY,
            "fortyguard_submission_failed",
            str(exc),
        ) from exc
    except FortyGuardResponseError as exc:
        raise _http_error(
            status.HTTP_502_BAD_GATEWAY,
            "fortyguard_invalid_response",
            str(exc),
        ) from exc
    except HeatmapDuplicateError as exc:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "heatmap_submission_not_repeatable",
            str(exc),
        ) from exc
    except HeatmapBudgetExceededError as exc:
        raise _http_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "heatmap_submission_budget_exceeded",
            str(exc),
        ) from exc
    except PipelineCycleError as exc:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "pipeline_cycle_unavailable",
            str(exc),
        ) from exc
    return CycleResponse(data=_to_data(progress))


def _require_development_control() -> None:
    if get_settings().app_env.lower() not in {"development", "test"}:
        raise _http_error(
            status.HTTP_403_FORBIDDEN,
            "pipeline_control_disabled",
            "Manual pipeline controls are available only in development or test environments.",
        )


def _to_data(progress: CycleProgress) -> CycleData:
    cycle = progress.cycle
    job = progress.job
    return CycleData(
        id=cycle.id,
        trigger_source=cycle.trigger_source,
        status=cycle.status,
        job_id=job.id,
        job_status=job.status,
        provider_status=job.provider_status,
        activity_id=job.external_activity_id,
        forecast_for=cycle.forecast_for,
        started_at=cycle.started_at,
        last_advanced_at=cycle.last_advanced_at,
        completed_at=cycle.completed_at,
        error_code=cycle.error_code,
        poll_attempts=job.poll_attempts,
        data_freshness_status=cycle.data_freshness_status,
        zone_forecast_count=cycle.zone_forecast_count,
        recommendation_count=cycle.recommendation_count,
        reused=progress.reused,
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

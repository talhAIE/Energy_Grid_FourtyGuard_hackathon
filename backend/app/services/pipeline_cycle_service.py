"""Durable, manually advanced orchestration for the heatmap-to-recommendation pipeline."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.heatmap_run import HeatmapRun
from app.db.models.integration_job import IntegrationJob
from app.db.models.pipeline_cycle import PipelineCycle
from app.db.models.zone_forecast import ZoneForecast
from app.schemas.heatmaps import HeatmapSubmitRequest
from app.services.audit_service import record_audit_event
from app.services.forecast_model_service import (
    ForecastInputError,
    ModelArtifactError,
    ModelNotAvailableError,
    run_city_forecast,
)
from app.services.fortyguard_client import FortyGuardConfigurationError
from app.services.heatmap_polling_service import poll_heatmap_job
from app.services.heatmap_submission_service import submit_heatmap
from app.services.recommendation_service import RecommendationError, generate_recommendations
from app.services.zone_forecast_service import ZoneForecastError, generate_zone_forecasts

ACTIVE_JOB_STATUSES = {"submitting", "submitted", "processing"}
SUCCESS_JOB_STATUSES = {"completed", "succeeded"}
FAILED_JOB_STATUSES = {"failed", "timed_out", "submission_failed"}
FINAL_CYCLE_STATUSES = {"completed", "failed", "blocked"}


class PipelineCycleError(ValueError):
    """Raised when a pipeline cycle record is missing or cannot be safely advanced."""


@dataclass(frozen=True)
class CycleProgress:
    cycle: PipelineCycle
    job: IntegrationJob
    reused: bool


def start_cycle(
    session: Session,
    *,
    payload: HeatmapSubmitRequest,
    trigger_source: str,
    settings: Settings | None = None,
) -> CycleProgress:
    """Submit/reuse a heatmap job, create/reuse its durable cycle, then advance it once."""
    settings = settings or get_settings()
    submission = submit_heatmap(session=session, payload=payload, settings=settings)
    job = session.get(IntegrationJob, submission.job_id)
    if job is None:
        raise PipelineCycleError("The submitted heatmap job could not be recovered.")
    cycle = session.scalar(
        select(PipelineCycle).where(PipelineCycle.integration_job_id == job.id)
    )
    reused = cycle is not None
    if cycle is None:
        heatmap_run = session.scalar(select(HeatmapRun).where(HeatmapRun.job_id == job.id))
        if heatmap_run is None:
            raise PipelineCycleError("The heatmap job has no persisted heatmap-run context.")
        now = datetime.now(UTC)
        cycle = PipelineCycle(
            integration_job_id=job.id,
            trigger_source=trigger_source,
            status=_cycle_status_for_job(job.status),
            forecast_for=_ensure_utc(heatmap_run.requested_time),
            started_at=now,
            data_freshness_status="unavailable",
            zone_forecast_count=0,
            recommendation_count=0,
        )
        session.add(cycle)
        session.flush()
        record_audit_event(
            session,
            event_type="pipeline.cycle_started",
            entity_type="pipeline_cycle",
            entity_id=cycle.id,
            payload={
                "integration_job_id": str(job.id),
                "trigger_source": trigger_source,
                "forecast_for": cycle.forecast_for.isoformat(),
                "job_reused": submission.reused,
            },
        )
        session.commit()
        session.refresh(cycle)
    progress = advance_cycle(session=session, cycle_id=cycle.id, settings=settings)
    return CycleProgress(cycle=progress.cycle, job=progress.job, reused=reused)


def advance_cycle(
    session: Session,
    *,
    cycle_id: UUID,
    settings: Settings | None = None,
) -> CycleProgress:
    """Perform at most one provider poll, then run downstream stages only after success."""
    settings = settings or get_settings()
    cycle = session.scalar(
        select(PipelineCycle).where(PipelineCycle.id == cycle_id).with_for_update()
    )
    if cycle is None:
        raise PipelineCycleError("The requested pipeline cycle was not found.")
    job = session.get(IntegrationJob, cycle.integration_job_id)
    if job is None:
        _mark_cycle_failed(
            session=session,
            cycle=cycle,
            now=datetime.now(UTC),
            error_code="missing_integration_job",
        )
        raise PipelineCycleError("The pipeline cycle references a missing integration job.")
    if cycle.status in FINAL_CYCLE_STATUSES:
        return CycleProgress(cycle=cycle, job=job, reused=True)

    now = datetime.now(UTC)
    cycle.last_advanced_at = now
    if job.status in ACTIVE_JOB_STATUSES:
        if job.poll_attempts >= settings.pipeline_max_poll_attempts:
            job.status = "failed"
            job.completed_at = now
            job.error_code = "pipeline_poll_attempt_limit_exceeded"
            record_audit_event(
                session,
                event_type="pipeline.poll_attempt_limit_exceeded",
                entity_type="integration_job",
                entity_id=job.id,
                payload={"max_poll_attempts": settings.pipeline_max_poll_attempts},
            )
            _mark_cycle_failed(
                session=session,
                cycle=cycle,
                now=now,
                error_code=job.error_code,
                commit=False,
            )
            session.commit()
            session.refresh(job)
            session.refresh(cycle)
            return CycleProgress(cycle=cycle, job=job, reused=True)
        try:
            poll_heatmap_job(session=session, job_id=job.id, settings=settings)
        except FortyGuardConfigurationError:
            _mark_cycle_failed(
                session=session,
                cycle=cycle,
                now=now,
                error_code="fortyguard_not_configured",
            )
            session.refresh(job)
            return CycleProgress(cycle=cycle, job=job, reused=True)
        session.refresh(job)

    if job.status in ACTIVE_JOB_STATUSES:
        cycle.status = "processing" if job.status == "processing" else "submitted"
        cycle.error_code = job.error_code
        session.commit()
        session.refresh(cycle)
        return CycleProgress(cycle=cycle, job=job, reused=True)
    if job.status in FAILED_JOB_STATUSES:
        _mark_cycle_failed(
            session=session,
            cycle=cycle,
            now=now,
            error_code=job.error_code or f"job_{job.status}",
        )
        session.refresh(job)
        return CycleProgress(cycle=cycle, job=job, reused=True)
    if job.status not in SUCCESS_JOB_STATUSES:
        _mark_cycle_blocked(
            session=session,
            cycle=cycle,
            now=now,
            error_code="unsupported_job_status",
        )
        session.refresh(job)
        return CycleProgress(cycle=cycle, job=job, reused=True)
    if job.error_code == "normalization_failed":
        _mark_cycle_blocked(
            session=session,
            cycle=cycle,
            now=now,
            error_code="heatmap_normalization_failed",
        )
        session.refresh(job)
        return CycleProgress(cycle=cycle, job=job, reused=True)

    _run_downstream_stages(session=session, cycle=cycle, job=job, now=now, settings=settings)
    session.refresh(job)
    session.refresh(cycle)
    return CycleProgress(cycle=cycle, job=job, reused=True)


def get_cycle(session: Session, *, cycle_id: UUID) -> CycleProgress:
    """Return safe persisted cycle and job state without advancing or polling the provider."""
    cycle = session.get(PipelineCycle, cycle_id)
    if cycle is None:
        raise PipelineCycleError("The requested pipeline cycle was not found.")
    job = session.get(IntegrationJob, cycle.integration_job_id)
    if job is None:
        raise PipelineCycleError("The pipeline cycle references a missing integration job.")
    return CycleProgress(cycle=cycle, job=job, reused=True)


def _run_downstream_stages(
    *,
    session: Session,
    cycle: PipelineCycle,
    job: IntegrationJob,
    now: datetime,
    settings: Settings,
) -> None:
    try:
        city_forecast = run_city_forecast(
            session=session,
            forecast_for=cycle.forecast_for,
            settings=settings,
        )
        zone_result = generate_zone_forecasts(
            session=session,
            city_forecast=city_forecast,
            settings=settings,
        )
        recommendation_result = generate_recommendations(
            session=session,
            zone_forecasts=zone_result.forecasts,
            settings=settings,
        )
    except (ForecastInputError, ModelArtifactError, ModelNotAvailableError) as exc:
        _mark_cycle_blocked(
            session=session,
            cycle=cycle,
            now=now,
            error_code="forecast_input_not_ready",
            detail=str(exc),
        )
        return
    except ZoneForecastError as exc:
        _mark_cycle_blocked(
            session=session,
            cycle=cycle,
            now=now,
            error_code="zone_forecast_input_not_ready",
            detail=str(exc),
        )
        return
    except RecommendationError as exc:
        _mark_cycle_blocked(
            session=session,
            cycle=cycle,
            now=now,
            error_code="recommendation_generation_failed",
            detail=str(exc),
        )
        return

    cycle.status = "completed"
    cycle.completed_at = now
    cycle.error_code = None
    cycle.zone_forecast_count = len(zone_result.forecasts)
    cycle.recommendation_count = recommendation_result.created_count
    cycle.data_freshness_status = _freshness_status(zone_result.forecasts)
    record_audit_event(
        session,
        event_type="pipeline.cycle_completed",
        entity_type="pipeline_cycle",
        entity_id=cycle.id,
        payload={
            "integration_job_id": str(job.id),
            "forecast_for": cycle.forecast_for.isoformat(),
            "zone_forecast_count": cycle.zone_forecast_count,
            "recommendation_count": cycle.recommendation_count,
            "data_freshness_status": cycle.data_freshness_status,
        },
    )
    session.commit()


def _mark_cycle_failed(
    *,
    session: Session,
    cycle: PipelineCycle,
    now: datetime,
    error_code: str,
    commit: bool = True,
) -> None:
    cycle.status = "failed"
    cycle.completed_at = now
    cycle.error_code = error_code
    record_audit_event(
        session,
        event_type="pipeline.cycle_failed",
        entity_type="pipeline_cycle",
        entity_id=cycle.id,
        payload={"error_code": error_code},
    )
    if commit:
        session.commit()


def _mark_cycle_blocked(
    *,
    session: Session,
    cycle: PipelineCycle,
    now: datetime,
    error_code: str,
    detail: str | None = None,
) -> None:
    cycle.status = "blocked"
    cycle.completed_at = now
    cycle.error_code = error_code
    record_audit_event(
        session,
        event_type="pipeline.cycle_blocked",
        entity_type="pipeline_cycle",
        entity_id=cycle.id,
        payload=(
            {"error_code": error_code, "detail": detail}
            if detail
            else {"error_code": error_code}
        ),
    )
    session.commit()


def _cycle_status_for_job(job_status: str) -> str:
    if job_status in SUCCESS_JOB_STATUSES:
        return "processing"
    if job_status in FAILED_JOB_STATUSES:
        return "failed"
    return "submitted"


def _freshness_status(forecasts: list[ZoneForecast]) -> str:
    if not forecasts:
        return "unavailable"
    return "fresh" if all(item.data_freshness_status == "fresh" for item in forecasts) else "stale"


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

"""One-shot, API-triggered FortyGuard status polling with controlled storage."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.integration_job import IntegrationJob
from app.schemas.jobs import JobData
from app.services.audit_service import record_audit_event
from app.services.fortyguard_client import (
    FortyGuardClient,
    FortyGuardConfigurationError,
    FortyGuardPollError,
    FortyGuardPollResult,
)
from app.services.heatmap_normalization_service import (
    HeatmapNormalizationError,
    normalize_completed_heatmap,
)

TERMINAL_JOB_STATUSES = {"completed", "failed", "succeeded", "timed_out", "submission_failed"}
SUCCESS_PROVIDER_STATUSES = {"completed", "succeeded"}
FAILED_PROVIDER_STATUSES = {"failed", "error"}
SENSITIVE_KEY_PARTS = (
    "authorization",
    "credential",
    "download",
    "password",
    "secret",
    "signature",
    "signed",
    "token",
    "url",
    "uri",
)


class JobNotFoundError(Exception):
    """Raised when an internal job ID does not exist."""


def get_job(session: Session, *, job_id: UUID) -> JobData:
    """Return stored job metadata without returning raw provider response content."""
    job = session.get(IntegrationJob, job_id)
    if job is None:
        raise JobNotFoundError("The requested job was not found.")
    return _to_job_data(job)


def poll_heatmap_job(
    session: Session,
    *,
    job_id: UUID,
    settings: Settings | None = None,
    client: FortyGuardClient | None = None,
) -> JobData:
    """Make one bounded provider status request and persist its outcome before returning."""
    settings = settings or get_settings()
    job = session.scalar(
        select(IntegrationJob).where(IntegrationJob.id == job_id).with_for_update()
    )
    if job is None:
        raise JobNotFoundError("The requested job was not found.")
    if job.status in TERMINAL_JOB_STATUSES and not (
        job.status == "completed" and job.error_code == "normalization_failed"
    ):
        return _to_job_data(job)
    if job.provider != "fortyguard" or job.operation != "heatmap":
        raise ValueError("This job is not a FortyGuard heatmap job.")

    now = datetime.now(UTC)
    if now - job.requested_at > timedelta(seconds=settings.fortyguard_max_poll_seconds):
        _mark_timed_out(session=session, job=job, now=now, settings=settings)
        return _to_job_data(job)
    if not job.external_activity_id:
        _mark_failed(
            session=session,
            job=job,
            now=now,
            error_code="missing_activity_id",
            provider_status="unknown",
            audit_event="heatmap.poll_failed",
        )
        return _to_job_data(job)

    provider_client = client or FortyGuardClient(settings)
    try:
        result = provider_client.get_status(job.external_activity_id)
    except FortyGuardConfigurationError:
        raise
    except FortyGuardPollError as exc:
        _record_poll_error(session=session, job=job, now=now, error=exc, settings=settings)
        return _to_job_data(job)

    _persist_poll_result(session=session, job=job, now=now, result=result, settings=settings)
    return _to_job_data(job)


def _persist_poll_result(
    *,
    session: Session,
    job: IntegrationJob,
    now: datetime,
    result: FortyGuardPollResult,
    settings: Settings,
) -> None:
    job.poll_attempts += 1
    job.last_polled_at = now
    job.raw_response_json = _controlled_response(
        response=result.response_payload,
        max_bytes=settings.fortyguard_max_raw_response_bytes,
        provider_status=result.provider_status or "not_found",
    )
    if result.transient_not_found:
        job.status = "processing"
        job.provider_status = "not_found"
        job.error_code = None
        session.commit()
        return

    assert result.provider_status is not None
    normalized_status = result.provider_status.casefold()
    job.provider_status = normalized_status
    job.error_code = None
    if normalized_status in SUCCESS_PROVIDER_STATUSES:
        job.status = "completed"
        job.completed_at = now
        try:
            normalization = normalize_completed_heatmap(
                session,
                job=job,
                provider_response=result.response_payload,
                execution_time=now,
            )
        except HeatmapNormalizationError:
            job.error_code = "normalization_failed"
            record_audit_event(
                session,
                event_type="heatmap.normalization_failed",
                entity_type="integration_job",
                entity_id=job.id,
                payload={"error_code": "normalization_failed"},
            )
        else:
            job.error_code = None
        record_audit_event(
            session,
            event_type="heatmap.poll_completed",
            entity_type="integration_job",
            entity_id=job.id,
            payload={
                "provider_status": normalized_status,
                "poll_attempts": job.poll_attempts,
                "normalization": {
                    "source_run_id": str(normalization.source_run_id),
                    "available_zone_count": normalization.available_zone_count,
                    "missing_zone_count": normalization.missing_zone_count,
                    "no_overlap": normalization.no_overlap,
                    "reused": normalization.reused,
                }
                if job.error_code is None
                else {"status": "failed"},
            },
        )
    elif normalized_status in FAILED_PROVIDER_STATUSES:
        _mark_failed(
            session=session,
            job=job,
            now=now,
            error_code=f"provider_{normalized_status}",
            provider_status=normalized_status,
            audit_event="heatmap.poll_failed",
            commit=False,
        )
    else:
        job.status = "processing"
    session.commit()


def _record_poll_error(
    *,
    session: Session,
    job: IntegrationJob,
    now: datetime,
    error: FortyGuardPollError,
    settings: Settings,
) -> None:
    job.poll_attempts += 1
    job.last_polled_at = now
    job.raw_response_json = _controlled_response(
        response={"poll_error": error.error_code, "retryable": error.retryable},
        max_bytes=settings.fortyguard_max_raw_response_bytes,
        provider_status="unavailable",
    )
    if error.retryable:
        job.status = "processing"
        job.provider_status = "unavailable"
        job.error_code = error.error_code
        record_audit_event(
            session,
            event_type="heatmap.poll_unavailable",
            entity_type="integration_job",
            entity_id=job.id,
            payload={"error_code": error.error_code, "poll_attempts": job.poll_attempts},
        )
        session.commit()
        return
    _mark_failed(
        session=session,
        job=job,
        now=now,
        error_code=error.error_code,
        provider_status="invalid_response",
        audit_event="heatmap.poll_failed",
    )


def _mark_timed_out(
    *, session: Session, job: IntegrationJob, now: datetime, settings: Settings
) -> None:
    job.status = "timed_out"
    job.completed_at = now
    job.error_code = "poll_window_exceeded"
    record_audit_event(
        session,
        event_type="heatmap.poll_timed_out",
        entity_type="integration_job",
        entity_id=job.id,
        payload={"max_poll_seconds": settings.fortyguard_max_poll_seconds},
    )
    session.commit()


def _mark_failed(
    *,
    session: Session,
    job: IntegrationJob,
    now: datetime,
    error_code: str,
    provider_status: str,
    audit_event: str,
    commit: bool = True,
) -> None:
    job.status = "failed"
    job.provider_status = provider_status
    job.error_code = error_code
    job.completed_at = now
    record_audit_event(
        session,
        event_type=audit_event,
        entity_type="integration_job",
        entity_id=job.id,
        payload={"error_code": error_code, "provider_status": provider_status},
    )
    if commit:
        session.commit()


def _controlled_response(
    *, response: dict[str, Any], max_bytes: int, provider_status: str
) -> dict[str, object]:
    """Store a size-limited, scrubbed provider response without credentials or signed URLs."""
    sanitized = _sanitize_value(response)
    serialized = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
    encoded = serialized.encode("utf-8")
    if len(encoded) <= max_bytes:
        return {"truncated": False, "payload": sanitized}
    return {
        "truncated": True,
        "original_safe_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "provider_status": provider_status,
    }


def _sanitize_value(value: Any, *, depth: int = 0) -> object:
    if depth > 8:
        return "[omitted_depth]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]"
            if _is_sensitive_key(str(key))
            else _sanitize_value(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = [_sanitize_value(item, depth=depth + 1) for item in value[:200]]
        if len(value) > 200:
            return {"items": items, "omitted_items": len(value) - 200}
        return items
    if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
        return "[redacted_url]"
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return (
        normalized in {"api_key", "apikey", "key"}
        or normalized.endswith("_key")
        or any(part in normalized for part in SENSITIVE_KEY_PARTS)
    )


def _to_job_data(job: IntegrationJob) -> JobData:
    return JobData(
        job_id=job.id,
        provider=job.provider,
        operation=job.operation,
        status=job.status,
        provider_status=job.provider_status,
        activity_id=job.external_activity_id,
        requested_at=job.requested_at,
        completed_at=job.completed_at,
        last_polled_at=job.last_polled_at,
        poll_attempts=job.poll_attempts,
        error_code=job.error_code,
        raw_response_available=job.raw_response_json is not None,
    )

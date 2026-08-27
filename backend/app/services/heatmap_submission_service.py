"""Idempotent persistence and submission workflow for FortyGuard heatmap tasks."""

from datetime import UTC, date, datetime, time, timedelta

from geoalchemy2.shape import from_shape, to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.heatmap_run import HeatmapRun
from app.db.models.integration_job import IntegrationJob
from app.schemas.heatmaps import HeatmapJobData, HeatmapSubmitRequest
from app.services.audit_service import record_audit_event
from app.services.fortyguard_client import (
    FortyGuardClient,
    FortyGuardError,
    FortyGuardRequestError,
    HeatmapProviderRequest,
    canonical_request_hash,
)
from app.services.heatmap_submission_geometry import (
    HeatmapGeometryError,
    NormalizedHeatmapAoi,
    normalize_heatmap_aoi,
)

FORTYGUARD_PROVIDER = "fortyguard"
HEATMAP_OPERATION = "heatmap"
REUSABLE_JOB_STATUSES = {"submitting", "submitted", "processing", "completed", "succeeded"}


class HeatmapValidationError(ValueError):
    """Raised when a request is outside the MVP's safe local/provider constraints."""


class HeatmapNotReadyError(Exception):
    """Raised when the configured city boundary is not available for AOI validation."""


class HeatmapDuplicateError(Exception):
    """Raised when a previous failed submission has already reserved the same input hash."""


def submit_heatmap(
    session: Session,
    *,
    payload: HeatmapSubmitRequest,
    settings: Settings | None = None,
    client: FortyGuardClient | None = None,
) -> HeatmapJobData:
    """Reserve, submit, and persist one heatmap job without waiting for its final result."""
    settings = settings or get_settings()
    city = _get_demo_city(session=session, settings=settings)
    granularity = payload.granularity or settings.fortyguard_default_granularity
    try:
        normalized_aoi = normalize_heatmap_aoi(payload.polygon_aoi)
        _validate_submission(
            payload=payload,
            aoi=normalized_aoi,
            city=city,
            settings=settings,
        )
    except (HeatmapGeometryError, HeatmapValidationError) as exc:
        _record_validation_failure(session=session, city=city, reason=str(exc))
        raise HeatmapValidationError(str(exc)) from exc

    provider_request = HeatmapProviderRequest(
        polygon_aoi=normalized_aoi.provider_geojson,
        date_time=payload.date_time.to_provider_payload(),
        granularity=granularity,
        analytic_type=payload.analytic_type,
    )
    request_hash = canonical_request_hash(provider_request)
    existing_job = session.scalar(
        select(IntegrationJob).where(
            IntegrationJob.provider == FORTYGUARD_PROVIDER,
            IntegrationJob.request_hash == request_hash,
        )
    )
    if existing_job is not None:
        if existing_job.status in REUSABLE_JOB_STATUSES:
            return _to_job_data(existing_job, reused=True)
        raise HeatmapDuplicateError(
            "This heatmap input already has a previous failed submission and will not be resent "
            "automatically. Change the input or inspect the audit history."
        )

    provider_client = client or FortyGuardClient(settings)
    requested_at = datetime.now(UTC)
    job = IntegrationJob(
        provider=FORTYGUARD_PROVIDER,
        operation=HEATMAP_OPERATION,
        status="submitting",
        request_hash=request_hash,
        requested_at=requested_at,
    )
    session.add(job)
    session.flush()
    session.add(
        HeatmapRun(
            job_id=job.id,
            requested_time=payload.date_time.requested_time_utc(),
            granularity_m=granularity,
            analytic_type=payload.analytic_type,
            aoi_geometry=from_shape(normalized_aoi.normalized_geometry.shape, srid=4326),
            date_time_json=provider_request.date_time,
            source_kind="live",
        )
    )
    record_audit_event(
        session,
        event_type="heatmap.submission_started",
        entity_type="integration_job",
        entity_id=job.id,
        payload={
            "provider": FORTYGUARD_PROVIDER,
            "operation": HEATMAP_OPERATION,
            "request_hash": request_hash,
            "granularity_m": granularity,
            "analytic_type": payload.analytic_type,
            "aoi_area_sq_mi": round(normalized_aoi.area_sq_mi, 4),
        },
    )
    session.commit()

    try:
        submission = provider_client.submit_heatmap(provider_request)
    except FortyGuardError as exc:
        _mark_submission_failed(session=session, job=job, error=exc)
        raise

    job.external_activity_id = submission.activity_id
    job.status = "submitted"
    record_audit_event(
        session,
        event_type="heatmap.submitted",
        entity_type="integration_job",
        entity_id=job.id,
        payload={
            "provider": FORTYGUARD_PROVIDER,
            "operation": HEATMAP_OPERATION,
            "request_hash": request_hash,
            "activity_id": submission.activity_id,
        },
    )
    session.commit()
    session.refresh(job)
    return _to_job_data(job, reused=False)


def _get_demo_city(*, session: Session, settings: Settings) -> City:
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None or city.geometry is None:
        raise HeatmapNotReadyError(
            "The configured demo city and its boundary are required. Run seed_city first."
        )
    return city


def _validate_submission(
    *,
    payload: HeatmapSubmitRequest,
    aoi: NormalizedHeatmapAoi,
    city: City,
    settings: Settings,
) -> None:
    if aoi.area_sq_mi > settings.fortyguard_max_heatmap_area_sq_mi:
        raise HeatmapValidationError(
            "The heatmap AOI is "
            f"{aoi.area_sq_mi:.2f} sq mi, above the configured "
            f"{settings.fortyguard_max_heatmap_area_sq_mi:.2f} sq mi limit."
        )
    city_boundary = to_shape(city.geometry)
    if not city_boundary.covers(aoi.normalized_geometry.shape):
        raise HeatmapValidationError(
            "The heatmap AOI must be fully inside the configured demo city."
        )
    _validate_date_time(payload=payload, settings=settings)


def _validate_date_time(*, payload: HeatmapSubmitRequest, settings: Settings) -> None:
    date_time = payload.date_time
    earliest_date = date(2019, 1, 1)
    if date_time.start_date < earliest_date:
        raise HeatmapValidationError("FortyGuard heatmaps are available from 2019-01-01 onward.")
    if date_time.filter_type == 4:
        assert date_time.end_date is not None
        if date_time.end_date - date_time.start_date > timedelta(days=31):
            raise HeatmapValidationError("filter_type 4 heatmap ranges cannot exceed 31 days.")

    latest_time = _latest_requested_time(payload)
    max_allowed_time = datetime.now(UTC) + timedelta(hours=settings.fortyguard_max_forecast_hours)
    if latest_time > max_allowed_time:
        raise HeatmapValidationError(
            "The heatmap request is beyond the configured FortyGuard forecast window."
        )


def _latest_requested_time(payload: HeatmapSubmitRequest) -> datetime:
    date_time = payload.date_time
    if date_time.filter_type == 2:
        assert date_time.end_time is not None
        return datetime.combine(date_time.start_date, date_time.end_time, tzinfo=UTC)
    if date_time.filter_type == 4:
        assert date_time.end_date is not None
        return datetime.combine(date_time.end_date, time.max, tzinfo=UTC)
    return date_time.requested_time_utc()


def _record_validation_failure(*, session: Session, city: City, reason: str) -> None:
    record_audit_event(
        session,
        event_type="heatmap.validation_failed",
        entity_type="city",
        entity_id=city.id,
        payload={"provider": FORTYGUARD_PROVIDER, "operation": HEATMAP_OPERATION, "reason": reason},
    )
    session.commit()


def _mark_submission_failed(
    *, session: Session, job: IntegrationJob, error: FortyGuardError
) -> None:
    job.status = "submission_failed"
    job.completed_at = datetime.now(UTC)
    job.error_code = (
        error.error_code if isinstance(error, FortyGuardRequestError) else "invalid_response"
    )
    record_audit_event(
        session,
        event_type="heatmap.submission_failed",
        entity_type="integration_job",
        entity_id=job.id,
        payload={"provider": FORTYGUARD_PROVIDER, "error_code": job.error_code},
    )
    session.commit()


def _to_job_data(job: IntegrationJob, *, reused: bool) -> HeatmapJobData:
    return HeatmapJobData(
        job_id=job.id,
        status=job.status,
        activity_id=job.external_activity_id,
        request_hash=job.request_hash,
        requested_at=job.requested_at,
        reused=reused,
    )

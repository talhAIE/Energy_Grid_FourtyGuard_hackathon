from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.jobs import JobResponse
from app.services.fortyguard_client import FortyGuardConfigurationError
from app.services.heatmap_polling_service import JobNotFoundError, get_job, poll_heatmap_job

router = APIRouter()


@router.get("/{job_id}", response_model=JobResponse, summary="Get stored heatmap job state")
def get_job_by_id(
    job_id: UUID,
    session: Session = Depends(get_db_session),
) -> JobResponse:
    """Return stored state only; raw provider responses and credentials are never exposed."""
    try:
        job = get_job(session=session, job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": str(exc)},
        ) from exc
    return JobResponse(data=job)


@router.post("/{job_id}/poll", response_model=JobResponse, summary="Poll a heatmap task once")
def post_job_poll(
    job_id: UUID,
    session: Session = Depends(get_db_session),
) -> JobResponse:
    """Make one provider request and return immediately; callers schedule subsequent polls."""
    try:
        job = poll_heatmap_job(session=session, job_id=job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": str(exc)},
        ) from exc
    except FortyGuardConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "fortyguard_not_configured", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_job_for_polling", "message": str(exc)},
        ) from exc
    return JobResponse(data=job)

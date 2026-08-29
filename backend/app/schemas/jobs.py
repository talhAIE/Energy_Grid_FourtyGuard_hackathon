from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import DataModeResponse


class JobData(BaseModel):
    """Safe persisted job state. Raw provider responses remain server-side only."""

    job_id: UUID
    provider: str
    operation: str
    status: str
    provider_status: str | None
    activity_id: str | None
    requested_at: datetime
    completed_at: datetime | None
    last_polled_at: datetime | None
    poll_attempts: int
    error_code: str | None
    raw_response_available: bool


class JobResponse(DataModeResponse):
    data: JobData

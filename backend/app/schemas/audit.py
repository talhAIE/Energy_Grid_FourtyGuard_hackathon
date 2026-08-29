from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import DataModeResponse


class AuditEventData(BaseModel):
    """Safe, redacted representation of an append-only audit event."""

    id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    payload: dict[str, Any]
    created_at: datetime


class AuditEventListResponse(DataModeResponse):
    data: list[AuditEventData]
    count: int
    total: int
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)

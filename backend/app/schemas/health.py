from datetime import datetime

from pydantic import Field

from app.schemas.common import DataModeResponse


class HealthResponse(DataModeResponse):
    """Public, non-sensitive application health response."""

    status: str
    service: str
    environment: str
    timestamp: datetime
    replay_mode: bool
    dependencies: dict[str, str] = Field(default_factory=dict)

from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Public, non-sensitive application health response."""

    status: str
    service: str
    environment: str
    timestamp: datetime
    replay_mode: bool
    dependencies: dict[str, str] = Field(default_factory=dict)


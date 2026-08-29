from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import DataModeResponse
from app.schemas.heatmaps import HeatmapSubmitRequest


class CycleRunRequest(BaseModel):
    """One validated heatmap request to submit/reuse and advance exactly once."""

    heatmap: HeatmapSubmitRequest


class CycleData(BaseModel):
    id: UUID
    trigger_source: Literal["manual", "demo"]
    status: Literal["submitted", "processing", "completed", "failed", "blocked"]
    job_id: UUID
    job_status: str
    provider_status: str | None
    activity_id: str | None
    forecast_for: datetime
    started_at: datetime
    last_advanced_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    poll_attempts: int
    data_freshness_status: Literal["fresh", "stale", "unavailable"]
    zone_forecast_count: int
    recommendation_count: int
    reused: bool


class CycleResponse(DataModeResponse):
    data: CycleData

from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import DataModeResponse


class ReplayLoadData(BaseModel):
    scenario: str
    cycle_id: UUID
    job_id: UUID
    zone_forecast_count: int
    recommendations_created_count: int
    recommendations_reused_count: int
    reused: bool


class ReplayLoadResponse(DataModeResponse):
    data: ReplayLoadData

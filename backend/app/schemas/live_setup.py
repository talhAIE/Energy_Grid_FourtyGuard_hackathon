"""Schemas for the bounded live dashboard initialization flow."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import DataModeResponse
from app.schemas.heatmaps import HeatmapJobData


class LiveZoneSampleData(BaseModel):
    zone_id: UUID
    zone_code: str
    zone_name: str
    job: HeatmapJobData


class LiveSetupData(BaseModel):
    forecast_for: datetime
    model_version: str
    model_quality_policy: str
    model_reused: bool
    samples: list[LiveZoneSampleData]


class LiveSetupResponse(DataModeResponse):
    data: LiveSetupData

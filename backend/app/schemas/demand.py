from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import DataModeResponse


class EiaImportRequest(BaseModel):
    """A bounded historical time range for a configured EIA demand import."""

    start: datetime = Field(description="Inclusive ISO-8601 start time. UTC is recommended.")
    end: datetime = Field(description="Inclusive ISO-8601 end time. UTC is recommended.")


class DemandObservationData(BaseModel):
    """Public normalized demand observation, always represented in UTC."""

    id: UUID
    city_id: UUID
    period_utc: datetime
    source: str
    source_area_code: str
    demand_mw: Decimal
    is_actual: bool
    quality_flag: str | None


class EiaImportResultData(BaseModel):
    source: str
    source_area_code: str
    start_utc: datetime
    end_utc: datetime
    fetched_count: int
    created_count: int
    skipped_duplicate_count: int


class EiaImportResponse(DataModeResponse):
    data: EiaImportResultData


class DemandObservationListResponse(DataModeResponse):
    data: list[DemandObservationData]
    count: int

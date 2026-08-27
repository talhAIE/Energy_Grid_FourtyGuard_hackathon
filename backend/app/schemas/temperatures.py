from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ZoneTemperatureData(BaseModel):
    """A traceable, normalized zone temperature observation or explicit missing marker."""

    id: UUID
    zone_id: UUID
    observed_for: datetime
    mean_c: Decimal | None
    min_c: Decimal | None
    max_c: Decimal | None
    stddev_c: Decimal | None
    tile_count: int
    source_run_id: UUID
    is_forecast: bool
    data_status: str
    source_retrieved_at: datetime


class ZoneTemperatureListResponse(BaseModel):
    data: list[ZoneTemperatureData]
    count: int

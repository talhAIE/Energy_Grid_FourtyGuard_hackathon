from datetime import UTC, date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class HeatmapDateTime(BaseModel):
    """FortyGuard heatmap date filters, interpreted as UTC by this backend."""

    start_date: date
    filter_type: Literal[1, 2, 3, 4] = 1
    start_time: time | None = None
    end_time: time | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_filter_fields(self) -> "HeatmapDateTime":
        if self.filter_type == 1:
            if self.start_time is None:
                raise ValueError("filter_type 1 requires start_time.")
            if self.end_time is not None or self.end_date is not None:
                raise ValueError("filter_type 1 accepts only start_date and start_time.")
        if self.filter_type == 2:
            if self.start_time is None or self.end_time is None:
                raise ValueError("filter_type 2 requires start_time and end_time.")
            if self.end_time <= self.start_time:
                raise ValueError("filter_type 2 end_time must be later than start_time.")
            if self.end_date is not None:
                raise ValueError("filter_type 2 uses times from one start_date only.")
        if self.filter_type == 3 and any(
            value is not None for value in (self.start_time, self.end_time, self.end_date)
        ):
            raise ValueError("filter_type 3 accepts only start_date.")
        if self.filter_type == 4:
            if self.end_date is None:
                raise ValueError("filter_type 4 requires end_date.")
            if self.end_date < self.start_date:
                raise ValueError("filter_type 4 end_date cannot be before start_date.")
            if self.start_time is not None or self.end_time is not None:
                raise ValueError("filter_type 4 accepts dates, not times.")
        return self

    def requested_time_utc(self) -> datetime:
        """Return a stable UTC timestamp representing the beginning of this request."""
        return datetime.combine(self.start_date, self.start_time or time.min, tzinfo=UTC)

    def to_provider_payload(self) -> dict[str, str | int]:
        """Create only the documented date-time fields required by the selected filter."""
        payload: dict[str, str | int] = {
            "start_date": self.start_date.isoformat(),
            "filter_type": self.filter_type,
        }
        if self.start_time is not None:
            payload["start_time"] = self.start_time.strftime("%H:%M")
        if self.end_time is not None:
            payload["end_time"] = self.end_time.strftime("%H:%M")
        if self.end_date is not None:
            payload["end_date"] = self.end_date.isoformat()
        return payload


class HeatmapSubmitRequest(BaseModel):
    """A small, validated live temperature-map request for the configured demo city."""

    polygon_aoi: dict[str, Any] = Field(
        description="One GeoJSON FeatureCollection containing one closed Polygon AOI."
    )
    date_time: HeatmapDateTime
    granularity: Literal[60, 80, 100] | None = Field(
        default=None,
        description="Tile size in metres. Defaults to FORTYGUARD_DEFAULT_GRANULARITY.",
    )
    analytic_type: Literal["tcm"] = "tcm"


class HeatmapJobData(BaseModel):
    job_id: UUID
    status: str
    activity_id: str | None
    request_hash: str
    requested_at: datetime
    reused: bool


class HeatmapSubmitResponse(BaseModel):
    data: HeatmapJobData

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import DataModeResponse


class ZoneCreate(BaseModel):
    """Development request to create an operational zone in the configured city."""

    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_]+$")
    geometry: dict[str, Any]
    allocation_weight: Decimal = Field(gt=0, le=1)
    active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class OperationalGridRequest(BaseModel):
    """A bounded, approved planning-grid request for the demo analysis boundary."""

    columns: int = Field(default=4, ge=1, le=6)
    rows: int = Field(default=2, ge=1, le=6)

    @field_validator("rows")
    @classmethod
    def validate_zone_count(cls, rows: int, info) -> int:
        columns = info.data.get("columns", 6)
        if not 4 <= columns * rows <= 12:
            raise ValueError("columns × rows must create between 4 and 12 operational zones.")
        return rows


class ZoneData(BaseModel):
    """Public zone representation consumed by the future map dashboard."""

    id: UUID
    city_id: UUID
    name: str
    code: str
    geometry: dict[str, Any]
    active: bool
    allocation_weight: Decimal


class ZoneResponse(DataModeResponse):
    data: ZoneData


class ZoneListResponse(DataModeResponse):
    data: list[ZoneData]


class OperationalGridResponse(DataModeResponse):
    data: dict[str, int]

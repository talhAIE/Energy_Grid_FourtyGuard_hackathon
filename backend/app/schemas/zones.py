from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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


class ZoneData(BaseModel):
    """Public zone representation consumed by the future map dashboard."""

    id: UUID
    city_id: UUID
    name: str
    code: str
    geometry: dict[str, Any]
    active: bool
    allocation_weight: Decimal


class ZoneResponse(BaseModel):
    data: ZoneData


class ZoneListResponse(BaseModel):
    data: list[ZoneData]

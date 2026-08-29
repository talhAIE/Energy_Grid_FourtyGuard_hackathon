from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel


class ZoneForecastData(BaseModel):
    """One zone-level proxy demand allocation and explainable risk result."""

    id: UUID
    zone_id: UUID
    forecast_for: datetime
    generated_at: datetime
    model_version: str
    estimate_type: Literal["proxy"] = "proxy"
    city_forecast_mw: Decimal
    allocation_weight: Decimal
    temperature_c: Decimal
    city_temperature_c: Decimal
    heat_anomaly_c: Decimal
    temperature_ramp_c_per_hour: Decimal | None
    temperature_stddev_c: Decimal | None
    baseline_mw: Decimal
    predicted_mw: Decimal
    uplift_pct: Decimal
    uncertainty_penalty: Decimal
    risk_score: Decimal
    risk_level: Literal["low", "watch", "high", "critical"]
    confidence: Literal["low", "medium", "high"]
    data_freshness_status: Literal["fresh", "stale"]
    explanation: dict[str, Any]


class ZoneForecastSetData(BaseModel):
    forecast_for: datetime
    generated_at: datetime
    model_version: str
    city_forecast_mw: Decimal
    estimate_type: Literal["proxy"] = "proxy"
    forecasts: list[ZoneForecastData]


class ZoneForecastSetResponse(BaseModel):
    data: ZoneForecastSetData


class ZoneForecastTimelineResponse(BaseModel):
    data: list[ZoneForecastData]
    count: int

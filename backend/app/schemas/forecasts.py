from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.recommendations import RecommendationEligibilityData


class ForecastRunRequest(BaseModel):
    """Optional requested UTC forecast slot; omit it to use the next available temperature slot."""

    forecast_for: datetime | None = Field(
        default=None,
        description="Optional ISO-8601 forecast time. UTC is recommended.",
    )


class ActiveModelData(BaseModel):
    version: str
    algorithm: str
    source_dataset_version: str
    feature_schema_version: str
    quality_policy: str
    feature_columns: list[str]
    trained_from: datetime
    trained_to: datetime
    training_row_count: int
    validation_row_count: int
    mae_mw: Decimal
    rmse_mw: Decimal
    mape_percent: Decimal | None
    activated_at: datetime | None


class ActiveModelResponse(BaseModel):
    data: ActiveModelData


class ForecastRunData(BaseModel):
    model_version: str
    algorithm: str
    forecast_for: datetime
    predicted_demand_mw: Decimal
    estimate_type: Literal["estimate"] = "estimate"
    prediction_was_clamped: bool
    city_temperature_c: Decimal
    cooling_degree_hours: Decimal
    temperature_source_kind: Literal["actual", "forecast", "mixed"]
    feature_quality_status: Literal["complete"] = "complete"
    lag_demand_1h_mw: Decimal
    lag_demand_24h_mw: Decimal
    zone_forecast_count: int
    zone_forecasts_reused: bool
    recommendations_created_count: int
    recommendations_reused_count: int
    recommendation_eligibility: list[RecommendationEligibilityData]


class ForecastRunResponse(BaseModel):
    data: ForecastRunData

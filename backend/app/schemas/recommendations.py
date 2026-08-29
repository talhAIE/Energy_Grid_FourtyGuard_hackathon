from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import DataModeResponse

RecommendationActionCode = Literal[
    "monitor_and_recheck",
    "verify_reserve_and_prepare_voluntary_demand_response",
    "escalate_duty_operator_and_review_approved_response_plan",
]
RecommendationStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "deferred",
    "expired",
    "superseded",
]
RecommendationDecisionValue = Literal["approved", "rejected", "deferred"]


class RecommendationActionData(BaseModel):
    code: RecommendationActionCode
    label: str
    safety_boundary: str


class RecommendationData(BaseModel):
    """A machine-generated decision-support recommendation and its traceable evidence."""

    id: UUID
    zone_forecast_id: UUID
    zone_id: UUID
    forecast_for: datetime
    risk_score: Decimal
    risk_level: Literal["watch", "high", "critical"]
    confidence: Literal["medium", "high"]
    data_freshness_status: Literal["fresh"]
    estimate_type: Literal["proxy"]
    action: RecommendationActionData
    status: RecommendationStatus
    reason: dict[str, Any]
    evidence: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    superseded_at: datetime | None
    decided_at: datetime | None


class RecommendationListResponse(DataModeResponse):
    data: list[RecommendationData]
    count: int
    total: int
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class RecommendationDecisionRequest(BaseModel):
    decision: RecommendationDecisionValue
    operator_name: str = Field(min_length=2, max_length=120)
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("operator_name")
    @classmethod
    def normalize_operator_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("operator_name must contain at least two non-space characters.")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class RecommendationDecisionData(BaseModel):
    id: UUID
    recommendation_id: UUID
    decision: RecommendationDecisionValue
    operator_name: str
    note: str | None
    decided_at: datetime


class RecommendationDecisionResponse(DataModeResponse):
    data: RecommendationDecisionData


class RecommendationEligibilityData(BaseModel):
    zone_id: UUID
    zone_forecast_id: UUID
    eligible: bool
    reason_code: str

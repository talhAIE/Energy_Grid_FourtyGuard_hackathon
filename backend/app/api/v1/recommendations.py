from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.recommendations import (
    RecommendationData,
    RecommendationDecisionData,
    RecommendationDecisionRequest,
    RecommendationDecisionResponse,
    RecommendationListResponse,
    RecommendationStatus,
)
from app.services.recommendation_service import (
    RecommendationDecisionConflictError,
    RecommendationError,
    RecommendationNotFoundError,
    action_definition,
    list_recommendations,
    record_recommendation_decision,
)

router = APIRouter()


@router.get(
    "",
    response_model=RecommendationListResponse,
    summary="List decision-support recommendations",
)
def get_recommendations(
    recommendation_status: RecommendationStatus | None = Query(default=None, alias="status"),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    session: Session = Depends(get_db_session),
) -> RecommendationListResponse:
    """Return recommendations only; this endpoint never executes or dispatches an action."""
    try:
        records, total = list_recommendations(
            session=session,
            status=recommendation_status,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
    except RecommendationError as exc:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_recommendation_filter",
            str(exc),
        ) from exc
    return RecommendationListResponse(
        data=[_to_data(record) for record in records],
        count=len(records),
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{recommendation_id}/decision",
    response_model=RecommendationDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record one immutable human decision",
)
def post_recommendation_decision(
    recommendation_id: UUID,
    payload: RecommendationDecisionRequest,
    session: Session = Depends(get_db_session),
) -> RecommendationDecisionResponse:
    """Record approve/reject/defer only; it never performs the proposed operational action."""
    try:
        decision = record_recommendation_decision(
            session=session,
            recommendation_id=recommendation_id,
            decision=payload.decision,
            operator_name=payload.operator_name,
            note=payload.note,
        )
    except RecommendationNotFoundError as exc:
        raise _http_error(status.HTTP_404_NOT_FOUND, "recommendation_not_found", str(exc)) from exc
    except RecommendationDecisionConflictError as exc:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "recommendation_not_decidable",
            str(exc),
        ) from exc
    return RecommendationDecisionResponse(
        data=RecommendationDecisionData(
            id=decision.id,
            recommendation_id=decision.recommendation_id,
            decision=decision.decision,
            operator_name=decision.operator_name,
            note=decision.note,
            decided_at=decision.decided_at,
        )
    )


def _to_data(record) -> RecommendationData:
    recommendation = record.recommendation
    forecast = record.zone_forecast
    action = action_definition(recommendation.action_code)
    return RecommendationData(
        id=recommendation.id,
        zone_forecast_id=forecast.id,
        zone_id=forecast.zone_id,
        forecast_for=forecast.forecast_for,
        risk_score=forecast.risk_score,
        risk_level=forecast.risk_level,
        confidence=forecast.confidence,
        data_freshness_status=forecast.data_freshness_status,
        estimate_type=forecast.estimate_type,
        action={
            "code": action.code,
            "label": action.label,
            "safety_boundary": action.safety_boundary,
        },
        status=recommendation.status,
        reason=recommendation.reason_json,
        evidence=recommendation.evidence_json,
        created_at=recommendation.created_at,
        expires_at=recommendation.expires_at,
        superseded_at=recommendation.superseded_at,
        decided_at=recommendation.decided_at,
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})

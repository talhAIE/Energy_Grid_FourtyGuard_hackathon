"""Create bounded recommendations and immutable human decisions from zone-risk forecasts."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.recommendation import Recommendation
from app.db.models.recommendation_decision import RecommendationDecision
from app.db.models.zone_forecast import ZoneForecast
from app.services.audit_service import record_audit_event

ACTIVE_RECOMMENDATION_STATUS = "pending"
FINAL_RECOMMENDATION_STATUSES = {"approved", "rejected", "deferred", "expired", "superseded"}
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class ActionDefinition:
    code: str
    label: str
    safety_boundary: str


ACTION_CATALOG: dict[str, ActionDefinition] = {
    "watch": ActionDefinition(
        code="monitor_and_recheck",
        label="Monitor conditions and schedule a re-check.",
        safety_boundary=(
            "Observation only; no customer, market, or grid-control action is performed."
        ),
    ),
    "high": ActionDefinition(
        code="verify_reserve_and_prepare_voluntary_demand_response",
        label="Verify reserve capacity and prepare voluntary demand-response options.",
        safety_boundary=(
            "Preparation only; any operational or customer action requires separate approval."
        ),
    ),
    "critical": ActionDefinition(
        code="escalate_duty_operator_and_review_approved_response_plan",
        label="Escalate to the duty operator and review the approved response plan.",
        safety_boundary=(
            "Escalation and review only; this service never dispatches or controls equipment."
        ),
    ),
}


class RecommendationError(ValueError):
    """Raised when recommendation inputs or filters are invalid."""


class RecommendationNotFoundError(Exception):
    """Raised when a recommendation ID does not exist."""


class RecommendationDecisionConflictError(Exception):
    """Raised when a recommendation is no longer eligible for a first immutable decision."""


@dataclass(frozen=True)
class RecommendationEligibility:
    zone_id: UUID
    zone_forecast_id: UUID
    eligible: bool
    reason_code: str


@dataclass(frozen=True)
class RecommendationGenerationResult:
    recommendations: list[Recommendation]
    eligibility: list[RecommendationEligibility]
    created_count: int
    reused_count: int


@dataclass(frozen=True)
class RecommendationRecord:
    recommendation: Recommendation
    zone_forecast: ZoneForecast


def generate_recommendations(
    session: Session,
    *,
    zone_forecasts: list[ZoneForecast],
    settings: Settings | None = None,
) -> RecommendationGenerationResult:
    """Evaluate one set of forecasts without ever triggering an external or grid action."""
    settings = settings or get_settings()
    now = datetime.now(UTC)
    _expire_pending_recommendations(session=session, now=now)
    created: list[Recommendation] = []
    eligibility: list[RecommendationEligibility] = []
    reused_count = 0

    for forecast in zone_forecasts:
        existing = session.scalar(
            select(Recommendation).where(Recommendation.zone_forecast_id == forecast.id)
        )
        if existing is not None:
            eligibility.append(
                RecommendationEligibility(
                    zone_id=forecast.zone_id,
                    zone_forecast_id=forecast.id,
                    eligible=existing.status == ACTIVE_RECOMMENDATION_STATUS,
                    reason_code=(
                        "recommendation_already_pending"
                        if existing.status == ACTIVE_RECOMMENDATION_STATUS
                        else "recommendation_already_finalized"
                    ),
                )
            )
            reused_count += 1
            continue

        result = evaluate_recommendation_eligibility(
            forecast=forecast,
            now=now,
            settings=settings,
        )
        eligibility.append(result)
        _supersede_prior_pending_recommendations(
            session=session,
            forecast=forecast,
            now=now,
            reason_code=("new_eligible_forecast" if result.eligible else "new_ineligible_forecast"),
        )
        if not result.eligible:
            record_audit_event(
                session,
                event_type="recommendation.ineligible",
                entity_type="zone_forecast",
                entity_id=forecast.id,
                payload={
                    "zone_id": str(forecast.zone_id),
                    "reason_code": result.reason_code,
                    "risk_score": _decimal_text(forecast.risk_score),
                    "confidence": forecast.confidence,
                    "data_freshness_status": forecast.data_freshness_status,
                },
            )
            continue

        action = _action_for(forecast.risk_level)
        recommendation = Recommendation(
            zone_forecast_id=forecast.id,
            action_code=action.code,
            status=ACTIVE_RECOMMENDATION_STATUS,
            reason_json=_reason(forecast=forecast, action=action),
            evidence_json=_evidence(forecast=forecast),
            expires_at=min(
                now + timedelta(minutes=settings.recommendation_expiry_minutes),
                _ensure_utc(forecast.forecast_for),
            ),
        )
        session.add(recommendation)
        session.flush()
        record_audit_event(
            session,
            event_type="recommendation.created",
            entity_type="recommendation",
            entity_id=recommendation.id,
            payload={
                "zone_forecast_id": str(forecast.id),
                "zone_id": str(forecast.zone_id),
                "action_code": action.code,
                "risk_level": forecast.risk_level,
                "risk_score": _decimal_text(forecast.risk_score),
                "expires_at": _ensure_utc(recommendation.expires_at).isoformat(),
            },
        )
        created.append(recommendation)

    session.commit()
    for recommendation in created:
        session.refresh(recommendation)
    return RecommendationGenerationResult(
        recommendations=created,
        eligibility=eligibility,
        created_count=len(created),
        reused_count=reused_count,
    )


def evaluate_recommendation_eligibility(
    *,
    forecast: ZoneForecast,
    now: datetime,
    settings: Settings,
) -> RecommendationEligibility:
    """Return the first explicit policy reason; recommendations require every guardrail to pass."""
    reason_code = "eligible"
    if forecast.estimate_type != "proxy":
        reason_code = "unsupported_estimate_type"
    elif _ensure_utc(forecast.forecast_for) <= now:
        reason_code = "forecast_not_future"
    elif forecast.data_freshness_status != "fresh":
        reason_code = "stale_temperature_data"
    elif CONFIDENCE_RANK.get(forecast.confidence, -1) < CONFIDENCE_RANK[
        settings.recommendation_min_confidence
    ]:
        reason_code = "insufficient_confidence"
    elif Decimal(forecast.risk_score) < settings.recommendation_min_risk_score:
        reason_code = "risk_below_threshold"
    elif forecast.risk_level not in ACTION_CATALOG:
        reason_code = "risk_level_not_actionable"
    return RecommendationEligibility(
        zone_id=forecast.zone_id,
        zone_forecast_id=forecast.id,
        eligible=reason_code == "eligible",
        reason_code=reason_code,
    )


def list_recommendations(
    session: Session,
    *,
    status: str | None = None,
    include_inactive: bool = False,
) -> list[RecommendationRecord]:
    """List stored recommendations after safely expiring any pending item past its deadline."""
    if status is not None and status not in {
        ACTIVE_RECOMMENDATION_STATUS,
        *FINAL_RECOMMENDATION_STATUSES,
    }:
        raise RecommendationError("Recommendation status filter is not supported.")
    _expire_pending_recommendations(session=session, now=datetime.now(UTC), commit=True)
    statement = select(Recommendation, ZoneForecast).join(
        ZoneForecast,
        Recommendation.zone_forecast_id == ZoneForecast.id,
    )
    if status is not None:
        statement = statement.where(Recommendation.status == status)
    elif not include_inactive:
        statement = statement.where(Recommendation.status == ACTIVE_RECOMMENDATION_STATUS)
    rows = session.execute(
        statement.order_by(Recommendation.expires_at, Recommendation.created_at.desc())
    ).all()
    return [RecommendationRecord(recommendation=item[0], zone_forecast=item[1]) for item in rows]


def record_recommendation_decision(
    session: Session,
    *,
    recommendation_id: UUID,
    decision: Literal["approved", "rejected", "deferred"],
    operator_name: str,
    note: str | None,
) -> RecommendationDecision:
    """Record one irreversible human decision; this does not execute the recommended action."""
    recommendation = session.scalar(
        select(Recommendation)
        .where(Recommendation.id == recommendation_id)
        .with_for_update()
    )
    if recommendation is None:
        raise RecommendationNotFoundError("The requested recommendation was not found.")
    now = datetime.now(UTC)
    if (
        recommendation.status == ACTIVE_RECOMMENDATION_STATUS
        and _ensure_utc(recommendation.expires_at) <= now
    ):
        _expire_recommendation(session=session, recommendation=recommendation, now=now)
        session.commit()
        raise RecommendationDecisionConflictError(
            "The recommendation has expired and cannot be decided."
        )
    if recommendation.status != ACTIVE_RECOMMENDATION_STATUS:
        raise RecommendationDecisionConflictError(
            "A decision cannot be changed or added after this recommendation is no longer pending."
        )

    decision_record = RecommendationDecision(
        recommendation_id=recommendation.id,
        decision=decision,
        operator_name=operator_name.strip(),
        note=note.strip() if note and note.strip() else None,
        decided_at=now,
    )
    session.add(decision_record)
    recommendation.status = decision
    recommendation.decided_at = now
    session.flush()
    record_audit_event(
        session,
        event_type="recommendation.decision_recorded",
        entity_type="recommendation",
        entity_id=recommendation.id,
        payload={
            "decision_id": str(decision_record.id),
            "decision": decision,
            "operator_name": decision_record.operator_name,
            "has_note": decision_record.note is not None,
        },
    )
    session.commit()
    session.refresh(decision_record)
    return decision_record


def action_definition(action_code: str) -> ActionDefinition:
    """Return a known action definition without accepting arbitrary operational instructions."""
    for action in ACTION_CATALOG.values():
        if action.code == action_code:
            return action
    raise RecommendationError("Stored recommendation has an unsupported action code.")


def _supersede_prior_pending_recommendations(
    *,
    session: Session,
    forecast: ZoneForecast,
    now: datetime,
    reason_code: str,
) -> None:
    prior = session.execute(
        select(Recommendation, ZoneForecast)
        .join(ZoneForecast, Recommendation.zone_forecast_id == ZoneForecast.id)
        .where(
            ZoneForecast.zone_id == forecast.zone_id,
            Recommendation.status == ACTIVE_RECOMMENDATION_STATUS,
            Recommendation.zone_forecast_id != forecast.id,
            ZoneForecast.generated_at <= forecast.generated_at,
        )
        .with_for_update()
    ).all()
    for recommendation, prior_forecast in prior:
        recommendation.status = "superseded"
        recommendation.superseded_at = now
        record_audit_event(
            session,
            event_type="recommendation.superseded",
            entity_type="recommendation",
            entity_id=recommendation.id,
            payload={
                "prior_zone_forecast_id": str(prior_forecast.id),
                "replacement_zone_forecast_id": str(forecast.id),
                "reason_code": reason_code,
            },
        )


def _expire_pending_recommendations(
    *,
    session: Session,
    now: datetime,
    commit: bool = False,
) -> None:
    pending = session.scalars(
        select(Recommendation)
        .where(
            Recommendation.status == ACTIVE_RECOMMENDATION_STATUS,
            Recommendation.expires_at <= now,
        )
        .with_for_update()
    ).all()
    for recommendation in pending:
        _expire_recommendation(session=session, recommendation=recommendation, now=now)
    if pending and commit:
        session.commit()


def _expire_recommendation(
    *,
    session: Session,
    recommendation: Recommendation,
    now: datetime,
) -> None:
    recommendation.status = "expired"
    record_audit_event(
        session,
        event_type="recommendation.expired",
        entity_type="recommendation",
        entity_id=recommendation.id,
        payload={"expired_at": now.isoformat()},
    )


def _action_for(risk_level: str) -> ActionDefinition:
    action = ACTION_CATALOG.get(risk_level)
    if action is None:
        raise RecommendationError("A recommendation action is not defined for this risk level.")
    return action


def _reason(*, forecast: ZoneForecast, action: ActionDefinition) -> dict[str, str]:
    return {
        "reason_code": "eligible_forecast_policy_passed",
        "action_code": action.code,
        "risk_level": forecast.risk_level,
        "risk_score": _decimal_text(forecast.risk_score),
        "confidence": forecast.confidence,
        "data_freshness_status": forecast.data_freshness_status,
    }


def _evidence(*, forecast: ZoneForecast) -> dict[str, object]:
    return {
        "estimate_type": forecast.estimate_type,
        "forecast_for": _ensure_utc(forecast.forecast_for).isoformat(),
        "predicted_mw": _decimal_text(forecast.predicted_mw),
        "baseline_mw": _decimal_text(forecast.baseline_mw),
        "uplift_pct": _decimal_text(forecast.uplift_pct),
        "temperature_c": _decimal_text(forecast.temperature_c),
        "heat_anomaly_c": _decimal_text(forecast.heat_anomaly_c),
        "temperature_ramp_c_per_hour": _decimal_text(forecast.temperature_ramp_c_per_hour),
        "uncertainty_penalty": _decimal_text(forecast.uncertainty_penalty),
        "risk_formula": forecast.explanation_json.get("risk", {}),
    }


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None

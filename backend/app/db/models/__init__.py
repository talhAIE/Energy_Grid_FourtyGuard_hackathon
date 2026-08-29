"""SQLAlchemy database models registered for Alembic metadata discovery."""

from app.db.models.audit_event import AuditEvent
from app.db.models.city import City
from app.db.models.demand_observation import DemandObservation
from app.db.models.heatmap_run import HeatmapRun
from app.db.models.integration_job import IntegrationJob
from app.db.models.model_version import ModelVersion
from app.db.models.recommendation import Recommendation
from app.db.models.recommendation_decision import RecommendationDecision
from app.db.models.zone import Zone
from app.db.models.zone_forecast import ZoneForecast
from app.db.models.zone_temperature_observation import ZoneTemperatureObservation

__all__ = [
    "AuditEvent",
    "City",
    "DemandObservation",
    "HeatmapRun",
    "IntegrationJob",
    "ModelVersion",
    "Recommendation",
    "RecommendationDecision",
    "Zone",
    "ZoneForecast",
    "ZoneTemperatureObservation",
]

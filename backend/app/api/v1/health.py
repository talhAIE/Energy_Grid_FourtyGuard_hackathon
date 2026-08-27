from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.db.database import get_database_health
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Check API health")
def get_health() -> HealthResponse:
    """Return public application health without exposing configuration secrets."""
    settings = get_settings()
    database_status = get_database_health()
    overall_status = "healthy" if database_status in {"healthy", "not_configured"} else "degraded"

    return HealthResponse(
        status=overall_status,
        service=settings.app_name,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
        replay_mode=settings.replay_mode,
        dependencies={"database": database_status, "redis": "not_configured"},
    )

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Check API health")
def get_health() -> HealthResponse:
    """Return public application health without exposing configuration secrets."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        environment=settings.app_env,
        timestamp=datetime.now(UTC),
        replay_mode=settings.replay_mode,
        dependencies={"database": "not_configured", "redis": "not_configured"},
    )


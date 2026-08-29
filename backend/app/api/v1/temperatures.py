from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.temperatures import ZoneTemperatureListResponse
from app.services.heatmap_normalization_service import (
    HeatmapNormalizationError,
    list_zone_temperatures,
)

router = APIRouter()


@router.get(
    "",
    response_model=ZoneTemperatureListResponse,
    summary="List normalized zone temperatures",
)
def get_zone_temperatures(
    start: datetime = Query(description="Inclusive ISO-8601 start time. UTC is recommended."),
    end: datetime = Query(description="Inclusive ISO-8601 end time. UTC is recommended."),
    zone_id: UUID | None = Query(default=None),
    include_missing: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    session: Session = Depends(get_db_session),
) -> ZoneTemperatureListResponse:
    """Return stored observations; missing records retain null statistics and a visible status."""
    try:
        observations, total = list_zone_temperatures(
            session=session,
            start=start,
            end=end,
            zone_id=zone_id,
            include_missing=include_missing,
            limit=limit,
            offset=offset,
        )
    except HeatmapNormalizationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_temperature_range", "message": str(exc)},
        ) from exc
    return ZoneTemperatureListResponse(
        data=observations,
        count=len(observations),
        total=total,
        limit=limit,
        offset=offset,
    )

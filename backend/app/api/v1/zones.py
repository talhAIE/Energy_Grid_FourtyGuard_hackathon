from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db_session
from app.schemas.zones import (
    OperationalGridRequest,
    OperationalGridResponse,
    ZoneCreate,
    ZoneListResponse,
    ZoneResponse,
)
from app.services.operational_grid_service import (
    OperationalGridError,
    activate_operational_grid,
)
from app.services.zone_service import (
    ZoneConflictError,
    ZoneNotReadyError,
    ZoneValidationError,
    create_zone,
    list_zones,
)

router = APIRouter()


@router.get("", response_model=ZoneListResponse, summary="List configured operational zones")
def get_zones(
    active_only: bool = Query(default=True),
    session: Session = Depends(get_db_session),
) -> ZoneListResponse:
    """Return zone geometry and allocation weights for the configured demo city."""
    try:
        zones = list_zones(session=session, active_only=active_only)
    except ZoneNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "zone_service_unavailable", "message": str(exc)},
        ) from exc
    return ZoneListResponse(data=zones)


@router.post(
    "",
    response_model=ZoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a zone",
)
def post_zone(
    payload: ZoneCreate,
    session: Session = Depends(get_db_session),
) -> ZoneResponse:
    """Create a zone in development mode after geometry and allocation validation."""
    if get_settings().app_env.lower() not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "zone_creation_disabled",
                "message": "Zone creation is development-only.",
            },
        )

    try:
        zone = create_zone(session=session, payload=payload)
    except ZoneValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_zone", "message": str(exc)},
        ) from exc
    except ZoneConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "zone_conflict", "message": str(exc)},
        ) from exc
    except ZoneNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "zone_service_unavailable", "message": str(exc)},
        ) from exc

    return ZoneResponse(data=zone)


@router.post(
    "/operational-grid",
    response_model=OperationalGridResponse,
    summary="Activate an approved 4–12 zone operational grid",
)
def post_operational_grid(
    payload: OperationalGridRequest,
    session: Session = Depends(get_db_session),
) -> OperationalGridResponse:
    """Activate a provider-size-validated grid without provider calls or dispatch actions."""
    if get_settings().app_env.lower() not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "zone_plan_activation_disabled",
                "message": "Operational-grid activation is development-only.",
            },
        )
    try:
        result = activate_operational_grid(
            session=session,
            columns=payload.columns,
            rows=payload.rows,
        )
    except OperationalGridError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_operational_grid", "message": str(exc)},
        ) from exc
    return OperationalGridResponse(
        data={
            "active_zone_count": result.active_zone_count,
            "deactivated_zone_count": result.deactivated_zone_count,
            "columns": result.columns,
            "rows": result.rows,
        }
    )

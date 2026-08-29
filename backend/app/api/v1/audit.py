from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db_session
from app.schemas.audit import AuditEventData, AuditEventListResponse
from app.services.audit_service import AuditQueryError, list_audit_events, safe_audit_payload

router = APIRouter()


@router.get("", response_model=AuditEventListResponse, summary="List redacted audit history")
def get_audit_events(
    event_type: str | None = Query(default=None, min_length=1, max_length=100),
    entity_type: str | None = Query(default=None, min_length=1, max_length=100),
    entity_id: UUID | None = Query(default=None),
    start: datetime | None = Query(
        default=None,
        description="Inclusive UTC start; defaults to 7 days ago.",
    ),
    end: datetime | None = Query(default=None, description="Inclusive UTC end; defaults to now."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    session: Session = Depends(get_db_session),
) -> AuditEventListResponse:
    """Read bounded audit history without exposing credentials or raw provider payloads."""
    try:
        page = list_audit_events(
            session=session,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
    except AuditQueryError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_audit_range", "message": str(exc)},
        ) from exc
    return AuditEventListResponse(
        data=[
            AuditEventData(
                id=event.id,
                event_type=event.event_type,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                payload=safe_audit_payload(event.payload_json),
                created_at=event.created_at,
            )
            for event in page.events
        ],
        count=len(page.events),
        total=page.total,
        limit=limit,
        offset=offset,
    )

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent


def record_audit_event(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: UUID,
    payload: dict[str, Any],
) -> AuditEvent:
    """Append an event to the audit log as part of the active transaction."""
    event = AuditEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=payload,
    )
    session.add(event)
    return event


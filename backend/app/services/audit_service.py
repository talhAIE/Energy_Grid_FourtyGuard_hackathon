from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.audit_event import AuditEvent

MAX_AUDIT_RANGE_DAYS = 366
MAX_PAYLOAD_DEPTH = 4
MAX_PAYLOAD_ITEMS = 50
MAX_PAYLOAD_STRING_LENGTH = 500
SENSITIVE_KEY_PARTS = ("api_key", "authorization", "password", "secret", "token", "signed")


class AuditQueryError(ValueError):
    """Raised when an audit-history filter would be unsafe or too broad."""


@dataclass(frozen=True)
class AuditEventPage:
    events: list[AuditEvent]
    total: int


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


def list_audit_events(
    session: Session,
    *,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AuditEventPage:
    """Return a bounded, newest-first page of safe audit events without mutating them."""
    start_utc, end_utc = _audit_time_range(start=start, end=end)
    statement = select(AuditEvent).where(
        AuditEvent.created_at >= start_utc,
        AuditEvent.created_at <= end_utc,
    )
    if event_type is not None:
        statement = statement.where(AuditEvent.event_type == event_type)
    if entity_type is not None:
        statement = statement.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditEvent.entity_id == entity_id)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    events = session.scalars(
        statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return AuditEventPage(events=events, total=total)


def safe_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep UI audit reads useful while removing credential-like values and oversized content."""
    safe = _safe_value(payload, depth=0)
    return safe if isinstance(safe, dict) else {}


def _audit_time_range(
    *, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start_utc = _as_utc(start) if start is not None else now - timedelta(days=7)
    end_utc = _as_utc(end) if end is not None else now
    if end_utc < start_utc:
        raise AuditQueryError("End time must not be earlier than start time.")
    if end_utc - start_utc > timedelta(days=MAX_AUDIT_RANGE_DAYS):
        raise AuditQueryError(f"Audit range cannot exceed {MAX_AUDIT_RANGE_DAYS} days.")
    return start_utc, end_utc


def _safe_value(value: Any, *, depth: int) -> Any:
    if depth >= MAX_PAYLOAD_DEPTH:
        return "[truncated]"
    if isinstance(value, dict):
        safe_items: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_PAYLOAD_ITEMS:
                safe_items["_truncated"] = True
                break
            normalized_key = str(key)
            if any(part in normalized_key.lower() for part in SENSITIVE_KEY_PARTS):
                safe_items[normalized_key] = "[redacted]"
            else:
                safe_items[normalized_key] = _safe_value(item, depth=depth + 1)
        return safe_items
    if isinstance(value, list):
        items = [_safe_value(item, depth=depth + 1) for item in value[:MAX_PAYLOAD_ITEMS]]
        if len(value) > MAX_PAYLOAD_ITEMS:
            items.append("[truncated]")
        return items
    if isinstance(value, str) and len(value) > MAX_PAYLOAD_STRING_LENGTH:
        return value[:MAX_PAYLOAD_STRING_LENGTH] + "…[truncated]"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

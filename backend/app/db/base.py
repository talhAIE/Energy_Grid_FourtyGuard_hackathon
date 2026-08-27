from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models."""


# Import all models so Alembic always sees the complete schema metadata.
from app.db.models.audit_event import AuditEvent  # noqa: E402, F401
from app.db.models.city import City  # noqa: E402, F401
from app.db.models.integration_job import IntegrationJob  # noqa: E402, F401
from app.db.models.zone import Zone  # noqa: E402, F401


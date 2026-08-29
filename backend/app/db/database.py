from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database-backed route is called before a database is configured."""


@lru_cache
def get_engine() -> Engine | None:
    """Create the PostgreSQL engine only when a database URL is configured."""
    database_url = get_settings().database_url
    if not database_url:
        return None
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the application database session factory."""
    engine = get_engine()
    if engine is None:
        raise DatabaseNotConfiguredError("DATABASE_URL is not configured.")
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db_session() -> Generator[Session, None, None]:
    """Yield a database session for future FastAPI route dependencies."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_database_health() -> str:
    """Return a safe database state without returning connection details."""
    engine = get_engine()
    if engine is None:
        return "not_configured"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return "unavailable"
    return "healthy"

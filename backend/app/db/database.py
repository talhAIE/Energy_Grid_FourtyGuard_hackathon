from collections.abc import Generator
from functools import lru_cache
from urllib.parse import urlparse

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database-backed route is called before a database is configured."""


@lru_cache
def get_engine() -> Engine | None:
    """Create the PostgreSQL engine only when a database URL is configured.

    Supabase's transaction pooler already owns connection reuse.  Keeping an
    application-side pool in front of it can exhaust the small session/client
    allowance on managed deployments, so use short-lived client connections
    and disable Psycopg prepared statements for that specific endpoint.
    """
    database_url = get_settings().database_url
    if not database_url:
        return None
    if _is_supabase_transaction_pooler(database_url):
        return create_engine(
            database_url,
            poolclass=NullPool,
            pool_pre_ping=True,
            connect_args={"prepare_threshold": None},
        )
    return create_engine(database_url, pool_pre_ping=True)


def _is_supabase_transaction_pooler(database_url: str) -> bool:
    """Identify Supabase's shared transaction-pooler URL without inspecting credentials."""
    parsed = urlparse(database_url)
    return (
        parsed.hostname is not None
        and parsed.hostname.endswith(".pooler.supabase.com")
        and parsed.port == 6543
    )


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

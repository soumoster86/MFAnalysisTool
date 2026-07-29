"""SQLAlchemy engine and session management (SQLite Phase 1)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import PROJECT_ROOT, settings
from utils.logging_config import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _ensure_sqlite_path(url: str) -> None:
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        # Handle relative paths
        p = Path(path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        p.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_path(settings.database_url)

connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
    future=True,
)

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables."""
    # Import models so metadata is registered
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized: {}", settings.database_url)

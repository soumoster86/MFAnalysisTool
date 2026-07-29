"""SQLAlchemy engine and session management (SQLite local / Postgres Supabase)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.db_url import is_supabase_pooler, normalize_database_url
# is_supabase_pooler also detects Neon -pooler endpoints
from config.settings import PROJECT_ROOT, settings
from utils.logging_config import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _ensure_sqlite_path(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    path = url.replace("sqlite:///", "", 1)
    # Absolute unix path: /tmp/foo.db (from sqlite:////tmp/foo.db → //tmp/foo after one replace)
    if path.startswith("//"):
        path = path[1:]  # /tmp/foo.db
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)


def _build_engine():
    url = normalize_database_url(settings.database_url)
    _ensure_sqlite_path(url)

    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif is_supabase_pooler(url):
        # Transaction mode pooler does not support prepared statements well
        connect_args["prepare_threshold"] = None

    engine = create_engine(
        url,
        connect_args=connect_args,
        echo=False,
        future=True,
        pool_pre_ping=True,
        # Cloud-friendly pool defaults (Supabase free tier is limited)
        pool_size=5 if not url.startswith("sqlite") else 5,
        max_overflow=5 if not url.startswith("sqlite") else 10,
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # Log without password
    safe = url
    if "@" in safe:
        # postgresql+psycopg://user:pass@host → user:***@host
        try:
            head, tail = safe.split("://", 1)
            creds, hostpart = tail.split("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                safe = f"{head}://{user}:***@{hostpart}"
        except Exception:
            pass
    logger.info("Database engine ready: {}", safe)
    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent). Safe for Supabase Postgres and SQLite."""
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # Quick connectivity check
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Database connectivity check failed: {}", exc)
        raise
    logger.info("Database tables ensured")


def rebind_engine_from_settings() -> None:
    """Rebuild engine after secrets bootstrap (Streamlit Cloud)."""
    global engine, SessionLocal
    try:
        engine.dispose()
    except Exception:
        pass
    engine = _build_engine()
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)

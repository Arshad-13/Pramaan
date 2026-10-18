"""Database engine and sessions.

Purpose: one SQLite engine configured for safe concurrent writes.
Inputs : DATABASE_URL from settings.
Outputs: `get_engine()`, `SessionLocal()`, `get_db()` (FastAPI dependency), `init_db()`.

Why these settings:
- WAL mode lets readers proceed while one writer commits.
- busy_timeout makes a second writer wait instead of failing instantly.
- foreign_keys=ON because SQLite ignores foreign keys by default.
- Every transaction starts with BEGIN IMMEDIATE, so the write lock is taken up front. This is
  what makes "read the last audit row, then insert the next one" race-free (Section 9), and it
  keeps the atomic dispense UPDATE honest under concurrency. At demo scale the cost (reads also
  take the lock briefly) is irrelevant.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

BUSY_TIMEOUT_MS = 10_000


def make_engine(url: str) -> Engine:
    """Build an engine. SQLite gets WAL, busy_timeout, foreign keys and BEGIN IMMEDIATE."""
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args, future=True)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection, _record):  # pragma: no cover - exercised via tests
            # Take control of transactions from the sqlite3 module so BEGIN IMMEDIATE works.
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


def SessionLocal() -> Session:  # noqa: N802 - conventional name
    """Create a session bound to the current engine."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()


def get_db() -> Iterator[Session]:
    """FastAPI dependency. The caller (service layer) commits; we always close."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent)."""
    from app import models  # noqa: F401 - registers tables on Base.metadata
    from app.models import Base

    Base.metadata.create_all(get_engine())

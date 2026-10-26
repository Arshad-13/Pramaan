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
SCHEMA_VERSION = 1  # bump whenever a model changes shape; see init_db()


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


@lru_cache(maxsize=4)
def _session_factory(engine: Engine) -> sessionmaker[Session]:
    # One factory per engine instead of one per request.
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def SessionLocal() -> Session:  # noqa: N802 - conventional name
    """Create a session bound to the current engine."""
    return _session_factory(get_engine())()


def get_db() -> Iterator[Session]:
    """FastAPI dependency. The caller (service layer) commits; we always close."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SchemaVersionError(RuntimeError):
    """The database file was made by a different version of the schema."""


def init_db() -> None:
    """Create all tables (idempotent) and check the schema version.

    `create_all` never alters an existing table, so a database made by an older or newer schema
    would start fine and then fail in odd places (or, worse, store things in the wrong shape). The
    schema version lives in SQLite's `user_version`: a fresh or unversioned file is stamped with the
    current version, and any other value stops the app with a clear message (fail closed).
    """
    from app import models  # noqa: F401 - registers tables on Base.metadata
    from app.models import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        found = conn.exec_driver_sql("PRAGMA user_version").scalar_one()
        if found == 0:
            conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")  # int constant
        elif found != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"The database is schema version {found} but this app needs {SCHEMA_VERSION}. "
                "Re-seed the demo database (scripts/seed_demo.py --reset) or restore a matching file."
            )

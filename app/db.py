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

import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

BUSY_TIMEOUT_MS = 10_000
SCHEMA_VERSION = 2  # bump whenever a model changes shape; add the step to MIGRATIONS below

# In-place upgrades for SQLite, keyed by the version they upgrade FROM. Each step only adds things
# (columns, indexes), so it cannot lose data. A fresh database never runs these: `create_all`
# builds the current shape and the file is stamped with SCHEMA_VERSION.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        # v2: alert workflow, two-factor sign-in, corrected prescriptions, audit lookup index.
        "ALTER TABLE security_events ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'OPEN'",
        "ALTER TABLE security_events ADD COLUMN handled_by INTEGER",
        "ALTER TABLE security_events ADD COLUMN handled_at DATETIME",
        "ALTER TABLE security_events ADD COLUMN note TEXT",
        "ALTER TABLE users ADD COLUMN totp_secret_enc BLOB",
        "ALTER TABLE users ADD COLUMN totp_kek_version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN totp_last_step INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN recovery_codes_json TEXT",
        "ALTER TABLE prescriptions ADD COLUMN superseded_by VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_audit_log_resource_id ON audit_log (resource_id)",
    ),
}


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


def _backup_before_migration(engine: Engine, found: int) -> None:
    """Copy the database next to itself before upgrading it (file databases only).

    SQLite's own backup call is used rather than a file copy: in WAL mode recent commits can still
    sit in the `-wal` file, and a plain copy of the main file would silently leave them out.
    """
    path = engine.url.database
    if not path or path == ":memory:":
        return
    source = Path(path)
    if not source.is_file():
        return
    target = source.with_name(f"{source.name}.bak-v{found}")
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def init_db() -> None:
    """Create all tables (idempotent), then bring the schema to the current version.

    `create_all` never alters an existing table, so the schema version lives in SQLite's
    `user_version`. A fresh or unversioned file is stamped with the current version. An older
    version is upgraded in place by the steps in MIGRATIONS (after a backup copy of the file); a
    newer or unknown version stops the app with a clear message (fail closed).
    """
    from app import models  # noqa: F401 - registers tables on Base.metadata
    from app.models import Base

    engine = get_engine()
    if engine.dialect.name != "sqlite":
        Base.metadata.create_all(engine)
        return

    with engine.connect() as conn:
        found = conn.exec_driver_sql("PRAGMA user_version").scalar_one()
        conn.rollback()
    if 0 < found < SCHEMA_VERSION and all(v in MIGRATIONS for v in range(found, SCHEMA_VERSION)):
        _backup_before_migration(engine, found)
        with engine.begin() as conn:
            for version in range(found, SCHEMA_VERSION):
                for statement in MIGRATIONS[version]:
                    conn.exec_driver_sql(statement)
            conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")  # int constant
        found = SCHEMA_VERSION

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if found == 0:
            conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")  # int constant
        elif found != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"The database is schema version {found} but this app needs {SCHEMA_VERSION}. "
                "Re-seed the demo database (scripts/seed_demo.py --reset) or restore a matching file."
            )

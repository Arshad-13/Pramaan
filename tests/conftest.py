"""Test setup: temp DB, fixed throwaway keys, frozen-clock helper.

Environment variables are set at import time, before any `app` module reads settings, so
tests never touch the real database, `.env`, or real keys.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

_TMP = Path(tempfile.mkdtemp(prefix="pramaan-tests-"))
_PEM = _TMP / "audit_signing.pem"
_PEM.write_bytes(
    ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)


def _key(seed: bytes) -> str:
    return base64.b64encode((seed * 32)[:32]).decode()


TEST_ENV = {
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256",
    "MASTER_KEY": _key(b"M"),
    "AUDIT_KEY": _key(b"A"),
    "AUDIT_SIGNING_KEY_PATH": str(_PEM),
    "ANOMALY_MODEL_PATH": str(_TMP / "models" / "iforest.joblib"),  # absent unless a test makes one
    "STORAGE_DIR": str(_TMP / "storage"),
    "ANCHOR_FILE": str(_TMP / "storage" / "anchors.jsonl"),
    "PBKDF2_ITERATIONS": "100000",  # faster tests; production default is 600000
    "RATE_LIMIT_ENABLED": "false",  # tests sign in constantly; rate-limit tests switch it on
    "FROZEN_TIME": "",
    "DEBUG": "false",
}
os.environ.update(TEST_ENV)


@pytest.fixture(autouse=True)
def _reset_anchor_file():
    """Anchors are an append-only file outside the DB; each test starts with an empty one."""
    Path(TEST_ENV["ANCHOR_FILE"]).unlink(missing_ok=True)
    yield


@pytest.fixture
def fresh_db():
    """Empty schema for API-level tests. Tests should talk to the app through the client and use
    short-lived sessions (see tests/helpers.py): a session left open would hold SQLite's write lock.
    """
    from app import models
    from app.db import get_engine

    engine = get_engine()
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def _reset_clock():
    from app.core import clock

    clock.freeze(None)
    yield
    clock.freeze(None)


@pytest.fixture
def frozen_clock():
    """Pin time at a known instant; tests can call clock.advance()."""
    from app.core import clock

    clock.freeze("2026-10-18T10:30:00Z")
    return clock


@pytest.fixture
def db():
    """Fresh schema per test on the temp SQLite file."""
    from app import models
    from app.db import SessionLocal, get_engine

    engine = get_engine()
    models.Base.metadata.drop_all(engine)
    models.Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c

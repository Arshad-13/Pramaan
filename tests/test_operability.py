"""Operability: request ids, the access log, readiness, schema versioning and one new rate limit."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app.config import get_settings
from app.core.ratelimit import limiter
from app.db import SCHEMA_VERSION, SchemaVersionError, make_engine
from app.main import access_logger, app
from tests.world import build_world


@pytest.fixture
def client(fresh_db):
    limiter.reset()
    with TestClient(app) as c:
        yield c
    limiter.reset()


# --- request ids and the access log ---------------------------------------------------------------


def test_every_response_carries_a_request_id(client):
    first = client.get("/api/health").headers["x-request-id"]
    second = client.get("/api/health").headers["x-request-id"]
    assert len(first) == 32 and first != second


def test_a_plain_caller_supplied_id_is_kept_and_an_odd_one_is_replaced(client):
    kept = client.get("/api/health", headers={"X-Request-ID": "trace-abc_123.4"})
    assert kept.headers["x-request-id"] == "trace-abc_123.4"
    for bad in ("short", "has spaces in it!!", "x" * 65, "semi;colon-injection"):
        replaced = client.get("/api/health", headers={"X-Request-ID": bad})
        assert (
            replaced.headers["x-request-id"] != bad and len(replaced.headers["x-request-id"]) == 32
        )


def test_access_log_has_method_path_status_and_id_but_never_the_query_string(client, caplog):
    access_logger.addHandler(caplog.handler)  # the logger does not propagate to the root handler
    try:
        with caplog.at_level(logging.INFO, logger="pramaan.access"):
            response = client.get("/api/patients/lookup?email=private.person@example.test")
    finally:
        access_logger.removeHandler(caplog.handler)
    rid = response.headers["x-request-id"]
    line = next(r.getMessage() for r in caplog.records if r.name == "pramaan.access")
    assert line.startswith("GET /api/patients/lookup 401 ") and f"rid={rid}" in line
    assert "private.person" not in line and "?" not in line


# --- readiness ----------------------------------------------------------------------------------


def test_ready_is_ok_when_the_database_and_signing_key_work(client):
    response = client.get("/api/ready")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_ready_says_degraded_and_nothing_else_when_the_signing_key_is_gone(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "audit_signing_key_path", "does/not/exist.pem")
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}  # no detail about which check failed


# --- schema version -----------------------------------------------------------------------------


def test_init_db_stamps_a_new_database_and_refuses_a_different_version(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{(tmp_path / 'versioned.db').as_posix()}")
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)

    def version() -> int:
        with engine.connect() as conn:
            return conn.exec_driver_sql("PRAGMA user_version").scalar_one()

    assert version() == 0
    db_module.init_db()
    assert version() == SCHEMA_VERSION
    db_module.init_db()  # idempotent on a database that is already stamped
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA user_version = 99")
    with pytest.raises(SchemaVersionError, match="schema version 99"):
        db_module.init_db()


# --- change-password budget ---------------------------------------------------------------------


def test_guessing_the_current_password_is_rate_limited(client, monkeypatch):
    world = build_world(client)
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    limiter.reset()
    attempts = get_settings().login_rate_per_minute
    for _ in range(attempts):
        wrong = client.post(
            "/api/auth/change-password",
            json={"current_password": "not-the-password", "new_password": "a-brand-new-password-1"},
            headers=world.patient1_h,
        )
        assert wrong.status_code == 400
    blocked = client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "a-brand-new-password-1"},
        headers=world.patient1_h,
    )
    assert blocked.status_code == 429 and "retry-after" in blocked.headers

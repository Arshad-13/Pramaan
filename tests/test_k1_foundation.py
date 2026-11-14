"""Phase K1: schema migration, session renewal with a hard cap, audit filters and export,
alert workflow, user search, pharmacist history, dispense history and model status."""

from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db as db_module
from app.config import get_settings
from app.core import audit, clock
from app.core.ratelimit import limiter
from app.db import SCHEMA_VERSION, make_engine
from app.main import app
from app.models import Base, Role, SecurityEvent, Severity
from tests.helpers import bearer, make_user, session
from tests.world import build_world, dispense, get_pin, issue, qr_for, verify

# --- migration ----------------------------------------------------------------------------------

NEW_COLUMNS = {
    "users": ["totp_secret_enc", "totp_kek_version", "totp_enabled", "totp_last_step"],
    "security_events": ["status", "handled_by", "handled_at", "note"],
    "prescriptions": ["superseded_by"],
}


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").all()}


def test_a_version_1_database_is_upgraded_in_place_with_a_backup(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    Base.metadata.create_all(engine)
    # Turn the fresh schema back into what version 1 looked like.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_audit_log_resource_id")
        conn.exec_driver_sql("ALTER TABLE users DROP COLUMN recovery_codes_json")
        for table, columns in NEW_COLUMNS.items():
            for column in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute(
            text(
                "INSERT INTO users (public_id, email, name, role, password_hash, is_active, "
                "approval_status, failed_logins, token_version, created_at) VALUES "
                "('u-1', 'old@example.test', 'Old User', 'patient', 'x', 1, 'APPROVED', 0, 0, "
                "'2026-01-01 00:00:00')"
            )
        )
        conn.exec_driver_sql("PRAGMA user_version = 1")
    with engine.connect() as conn:
        assert "totp_enabled" not in _columns(conn, "users")
        conn.rollback()

    db_module.init_db()

    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == SCHEMA_VERSION
        assert "totp_enabled" in _columns(conn, "users")
        assert "status" in _columns(conn, "security_events")
        assert "superseded_by" in _columns(conn, "prescriptions")
        assert conn.exec_driver_sql("SELECT email, totp_enabled FROM users").all() == [
            ("old@example.test", 0)
        ]
        indexes = {r[1] for r in conn.exec_driver_sql("PRAGMA index_list(audit_log)").all()}
        assert "ix_audit_log_resource_id" in indexes
    assert (tmp_path / "old.db.bak-v1").is_file()  # the copy made before touching anything
    db_module.init_db()  # and running it again changes nothing


def test_the_backup_includes_commits_that_are_still_in_the_wal_file(tmp_path):
    source = tmp_path / "x.db"
    engine = make_engine(f"sqlite:///{source.as_posix()}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE t (n INTEGER)")
        conn.exec_driver_sql("INSERT INTO t VALUES (7)")
    db_module._backup_before_migration(engine, 1)  # the engine is still open: data may be in -wal
    import sqlite3

    copy = sqlite3.connect(tmp_path / "x.db.bak-v1")
    try:
        assert copy.execute("SELECT n FROM t").fetchall() == [(7,)]
    finally:
        copy.close()
    engine.dispose()


# --- public config ------------------------------------------------------------------------------


def test_public_config_reports_demo_mode(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", True)
    assert client.get("/api/public-config").json() == {"demo_mode": True}
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.get("/api/public-config").json() == {"demo_mode": False}


# --- session renewal ----------------------------------------------------------------------------


@pytest.fixture
def w(fresh_db):
    limiter.reset()
    with TestClient(app) as client:
        yield build_world(client)
    limiter.reset()


def test_a_session_can_be_renewed_but_never_past_the_hard_cap(fresh_db, monkeypatch):
    clock.freeze("2026-11-02T08:00:00Z")
    monkeypatch.setattr(get_settings(), "session_max_hours", 2)
    make_user("p@example.test", Role.patient)
    with TestClient(app) as client:
        headers = bearer(client, "p@example.test")
        first = client.get("/api/auth/me", headers=headers).json()
        assert first["session_ends_by"].startswith("2026-11-02T10:00:00")
        # Renew every 25 minutes: each token is fine, but the end date never moves.
        for _ in range(4):
            clock.advance(timedelta(minutes=25))
            renewed = client.post("/api/auth/refresh", headers=headers)
            assert renewed.status_code == 200, renewed.text
            headers = {"Authorization": f"Bearer {renewed.json()['access_token']}"}
            me = client.get("/api/auth/me", headers=headers).json()
            assert me["session_ends_by"] == first["session_ends_by"]
            assert me["session_expires_at"] <= me["session_ends_by"]
        clock.advance(timedelta(minutes=25))  # 125 minutes after sign-in: past the cap
        assert client.post("/api/auth/refresh", headers=headers).status_code == 401
        assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_renewing_is_recorded_in_the_audit_log(w):
    assert w.client.post("/api/auth/refresh", headers=w.patient1_h).status_code == 200
    log = w.client.get("/api/admin/audit?action=SESSION_RENEWED", headers=w.auditor).json()
    assert log["total"] == 1


def test_a_mfa_token_is_not_a_session_token(w):
    from app.core.security import create_mfa_token

    token = create_mfa_token(1, 0)
    assert (
        w.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


# --- audit filters and export -------------------------------------------------------------------


def test_audit_log_filters_by_action_role_and_resource(w):
    rx_id = issue(w)
    everything = w.client.get("/api/admin/audit", headers=w.auditor).json()
    assert "RX_ISSUED" in everything["actions"] and everything["total"] > 3

    issued = w.client.get("/api/admin/audit?action=RX_ISSUED", headers=w.auditor).json()
    assert issued["total"] == 1 and issued["items"][0]["resource_id"] == rx_id

    by_resource = w.client.get(f"/api/admin/audit?resource={rx_id[:8]}", headers=w.auditor).json()
    assert by_resource["total"] >= 1
    assert all(rx_id[:8] in i["resource_id"] for i in by_resource["items"])

    doctors = w.client.get("/api/admin/audit?actor_role=doctor", headers=w.auditor).json()
    assert doctors["total"] >= 1 and {i["actor_role"] for i in doctors["items"]} == {"doctor"}

    future = w.client.get("/api/admin/audit?since=2099-01-01T00:00:00Z", headers=w.auditor).json()
    assert future["total"] == 0


def test_audit_filter_treats_percent_and_underscore_literally(w):
    issue(w)
    hits = w.client.get("/api/admin/audit?resource=%25", headers=w.auditor).json()
    assert hits["total"] == 0  # a bare % is not a wildcard
    assert w.client.get("/api/admin/audit?actor_role=hacker", headers=w.auditor).status_code == 422


def test_audit_export_is_csv_defuses_formulas_and_is_itself_logged(w):
    issue(w)
    sql_value = '=HYPERLINK("http://evil.test")'
    with session() as db:
        audit.append(db, None, "test", "USER_REGISTER", sql_value, {})
        db.commit()
    response = w.client.get("/api/admin/audit/export", headers=w.auditor)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:5] == ["seq", "time_utc", "actor_id", "actor_role", "action"]
    resources = [r[5] for r in rows[1:]]
    assert "'" + sql_value in resources and sql_value not in resources
    assert (
        w.client.get("/api/admin/audit?action=AUDIT_EXPORTED", headers=w.auditor).json()["total"]
        == 1
    )
    assert w.client.get("/api/admin/audit/export", headers=w.admin).status_code == 403
    assert w.client.get("/api/admin/audit/verify", headers=w.auditor).json()["ok"] is True


# --- alert workflow -----------------------------------------------------------------------------


def _event(severity=Severity.MEDIUM) -> int:
    with session() as db:
        event = SecurityEvent(event_type="POSSIBLE_REPLAY", severity=severity, user_id=None)
        db.add(event)
        db.commit()
        return event.id


def test_an_admin_can_acknowledge_and_resolve_an_alert(w):
    event_id = _event()
    assert w.client.get("/api/admin/security-events", headers=w.admin).json()[0]["status"] == "OPEN"

    done = w.client.patch(
        f"/api/admin/security-events/{event_id}",
        headers=w.admin,
        json={"status": "RESOLVED", "note": "Checked with the pharmacy."},
    )
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "RESOLVED" and body["note"] == "Checked with the pharmacy."
    assert body["handled_at"] is not None

    open_only = w.client.get("/api/admin/security-events?status=OPEN", headers=w.admin).json()
    assert open_only == []
    resolved = w.client.get("/api/admin/security-events?status=RESOLVED", headers=w.auditor).json()
    assert [e["id"] for e in resolved] == [event_id]
    handled = w.client.get("/api/admin/audit?action=SECURITY_EVENT_HANDLED", headers=w.auditor)
    assert handled.json()["total"] == 1

    reopened = w.client.patch(
        f"/api/admin/security-events/{event_id}", headers=w.admin, json={"status": "OPEN"}
    ).json()
    assert reopened["status"] == "OPEN" and reopened["handled_at"] is None


def test_alert_filters_and_who_may_close_them(w):
    low, high = _event(Severity.LOW), _event(Severity.HIGH)
    only_high = w.client.get("/api/admin/security-events?severity=HIGH", headers=w.admin).json()
    assert [e["id"] for e in only_high] == [high]
    assert low != high
    # The auditor reads alerts but cannot close them.
    closed = w.client.patch(
        f"/api/admin/security-events/{high}", headers=w.auditor, json={"status": "RESOLVED"}
    )
    assert closed.status_code == 403
    assert (
        w.client.patch(
            "/api/admin/security-events/987654", headers=w.admin, json={"status": "RESOLVED"}
        ).status_code
        == 404
    )
    assert (
        w.client.patch(
            f"/api/admin/security-events/{high}", headers=w.admin, json={"status": "DELETED"}
        ).status_code
        == 422
    )


# --- user search --------------------------------------------------------------------------------


def test_user_search_matches_name_or_email_and_treats_wildcards_literally(w):
    found = w.client.get("/api/admin/users?q=ravi", headers=w.admin).json()
    assert [u["name"] for u in found["items"]] == ["Ravi Patel"]
    by_email = w.client.get("/api/admin/users?q=PHARM.B@", headers=w.admin).json()
    assert by_email["total"] == 1
    assert w.client.get("/api/admin/users?q=%25", headers=w.admin).json()["total"] == 0


# --- pharmacist history and dispense history ----------------------------------------------------


def test_pharmacist_history_lists_only_their_own_checks_and_can_filter(w):
    rx_id = issue(w)
    qr = qr_for(rx_id)
    assert verify(w, qr).json()["result"] == "VALID"
    assert verify(w, qr[:-4] + "AAAA").json()["result"] in ("TAMPERED", "INVALID_QR")
    assert verify(w, qr, w.pharmacist_b).json()["result"] == "VALID"

    mine = w.client.get("/api/verify/history", headers=w.pharmacist_a).json()
    assert mine["total"] == 2 and mine["items"][0]["ts"] >= mine["items"][1]["ts"]
    only_valid = w.client.get("/api/verify/history?result=VALID", headers=w.pharmacist_a).json()
    assert only_valid["total"] == 1 and only_valid["items"][0]["rx_ref"] == rx_id[:8]
    paged = w.client.get("/api/verify/history?limit=1&offset=1", headers=w.pharmacist_a).json()
    assert len(paged["items"]) == 1 and paged["total"] == 2
    assert (
        w.client.get("/api/verify/history?result=NOPE", headers=w.pharmacist_a).status_code == 422
    )
    assert w.client.get("/api/verify/history", headers=w.patient1_h).status_code == 403


def test_dispense_history_and_fills_on_the_prescription(w):
    rx_id = issue(w)
    pin = get_pin(w, rx_id)
    assert dispense(w, rx_id, pin=pin).status_code == 200

    mine = w.client.get("/api/verify/dispenses", headers=w.pharmacist_a).json()
    assert mine["total"] == 1
    assert mine["items"][0]["rx_ref"] == rx_id[:8] and mine["items"][0]["fill_no"] == 1
    assert w.client.get("/api/verify/dispenses", headers=w.pharmacist_b).json()["total"] == 0

    for headers in (w.doctor, w.patient1_h):
        rx = w.client.get("/api/prescriptions/mine", headers=headers).json()[0]
        assert [f["fill_no"] for f in rx["fills"]] == [1]
        assert rx["fills"][0]["pharmacy"] == "Org"
    doctor_view = w.client.get("/api/prescriptions/mine", headers=w.doctor).json()[0]
    patient_view = w.client.get("/api/prescriptions/mine", headers=w.patient1_h).json()[0]
    assert doctor_view["patient_id"] == w.patient1 and patient_view["patient_id"] is None


# --- model status -------------------------------------------------------------------------------


def test_model_status_says_when_there_is_no_model(w):
    body = w.client.get("/api/admin/model-status", headers=w.admin).json()
    assert body["status"] == "MISSING" and body["features"] == [] and body["weight_points"] == 0
    assert w.client.get("/api/admin/model-status", headers=w.auditor).status_code == 200
    assert w.client.get("/api/admin/model-status", headers=w.doctor).status_code == 403

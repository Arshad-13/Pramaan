"""P0: database setup and /api/health."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.db import get_engine

EXPECTED_TABLES = {
    "users",
    "activation_tokens",
    "doctor_keys",
    "prescriptions",
    "dispenses",
    "audit_log",
    "audit_checkpoints",
    "security_events",
    "verification_attempts",
}


def test_all_tables_created(db):
    assert EXPECTED_TABLES <= set(inspect(get_engine()).get_table_names())


def test_sqlite_pragmas(db):
    with get_engine().connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 5000


def test_datetimes_round_trip_as_aware_utc(db):
    when = datetime(2026, 10, 18, 10, 30, tzinfo=UTC)
    user = models.User(email="a@b.test", name="A", role=models.Role.patient, created_at=when)
    db.add(user)
    db.commit()
    db.expire_all()
    assert db.query(models.User).one().created_at == when


def test_naive_datetime_is_rejected(db):
    user = models.User(
        email="n@b.test", name="N", role=models.Role.patient, created_at=datetime(2026, 1, 1)
    )
    db.add(user)
    with pytest.raises(Exception, match="naive datetime"):
        db.commit()


def test_dispense_unique_per_fill(db):
    doctor = models.User(email="d@x.test", name="D", role=models.Role.doctor)
    db.add(doctor)
    db.flush()
    key = models.DoctorKey(
        key_id="k" * 16,
        user_id=doctor.id,
        public_key_pem="pem",
        enc_private_key=b"x",
        kdf_salt=b"s",
        kdf_iterations=1,
        nonce=b"n",
    )
    db.add(key)
    db.flush()
    now = datetime(2026, 10, 18, tzinfo=UTC)
    rx = models.Prescription(
        id="rx1", doctor_id=doctor.id, patient_id=doctor.id, key_id=key.key_id,
        payload_enc=b"p", payload_hash="h", signature_b64="s", wrapped_dek=b"d",
        issued_at=now, expires_at=now, pdf_path="p", pdf_sha256="h",
    )  # fmt: skip
    db.add(rx)
    db.flush()
    db.add(models.Dispense(rx_id="rx1", fill_no=1, pharmacist_id=doctor.id))
    db.commit()
    db.add(models.Dispense(rx_id="rx1", fill_no=1, pharmacist_id=doctor.id))
    with pytest.raises(IntegrityError):
        db.commit()


def test_fills_check_constraint(db):
    with get_engine().begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO prescriptions (id, doctor_id, patient_id, key_id, payload_enc,"
                " payload_hash, signature_b64, wrapped_dek, kek_version, status, max_fills,"
                " fills_used, require_pin, risk_score, risk_flags, risk_features_json,"
                " issued_at, expires_at, pdf_path, pdf_sha256)"
                " VALUES ('r','1','1','k',x'00','h','s',x'00',1,'ISSUED',1,2,1,0,'[]','{}',"
                " '2026-01-01','2026-01-02','p','h')"
            )
        )


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_docs_disabled_when_not_debug(client):
    assert client.get("/api/docs").status_code in (404, 405)
    assert client.get("/api/openapi.json").status_code in (404, 405)

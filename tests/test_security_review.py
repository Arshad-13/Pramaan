"""Findings from the security review of the crypto, auth and dispense code (27 Oct)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core import audit
from app.core.ratelimit import limiter
from app.main import app
from app.models import AuditLog
from app.services.verification_service import _pin_policy_intact
from tests.helpers import session
from tests.world import build_world, dispense, get_pin, issue, qr_for, sql, stored, verify


@pytest.fixture
def w(fresh_db):
    limiter.reset()
    with TestClient(app) as client:
        yield build_world(client)
    limiter.reset()


def issue_entry(rx_id: str) -> AuditLog:
    with session() as db:
        row = db.scalars(
            select(AuditLog).where(AuditLog.action == "RX_ISSUED", AuditLog.resource_id == rx_id)
        ).one()
        db.expunge(row)
        return row


# --- the PIN setting is not signed, so it is sealed in the audit log ----------------------------


def test_the_pin_setting_is_recorded_in_the_sealed_issue_entry(w):
    rx_id = issue(w)
    assert '"require_pin":true' in issue_entry(rx_id).details_json
    assert audit.entry_is_authentic(issue_entry(rx_id))


def test_switching_the_pin_off_in_the_database_makes_the_prescription_tampered(w):
    rx_id = issue(w)
    qr, pin = qr_for(rx_id), get_pin(w, rx_id)
    assert verify(w, qr).json()["result"] == "VALID"

    sql("UPDATE prescriptions SET require_pin = 0 WHERE id = :i", i=rx_id)

    body = verify(w, qr).json()
    assert body["result"] == "TAMPERED"
    assert body["reason_codes"] == ["DB_RECORD_ALTERED"]
    assert body["can_dispense"] is False
    # Neither the identity tick-box nor the real PIN gets it through.
    assert dispense(w, rx_id, qr=qr, patient_identity_checked=True).status_code == 409
    assert dispense(w, rx_id, qr=qr, pin=pin).status_code == 409
    assert stored(rx_id).fills_used == 0


def edit_issue_entry(rx_id: str, old: str, new: str) -> None:
    """Attacker's view: rewrite the text of the sealed issue entry (without the audit key)."""
    sql(
        "UPDATE audit_log SET details_json = replace(details_json, :old, :new) "
        "WHERE action = 'RX_ISSUED' AND resource_id = :i",
        i=rx_id,
        old=old,
        new=new,
    )


def test_editing_the_sealed_entry_as_well_does_not_help_the_attacker(w):
    rx_id = issue(w)
    qr = qr_for(rx_id)
    sql("UPDATE prescriptions SET require_pin = 0 WHERE id = :i", i=rx_id)
    edit_issue_entry(rx_id, '"require_pin":true', '"require_pin":false')
    assert verify(w, qr).json()["result"] == "TAMPERED"


def test_deleting_the_setting_from_the_sealed_entry_does_not_help_either(w):
    rx_id = issue(w)
    qr = qr_for(rx_id)
    sql("UPDATE prescriptions SET require_pin = 0 WHERE id = :i", i=rx_id)
    edit_issue_entry(rx_id, '"require_pin":true,', "")
    assert verify(w, qr).json()["result"] == "TAMPERED"


def test_an_untouched_prescription_without_the_recorded_setting_is_accepted(w):
    """Prescriptions issued before the setting was recorded keep working."""
    with session() as db:
        audit.append(db, None, "doctor", "RX_ISSUED", "legacy-rx", {"max_fills": 1})
        db.commit()
    legacy = SimpleNamespace(id="legacy-rx", require_pin=True)
    with session() as db:
        assert _pin_policy_intact(db, legacy) is True


def test_a_normal_prescription_without_a_pin_still_verifies(w):
    rx_id = issue(w, require_pin=False)
    assert '"require_pin":false' in issue_entry(rx_id).details_json
    assert verify(w, qr_for(rx_id)).json()["result"] == "VALID"
    response = dispense(w, rx_id, patient_identity_checked=True)
    assert response.status_code == 200, response.text


# --- patient lookup is not a free "is this address registered?" oracle ---------------------------


def test_patient_lookup_is_rate_limited_per_doctor(w, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    monkeypatch.setattr(get_settings(), "verify_rate_per_minute", 3)
    limiter.reset()
    codes = [
        w.client.get(
            "/api/patients/lookup", params={"email": "nobody@example.test"}, headers=w.doctor
        ).status_code
        for _ in range(4)
    ]
    assert codes == [404, 404, 404, 429]

"""P6: the risk check, the override flow at issue time, and SUSPICIOUS at verification."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, DoctorKey, Prescription, SecurityEvent
from tests.helpers import SIGNING_PASSWORD, session
from tests.world import build_world, dispense, get_pin, issue, med, qr_for, stored, verify

FAKE = med(name="Xyzzolam")
TRAMADOL = med(name="Tramadol", dose_mg=50, frequency="BD")
ABSURD = med(name="Paracetamol", dose_mg=5000)
REASON = "Patient is on a trial protocol; dose confirmed with the specialist."


@pytest.fixture
def w(fresh_db):
    with TestClient(app) as client:
        yield build_world(client)


def post_issue(w, medicines, **extra):
    body = {
        "patient_id": w.patient1,
        "medicines": medicines,
        "notes": "",
        "validity_days": 30,
        "max_fills": 1,
        "signing_password": SIGNING_PASSWORD,
        **extra,
    }
    return w.client.post("/api/prescriptions", headers=w.doctor, json=body)


def risk_check(w, medicines, headers=None, **extra):
    return w.client.post(
        "/api/prescriptions/risk-check",
        headers=headers or w.doctor,
        json={"medicines": medicines, **extra},
    )


def audit_actions():
    with session() as db:
        return [r.action for r in db.scalars(select(AuditLog).order_by(AuditLog.seq))]


def rx_count():
    with session() as db:
        return len(list(db.scalars(select(Prescription.id))))


# --- the live risk check -------------------------------------------------------------------------


def test_a_normal_prescription_needs_no_confirmation(w):
    out = risk_check(w, [med()]).json()
    assert out["risk"] == {"score": 0, "flags": [], "explanations": []}
    assert out["requires_override"] is False and out["threshold"] == 60
    assert out["medicines"][0]["status"] == "KNOWN" and out["warnings"] == ["MODEL_UNAVAILABLE"]


def test_the_check_reports_typos_with_a_suggestion_per_medicine(w):
    out = risk_check(w, [med(), med(name="Paracetamool", dose_mg=650)]).json()
    assert [m["status"] for m in out["medicines"]] == ["KNOWN", "POSSIBLE_TYPO"]
    assert out["medicines"][1]["suggestion"] == "Paracetamol" and out["medicines"][1]["index"] == 1
    assert out["risk"]["flags"] == ["POSSIBLE_TYPO"] and out["requires_override"] is False


def test_a_fake_drug_or_absurd_dose_requires_confirmation(w):
    assert risk_check(w, [FAKE]).json()["requires_override"] is True
    out = risk_check(w, [ABSURD]).json()
    assert out["requires_override"] is True and out["risk"]["score"] == 70


def test_controlled_medicines_cannot_be_refilled_and_the_check_says_so(w):
    out = risk_check(w, [TRAMADOL], max_fills=3).json()
    assert "CONTROLLED_NO_REFILLS" in out["warnings"] and out["controlled"] is True


def test_the_check_needs_no_password_and_does_not_store_anything(w):
    risk_check(w, [FAKE])
    assert rx_count() == 0
    assert "RX_ISSUED" not in audit_actions()


def test_the_check_is_for_doctors_only(w):
    for headers in (w.patient1_h, w.pharmacist_a, w.admin):
        assert risk_check(w, [med()], headers=headers).status_code == 403


def test_the_drug_list_endpoint(w):
    drugs = w.client.get("/api/drugs", headers=w.doctor).json()
    assert len(drugs) >= 100 and {"name", "generic", "is_brand"} == set(drugs[0])
    names = [d["name"] for d in drugs]
    assert "Amoxicillin" in names and "Dolo" in names and names == sorted(names, key=str.lower)
    assert w.client.get("/api/drugs", headers=w.patient1_h).status_code == 403


# --- issuing with a warning --------------------------------------------------------------------------


def test_an_unusual_prescription_needs_a_reason_before_it_is_signed(w):
    response = post_issue(w, [FAKE])
    body = response.json()
    assert response.status_code == 409 and body["code"] == "RISK_CONFIRMATION_REQUIRED"
    assert body["threshold"] == 60 and body["risk"]["score"] == 60
    assert body["risk"]["flags"] == ["UNKNOWN_DRUG"]
    assert "not in the drug list" in body["risk"]["explanations"][0]
    assert rx_count() == 0 and "RX_ISSUED" not in audit_actions()


def test_a_missing_confirmation_does_not_spend_a_password_attempt(w):
    post_issue(w, [FAKE], signing_password="a-wrong-password-123")
    with session() as db:
        assert db.scalars(select(DoctorKey)).one().failed_unlocks == 0
    assert "SIGN_UNLOCK_FAIL" not in audit_actions()


@pytest.mark.parametrize("reason", ["", "   ", "short"])
def test_a_missing_or_trivial_reason_is_refused(w, reason):
    response = post_issue(w, [FAKE], override_reason=reason)
    assert response.status_code in (400, 409) and rx_count() == 0


def test_with_a_reason_the_prescription_is_issued_flagged_and_recorded(w):
    response = post_issue(w, [FAKE], override_reason=REASON)
    assert response.status_code == 201, response.text
    out = response.json()
    assert out["risk"]["score"] == 60 and out["risk"]["flags"] == ["UNKNOWN_DRUG"]
    row = stored(out["rx_id"])
    assert row.risk_score == 60 and json.loads(row.risk_flags) == ["UNKNOWN_DRUG"]
    assert row.override_reason == REASON
    features = json.loads(row.risk_features_json)
    assert features["num_medicines"] == 1 and "doctor_rx_last_24h" in features


def test_an_override_is_audited_distinctly_and_alerts_the_admin_without_the_reason_text(w):
    rx_id = post_issue(w, [FAKE], override_reason=REASON).json()["rx_id"]
    actions = audit_actions()
    assert "RX_ISSUED_WITH_OVERRIDE" in actions and "RX_ISSUED" not in actions
    with session() as db:
        blob = json.dumps([r.details_json for r in db.scalars(select(AuditLog))])
        event = db.scalars(select(SecurityEvent)).one()
    assert "trial protocol" not in blob and "Xyzzolam" not in blob  # no free text or drug names
    assert (event.event_type, event.severity.value) == ("RISK_OVERRIDE", "LOW")
    assert json.loads(event.details_json) == {"rx_id": rx_id, "risk_score": 60}
    listed = w.client.get("/api/admin/security-events", headers=w.admin).json()
    assert [e["event_type"] for e in listed] == ["RISK_OVERRIDE"]


def test_a_reason_is_ignored_when_it_was_not_needed(w):
    rx_id = post_issue(w, [med()], override_reason=REASON).json()["rx_id"]
    assert stored(rx_id).override_reason is None
    assert "RX_ISSUED" in audit_actions() and "RX_ISSUED_WITH_OVERRIDE" not in audit_actions()


def test_an_absurd_dose_needs_confirmation_too(w):
    assert post_issue(w, [ABSURD]).status_code == 409
    out = post_issue(w, [ABSURD], override_reason=REASON).json()
    assert out["risk"]["flags"] == ["DOSE_ABOVE_SINGLE_MAX", "DOSE_ABOVE_DAILY_MAX"]


def test_a_typo_alone_only_warns(w):
    out = post_issue(w, [med(name="Amoxicilin")]).json()
    assert out["risk"]["flags"] == ["POSSIBLE_TYPO"] and out["risk"]["score"] == 15


def test_the_doctor_sees_the_risk_score_the_patient_does_not(w):
    post_issue(w, [med(name="Amoxicilin")])
    assert w.client.get("/api/prescriptions/mine", headers=w.doctor).json()[0]["risk_score"] == 15
    assert (
        w.client.get("/api/prescriptions/mine", headers=w.patient1_h).json()[0]["risk_score"]
        is None
    )


# --- controlled medicines ---------------------------------------------------------------------------


def test_controlled_medicines_are_scored_and_limited_to_a_single_fill(w):
    refused = post_issue(w, [TRAMADOL], max_fills=3)
    assert refused.status_code == 400 and "refilled" in refused.json()["detail"]
    ok = post_issue(w, [TRAMADOL], max_fills=1)
    assert ok.status_code == 201 and ok.json()["risk"]["flags"] == ["CONTROLLED_SUBSTANCE"]
    assert ok.json()["risk"]["score"] == 10


def test_non_controlled_medicines_can_be_refilled(w):
    assert post_issue(w, [med()], max_fills=3).status_code == 201


# --- bursts ---------------------------------------------------------------------------------------------


def test_the_sixteenth_prescription_in_a_day_carries_a_burst_flag(w):
    for _ in range(15):
        assert post_issue(w, [med()]).status_code == 201
    out = post_issue(w, [med()]).json()
    assert out["risk"]["flags"] == ["DOCTOR_BURST"] and out["risk"]["score"] == 20
    scores = sorted(
        r["risk_score"] for r in w.client.get("/api/prescriptions/mine", headers=w.doctor).json()
    )
    assert scores == [0] * 15 + [20]  # earlier prescriptions were not retro-flagged


# --- at verification time ------------------------------------------------------------------------------------


def test_a_flagged_prescription_verifies_as_suspicious_with_the_reasons(w):
    rx_id = post_issue(w, [FAKE], override_reason=REASON).json()["rx_id"]
    out = verify(w, qr_for(rx_id)).json()
    assert out["result"] == "SUSPICIOUS" and out["reason_codes"] == ["RISK_ABOVE_THRESHOLD"]
    assert out["can_dispense"] is False
    assert out["risk"]["score"] == 60 and out["risk"]["flags"] == ["UNKNOWN_DRUG"]
    assert out["risk"]["explanations"] == ['"Xyzzolam" is not in the drug list.']
    assert out["doctor"]["name"] == "Dr. A. Shah"  # the record is authentic and still shown


def test_a_suspicious_prescription_cannot_be_dispensed(w):
    rx_id = post_issue(w, [FAKE], override_reason=REASON).json()["rx_id"]
    response = dispense(w, rx_id, pin=get_pin(w, rx_id))
    assert response.status_code == 409 and "SUSPICIOUS" in response.json()["detail"]
    assert stored(rx_id).fills_used == 0


def test_a_typo_only_prescription_is_still_valid_to_dispense(w):
    rx_id = post_issue(w, [med(name="Amoxicilin")]).json()["rx_id"]
    out = verify(w, qr_for(rx_id)).json()
    assert out["result"] == "VALID" and out["risk"]["flags"] == ["POSSIBLE_TYPO"]
    assert out["risk"]["explanations"][0].startswith('"Amoxicilin" looks like "Amoxicillin"')
    assert dispense(w, rx_id, pin=get_pin(w, rx_id)).status_code == 200


def test_the_audit_chain_is_intact_after_overrides(w):
    post_issue(w, [FAKE], override_reason=REASON)
    assert w.client.get("/api/admin/audit/verify", headers=w.auditor).json()["ok"] is True
    assert issue(w)  # normal issuing still works

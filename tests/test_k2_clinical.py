"""Phase K2: drug-interaction rules, the score breakdown, and corrected prescriptions."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.ai import interactions, risk
from app.core import clock
from app.main import app
from tests.helpers import PASSWORD, SIGNING_PASSWORD, bearer
from tests.world import DOCTOR_EMAIL, build_world, dispense, get_pin, issue, med, qr_for, verify

REASON = "The pair was reviewed with the patient and is intended."


def pairs(*generics: str):
    return interactions.find_interactions(list(enumerate(generics)))


def assess(*medicines):
    return risk.assess(list(medicines))


# --- the rules ----------------------------------------------------------------------------------


def test_every_name_in_the_rule_files_is_a_drug_we_know():
    import csv

    from app.ai import drug_match

    known = {e.generic for e in drug_match.load_catalog().names()}
    used: set[str] = set()
    for filename, columns in (("drug_classes.csv", ["generic"]), ("interactions.csv", ["a", "b"])):
        with open(drug_match.DATA_DIR / filename, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                used.update(row[c] for c in columns if not row[c].startswith("@"))
    assert used <= known, used - known


def test_a_class_rule_matches_any_member_and_names_the_pair():
    (hit,) = pairs("Warfarin", "Ibuprofen")
    assert (hit.severity, hit.first, hit.second) == ("MAJOR", "Warfarin", "Ibuprofen")
    (other,) = pairs("Naproxen", "Warfarin")  # order does not matter
    assert other.severity == "MAJOR"


def test_unrelated_medicines_and_the_same_medicine_twice_have_no_interaction():
    assert pairs("Paracetamol", "Amoxicillin", "Cetirizine") == []
    assert pairs("Ibuprofen", "Ibuprofen") == []  # that is DUPLICATE_THERAPY, not an interaction


def test_the_most_severe_matching_rule_wins_for_a_pair():
    # Ciprofloxacin and Levofloxacin are both QT drugs (moderate) and the same class (no rule),
    # so the pair is moderate; Warfarin with Ciprofloxacin has its own moderate rule.
    assert [h.severity for h in pairs("Ciprofloxacin", "Levofloxacin")] == ["MODERATE"]
    assert [h.severity for h in pairs("Warfarin", "Ciprofloxacin")] == ["MODERATE"]
    # Sertraline + Escitalopram: same class (major) and Escitalopram is a QT drug (no QT partner).
    assert [h.severity for h in pairs("Sertraline", "Escitalopram")] == ["MAJOR"]


def test_each_pair_is_reported_once_and_major_comes_first():
    found = pairs("Ondansetron", "Azithromycin", "Warfarin", "Diclofenac")
    assert [h.severity for h in found] == ["MAJOR", "MODERATE"]
    assert found[0].indices == (2, 3)


# --- in the risk score --------------------------------------------------------------------------


def test_a_major_interaction_reaches_the_review_threshold_by_itself():
    result = assess(
        med(name="Warfarin", dose_mg=5, frequency="OD"), med(name="Ibuprofen", dose_mg=400)
    )
    assert result.flags == ["DRUG_INTERACTION_MAJOR"]
    assert result.score == 60
    assert "Warfarin with Ibuprofen (major interaction)" in result.explanations[0]
    assert [n.flags for n in result.notes] == [["DRUG_INTERACTION_MAJOR"]] * 2


def test_moderate_interactions_add_fifteen_each_and_everything_stops_at_sixty():
    one = assess(
        med(name="Ondansetron", dose_mg=4), med(name="Azithromycin", dose_mg=500, frequency="OD")
    )
    assert one.score == 15 and one.flags == ["DRUG_INTERACTION_MODERATE"]
    many = assess(
        med(name="Ondansetron", dose_mg=4),
        med(name="Azithromycin", dose_mg=500, frequency="OD"),
        med(name="Domperidone", dose_mg=10),
        med(name="Hydroxychloroquine", dose_mg=200, frequency="BD"),
    )
    assert many.score == 60  # six moderate pairs would be 90: capped at 60


def test_the_breakdown_adds_up_to_the_score():
    cases = [
        [med()],
        [med(name="Xyzzolam"), med(name="Qwertyol")],
        [med(name="Warfarin", dose_mg=5, frequency="OD"), med(name="Ibuprofen", dose_mg=400)],
        [
            med(name="Tramadol", dose_mg=50, frequency="BD"),
            med(name="Alprazolam", dose_mg=1, frequency="OD"),
        ],
        [med(name="Paracetamol", dose_mg=5000), med(name="Xyzzolam")],
    ]
    for medicines in cases:
        result = risk.assess(medicines, doctor_rx_last_24h=20, anomaly_score=0.99)
        assert sum(points for _, _, points in result.breakdown) == result.score, medicines
        assert all(label for _, label, _ in result.breakdown)


def test_the_breakdown_shows_the_cap_when_the_total_goes_over_100():
    result = risk.assess(
        [med(name="Xyzzolam"), med(name="Paracetamol", dose_mg=5000)],
        doctor_rx_last_24h=20,
        anomaly_score=1.0,
    )
    assert result.score == 100
    assert result.breakdown[-1][0] == "CAPPED" and result.breakdown[-1][2] < 0


# --- over the API -------------------------------------------------------------------------------


@pytest.fixture
def w(fresh_db):
    with TestClient(app) as client:
        yield build_world(client)


def test_risk_check_returns_interactions_and_the_breakdown_and_asks_for_a_reason(w):
    medicines = [
        med(name="Warfarin", dose_mg=5, frequency="OD"),
        med(name="Ibuprofen", dose_mg=400, frequency="TDS"),
    ]
    body = w.client.post(
        "/api/prescriptions/risk-check", headers=w.doctor, json={"medicines": medicines}
    ).json()
    assert body["requires_override"] is True
    assert body["risk"]["interactions"] == [
        {
            "first": "Warfarin",
            "second": "Ibuprofen",
            "severity": "MAJOR",
            "note": "Bleeding risk rises sharply.",
        }
    ]
    assert body["risk"]["breakdown"] == [
        {"code": "DRUG_INTERACTION_MAJOR", "label": "Major drug interaction", "points": 60}
    ]
    refused = w.client.post(
        "/api/prescriptions",
        headers=w.doctor,
        json={
            "patient_id": w.patient1,
            "medicines": medicines,
            "signing_password": SIGNING_PASSWORD,
        },
    )
    assert refused.status_code == 409
    assert refused.json()["risk"]["breakdown"][0]["points"] == 60


def test_a_pharmacist_sees_why_it_was_flagged_without_the_breakdown(w):
    medicines = [
        med(name="Warfarin", dose_mg=5, frequency="OD"),
        med(name="Ibuprofen", dose_mg=400),
    ]
    rx_id = issue(w, medicines=medicines, override_reason=REASON)
    out = verify(w, qr_for(rx_id)).json()
    assert out["result"] == "SUSPICIOUS"
    assert "DRUG_INTERACTION_MAJOR" in out["risk"]["flags"]
    assert any("Warfarin with Ibuprofen" in text for text in out["risk"]["explanations"])
    assert out["risk"]["breakdown"] == []


# --- corrected prescriptions --------------------------------------------------------------------


def test_a_correction_issues_a_new_prescription_and_withdraws_the_old_one(w):
    old = issue(w)
    new = issue(w, medicines=[med(dose_mg=250)], supersedes=old)
    assert new != old

    gone = verify(w, qr_for(old)).json()
    assert gone["result"] == "REVOKED" and gone["reason_codes"] == ["RX_SUPERSEDED"]
    assert gone["can_dispense"] is False
    assert verify(w, qr_for(new)).json()["result"] == "VALID"

    mine = {r["id"]: r for r in w.client.get("/api/prescriptions/mine", headers=w.doctor).json()}
    assert mine[old]["status"] == "REVOKED" and mine[old]["superseded_by"] == new
    assert mine[new]["superseded_by"] is None

    log = w.client.get("/api/admin/audit?action=RX_SUPERSEDED", headers=w.auditor).json()
    assert log["total"] == 1 and log["items"][0]["resource_id"] == old
    assert w.client.get("/api/admin/audit/verify", headers=w.auditor).json()["ok"] is True


def test_the_old_prescription_cannot_be_dispensed_after_a_correction(w):
    old = issue(w)
    pin = get_pin(w, old)
    issue(w, supersedes=old)
    assert dispense(w, old, pin=pin).status_code == 409


def test_a_correction_must_be_for_the_same_patient(w):
    old = issue(w)
    body = {
        "patient_id": w.patient2,
        "medicines": [med()],
        "signing_password": SIGNING_PASSWORD,
        "supersedes": old,
    }
    response = w.client.post("/api/prescriptions", headers=w.doctor, json=body)
    assert response.status_code == 400
    assert verify(w, qr_for(old)).json()["result"] == "VALID"  # nothing was changed


def test_only_the_issuing_doctor_can_correct_and_only_unused_prescriptions(w):
    old = issue(w)
    body = {"patient_id": w.patient1, "medicines": [med()], "supersedes": old}
    created = w.client.post(
        "/api/admin/users",
        headers=w.admin,
        json={
            "email": "dr.second@clinic.test",
            "name": "Dr. S. Second",
            "license_no": "GJ-777",
            "org_name": "Second Clinic",
        },
    ).json()
    w.client.post(
        "/api/auth/activate",
        json={
            "email": "dr.second@clinic.test",
            "token": created["activation_token"],
            "login_password": PASSWORD,
            "signing_password": SIGNING_PASSWORD,
        },
    )
    second = bearer(w.client, "dr.second@clinic.test")
    other = w.client.post(
        "/api/prescriptions",
        headers=second,
        json={**body, "signing_password": SIGNING_PASSWORD},
    )
    assert other.status_code == 404  # someone else's prescription looks like it does not exist
    assert verify(w, qr_for(old)).json()["result"] == "VALID"

    used = issue(w)
    assert dispense(w, used, pin=get_pin(w, used)).status_code == 200
    again = w.client.post(
        "/api/prescriptions",
        headers=w.doctor,
        json={**body, "supersedes": used, "signing_password": SIGNING_PASSWORD},
    )
    assert again.status_code == 409

    unknown = w.client.post(
        "/api/prescriptions",
        headers=w.doctor,
        json={**body, "supersedes": "no-such-id", "signing_password": SIGNING_PASSWORD},
    )
    assert unknown.status_code == 404


def test_an_expired_prescription_cannot_be_corrected_and_one_correction_only(w):
    clock.freeze("2026-11-02T09:00:00Z")
    old = issue(w, validity_days=1)
    first = issue(w, supersedes=old)
    again = w.client.post(
        "/api/prescriptions",
        headers=w.doctor,
        json={
            "patient_id": w.patient1,
            "medicines": [med()],
            "signing_password": SIGNING_PASSWORD,
            "supersedes": old,
        },
    )
    assert again.status_code == 409  # already replaced
    clock.advance(timedelta(days=45))
    late = w.client.post(
        "/api/prescriptions",
        headers=bearer(w.client, DOCTOR_EMAIL),
        json={
            "patient_id": w.patient1,
            "medicines": [med()],
            "signing_password": SIGNING_PASSWORD,
            "supersedes": first,
        },
    )
    assert late.status_code == 409

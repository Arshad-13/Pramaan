"""P5: the verification pipeline (read-only) and the patient PIN endpoint."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core import crypto, pin
from app.core.qr import build_qr
from app.main import app
from app.models import AuditLog, Prescription, SecurityEvent, VerificationAttempt
from tests.helpers import bearer, session
from tests.world import (
    build_world,
    dispense,
    get_pin,
    issue,
    med,
    qr_for,
    sql,
    stored,
    verify,
)


@pytest.fixture
def w(fresh_db):
    with TestClient(app) as client:
        yield build_world(client)


def result(response):
    assert response.status_code == 200, response.text
    return response.json()


def audit_actions():
    with session() as db:
        return [r.action for r in db.scalars(select(AuditLog).order_by(AuditLog.seq))]


# --- the happy path ---------------------------------------------------------------------------


def test_a_genuine_prescription_verifies(w):
    rx_id = issue(w)
    out = result(verify(w, qr_for(rx_id)))
    assert out["result"] == "VALID" and out["reason_codes"] == [] and out["can_dispense"] is True
    assert out["rx_id"] == rx_id and out["pin_required"] is True
    assert out["checks"] == {
        "signature_valid": True, "hash_match": True, "key_state": "ACTIVE", "doctor_active": True,
        "status": "ISSUED", "fills_remaining": 1, "not_expired": True,
        "content_check": "NOT_CHECKED", "file_integrity": None,
    }  # fmt: skip
    assert out["doctor"] == {"name": "Dr. A. Shah", "license_no": "GJ-12345"}
    assert out["medicines"] == [med()]
    assert out["risk"] == {"score": 0, "flags": [], "explanations": []}
    assert out["issued_at"].endswith("Z") and out["expires_at"].endswith("Z")


def test_the_patient_is_shown_as_initial_and_surname_only(w):
    out = result(verify(w, qr_for(issue(w))))
    assert out["patient"] == {"name": "R. Patel"}
    assert "Ravi" not in json.dumps(out)


def test_verification_never_consumes_the_prescription(w):
    rx_id = issue(w)
    for _ in range(5):
        assert result(verify(w, qr_for(rx_id)))["result"] == "VALID"
    row = stored(rx_id)
    assert row.fills_used == 0 and row.status.value == "ISSUED"


def test_every_verification_is_recorded_and_audited(w):
    rx_id = issue(w)
    verify(w, qr_for(rx_id))
    verify(w, "garbage")
    with session() as db:
        attempts = list(db.scalars(select(VerificationAttempt).order_by(VerificationAttempt.id)))
    assert [(a.result, a.rx_id) for a in attempts] == [("VALID", rx_id), ("INVALID_QR", None)]
    actions = audit_actions()
    assert "RX_VERIFIED" in actions and "RX_VERIFY_FAILED" in actions


def test_the_audit_trail_has_no_personal_data(w):
    rx_id = issue(w)
    verify(w, qr_for(rx_id))
    with session() as db:
        blob = json.dumps([(r.details_json, r.resource_id) for r in db.scalars(select(AuditLog))])
    for secret in ("Ravi", "Patel", "Amoxicillin", "GJ-12345"):
        assert secret not in blob


# --- early exits ---------------------------------------------------------------------------------


@pytest.mark.parametrize("junk", ["garbage", "PRM2.x.y.z.w", "", " ", "a" * 350])
def test_malformed_codes_are_invalid_qr_with_no_data(w, junk):
    out = verify(w, junk or "x").json()
    assert out["result"] == "INVALID_QR" and out["reason_codes"] == ["MALFORMED_QR"]
    assert out["doctor"] is None and out["patient"] is None and out["medicines"] is None
    assert out["can_dispense"] is False and out["rx_id"] is None


def test_a_well_formed_code_for_an_unknown_prescription_is_not_found(w):
    fake = build_qr("11111111-2222-4333-8444-555555555555", "0" * 16, "a" * 64, bytes(64))
    out = result(verify(w, fake))
    assert out["result"] == "NOT_FOUND" and out["doctor"] is None and out["rx_id"] is None


# --- tampering ---------------------------------------------------------------------------------


def reasons(w, rx_id, qr=None, headers=None):
    out = result(verify(w, qr or qr_for(rx_id), headers))
    assert out["result"] == "TAMPERED", out
    assert out["doctor"] is None and out["patient"] is None and out["medicines"] is None
    assert out["can_dispense"] is False
    return set(out["reason_codes"])


def test_a_flipped_bit_in_the_stored_payload_is_detected(w):
    rx_id = issue(w)
    blob = bytearray(stored(rx_id).payload_enc)
    blob[30] ^= 1
    sql("UPDATE prescriptions SET payload_enc = :b WHERE id = :i", b=bytes(blob), i=rx_id)
    assert "DB_RECORD_ALTERED" in reasons(w, rx_id)


def test_an_edited_payload_hash_column_is_detected(w):
    rx_id = issue(w)
    sql("UPDATE prescriptions SET payload_hash = :h WHERE id = :i", h="0" * 64, i=rx_id)
    assert "DB_RECORD_ALTERED" in reasons(w, rx_id)


def test_a_changed_qr_hash_is_detected(w):
    rx_id = issue(w)
    row = stored(rx_id)
    forged = build_qr(rx_id, row.key_id, "f" * 64, crypto.b64u_decode(row.signature_b64))
    assert "QR_HASH_MISMATCH" in reasons(w, rx_id, forged)


@pytest.mark.parametrize("bit_index", [0, 7, 31, 63])
def test_a_flipped_bit_in_the_qr_signature_is_detected(w, bit_index):
    rx_id = issue(w)
    row = stored(rx_id)
    sig = bytearray(crypto.b64u_decode(row.signature_b64))
    sig[bit_index] ^= 1
    forged = build_qr(rx_id, row.key_id, row.payload_hash, bytes(sig))
    assert "INVALID_SIGNATURE" in reasons(w, rx_id, forged)


def test_a_tampered_stored_signature_is_detected(w):
    rx_id = issue(w)
    row = stored(rx_id)
    sig = bytearray(crypto.b64u_decode(row.signature_b64))
    sig[10] ^= 1
    sql(
        "UPDATE prescriptions SET signature_b64 = :s WHERE id = :i",
        s=crypto.b64u_encode(bytes(sig)),
        i=rx_id,
    )
    assert "INVALID_SIGNATURE" in reasons(w, rx_id)


def test_a_qr_swapped_in_from_another_prescription_is_detected(w):
    first, second = issue(w), issue(w)
    row2 = stored(second)
    swapped = build_qr(
        first, row2.key_id, row2.payload_hash, crypto.b64u_decode(row2.signature_b64)
    )
    assert "QR_HASH_MISMATCH" in reasons(w, first, swapped)


def test_a_wrong_key_id_in_the_qr_is_detected(w):
    rx_id = issue(w)
    row = stored(rx_id)
    forged = build_qr(rx_id, "0" * 16, row.payload_hash, crypto.b64u_decode(row.signature_b64))
    assert "KEY_ID_MISMATCH" in reasons(w, rx_id, forged)


def test_extending_the_expiry_column_does_not_extend_the_prescription(w, frozen_clock):
    """The expiry that counts is the signed one. Editing the plain column is itself tampering."""
    rx_id = issue(w, validity_days=1)
    sql("UPDATE prescriptions SET expires_at = '2030-01-01 00:00:00.000000' WHERE id = :i", i=rx_id)
    assert "DB_RECORD_ALTERED" in reasons(w, rx_id)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE prescriptions SET max_fills = 3 WHERE id = :i",
        "UPDATE prescriptions SET issued_at = '2020-01-01 00:00:00.000000' WHERE id = :i",
        "UPDATE prescriptions SET doctor_id = (SELECT id FROM users WHERE email = 'dr.other@clinic.test') WHERE id = :i",
        "UPDATE prescriptions SET patient_id = (SELECT id FROM users WHERE email = 'sneha@example.test') WHERE id = :i",
    ],
)
def test_every_plain_column_is_cross_checked_against_the_signed_payload(w, statement):
    rx_id = issue(w)
    sql(statement, i=rx_id)
    assert "DB_RECORD_ALTERED" in reasons(w, rx_id)


def test_a_payload_swapped_between_prescriptions_is_detected(w):
    first, second = issue(w), issue(w, medicines=[med(dose_mg=900)])
    sql(
        "UPDATE prescriptions SET payload_enc = :b WHERE id = :i",
        b=stored(second).payload_enc,
        i=first,
    )
    assert "DB_RECORD_ALTERED" in reasons(w, first)  # wrong AAD: it cannot even be decrypted


def test_an_attacker_who_forges_a_new_payload_with_the_master_key_still_fails_the_signature(w):
    """Even with the encryption key, changing the dose invalidates the doctor's signature."""
    rx_id = issue(w)
    row = stored(rx_id)
    settings = get_settings()
    dek = crypto.unwrap_dek(
        settings.master_key_bytes, row.wrapped_dek, rx_id=rx_id, kek_version=row.kek_version
    )
    payload = json.loads(crypto.decrypt_payload(dek, rx_id, row.payload_enc))
    payload["medicines"][0]["dose_mg"] = 5000
    from app.core.canonical import canonical_bytes, sha256_hex

    forged = canonical_bytes(payload)
    sql(
        "UPDATE prescriptions SET payload_enc = :b, payload_hash = :h WHERE id = :i",
        b=crypto.encrypt_payload(dek, rx_id, forged),
        h=sha256_hex(forged),
        i=rx_id,
    )
    found = reasons(
        w,
        rx_id,
        build_qr(rx_id, row.key_id, sha256_hex(forged), crypto.b64u_decode(row.signature_b64)),
    )
    assert "INVALID_SIGNATURE" in found


# --- status, expiry, revocation ---------------------------------------------------------------------


def test_revoked_prescriptions_are_reported_with_their_verified_record(w):
    rx_id = issue(w)
    w.client.post(f"/api/prescriptions/{rx_id}/revoke", headers=w.doctor)
    out = result(verify(w, qr_for(rx_id)))
    assert out["result"] == "REVOKED" and out["reason_codes"] == ["RX_REVOKED"]
    assert out["can_dispense"] is False and out["doctor"]["name"] == "Dr. A. Shah"


def test_expiry_comes_from_the_signed_payload_on_the_injected_clock(w, frozen_clock):
    rx_id = issue(w, validity_days=2)
    qr = qr_for(rx_id)
    frozen_clock.advance(timedelta(days=2) - timedelta(seconds=1))
    # (sessions last 30 minutes, so sign in again after moving the clock)
    assert result(verify(w, qr, bearer(w.client, "pharm.a@example.test")))["result"] == "VALID"
    frozen_clock.advance(timedelta(seconds=1))
    out = result(verify(w, qr, bearer(w.client, "pharm.a@example.test")))
    assert (
        out["result"] == "EXPIRED"
        and out["checks"]["not_expired"] is False
        and out["can_dispense"] is False
    )


def test_a_revoked_signing_key_revokes_its_unused_prescriptions(w):
    rx_id = issue(w)
    sql("UPDATE doctor_keys SET status = 'REVOKED'")
    out = result(verify(w, qr_for(rx_id)))
    assert out["result"] == "REVOKED" and "DOCTOR_KEY_REVOKED" in out["reason_codes"]
    assert out["checks"]["key_state"] == "REVOKED"


def test_a_suspended_doctor_revokes_unused_prescriptions(w):
    rx_id = issue(w)
    doctor_id = w.client.get("/api/auth/me", headers=w.doctor).json()["public_id"]
    w.client.patch(f"/api/admin/users/{doctor_id}/deactivate", headers=w.admin)
    out = result(verify(w, qr_for(rx_id)))
    assert out["result"] == "REVOKED" and "DOCTOR_SUSPENDED" in out["reason_codes"]


def test_a_retired_key_still_verifies_old_prescriptions(w):
    rx_id = issue(w)
    rotated = w.client.post(
        "/api/keys/rotate",
        headers=w.doctor,
        json={
            "current_signing_password": "another-long-secret-phrase",
            "new_signing_password": "a-new-phrase-for-signing",
        },
    )
    assert rotated.status_code == 200
    out = result(verify(w, qr_for(rx_id)))
    assert out["result"] == "VALID" and out["checks"]["key_state"] == "RETIRED"


def test_a_high_risk_score_makes_a_prescription_suspicious_and_not_dispensable(w):
    rx_id = issue(w)
    sql(
        "UPDATE prescriptions SET risk_score = 75, risk_flags = '[\"UNKNOWN_DRUG\"]' WHERE id = :i",
        i=rx_id,
    )
    out = result(verify(w, qr_for(rx_id)))
    assert out["result"] == "SUSPICIOUS" and out["reason_codes"] == ["RISK_ABOVE_THRESHOLD"]
    assert (
        out["risk"]["score"] == 75
        and out["risk"]["flags"] == ["UNKNOWN_DRUG"]
        and out["can_dispense"] is False
    )


def test_a_score_just_below_the_threshold_is_valid(w):
    rx_id = issue(w)
    sql("UPDATE prescriptions SET risk_score = 59 WHERE id = :i", i=rx_id)
    assert result(verify(w, qr_for(rx_id)))["result"] == "VALID"


def test_precedence_tampered_beats_everything_and_hides_the_record(w, frozen_clock):
    rx_id = issue(w, validity_days=1)
    w.client.post(f"/api/prescriptions/{rx_id}/revoke", headers=w.doctor)
    frozen_clock.advance(timedelta(days=2))
    sql("UPDATE prescriptions SET payload_hash = :h WHERE id = :i", h="1" * 64, i=rx_id)
    found = reasons(w, rx_id, headers=bearer(w.client, "pharm.a@example.test"))
    # only tamper reasons: the revoked/expired reasons are not even reported for a forged record
    assert "DB_RECORD_ALTERED" in found and found <= {"DB_RECORD_ALTERED", "QR_HASH_MISMATCH"}


def test_precedence_revoked_beats_expired_and_used_beats_expired(w, frozen_clock):
    revoked, used = issue(w, validity_days=1), issue(w, validity_days=1)
    w.client.post(f"/api/prescriptions/{revoked}/revoke", headers=w.doctor)
    pin_value = get_pin(w, used)
    assert dispense(w, used, pin=pin_value).status_code == 200
    qr_revoked, qr_used = qr_for(revoked), qr_for(used)
    frozen_clock.advance(timedelta(days=2))
    fresh = bearer(w.client, "pharm.a@example.test")
    out = result(verify(w, qr_revoked, fresh))
    assert out["result"] == "REVOKED" and "RX_EXPIRED" in out["reason_codes"]
    out = result(verify(w, qr_used, fresh))
    assert out["result"] == "ALREADY_USED" and "RX_EXPIRED" in out["reason_codes"]


# --- who may verify ----------------------------------------------------------------------------------


def test_only_approved_pharmacists_can_verify(w):
    qr = qr_for(issue(w))
    for headers in (w.doctor, w.patient1_h, w.admin, w.auditor):
        assert verify(w, qr, headers).status_code == 403
    w.client.cookies.clear()
    assert w.client.post("/api/verify/qr", json={"qr_string": qr}).status_code == 401


def test_verify_input_is_validated(w):
    assert w.client.post("/api/verify/qr", headers=w.pharmacist_a, json={}).status_code == 422
    assert (
        w.client.post(
            "/api/verify/qr", headers=w.pharmacist_a, json={"qr_string": "x" * 500}
        ).status_code
        == 422
    )
    assert (
        w.client.post(
            "/api/verify/qr", headers=w.pharmacist_a, json={"qr_string": "ok", "extra": 1}
        ).status_code
        == 422
    )


# --- alerts ----------------------------------------------------------------------------------------


def events(w):
    return w.client.get("/api/admin/security-events", headers=w.admin).json()


def test_five_failed_verifications_raise_one_high_alert(w):
    for i in range(4):
        verify(w, f"garbage-{i}")
    assert events(w) == []
    verify(w, "garbage-4")
    verify(w, "garbage-5")  # more failures do not spam new alerts
    found = events(w)
    assert (
        len(found) == 1
        and found[0]["event_type"] == "FAILED_VERIFICATIONS"
        and found[0]["severity"] == "HIGH"
    )
    assert "SECURITY_ALERT" in audit_actions()


def test_failures_by_different_pharmacists_are_counted_separately(w):
    for i in range(3):
        verify(w, f"garbage-{i}", w.pharmacist_a)
        verify(w, f"garbage-{i}", w.pharmacist_b)
    assert events(w) == []


def test_failures_age_out_of_the_ten_minute_window(w, frozen_clock):
    for i in range(4):
        verify(w, f"garbage-{i}")
    frozen_clock.advance(timedelta(minutes=11))
    verify(w, "garbage-late")
    assert events(w) == []


def test_replay_by_another_pharmacist_raises_a_medium_alert(w):
    rx_id = issue(w)
    assert dispense(w, rx_id, pin=get_pin(w, rx_id), headers=w.pharmacist_a).status_code == 200
    out = result(verify(w, qr_for(rx_id), w.pharmacist_b))
    assert out["result"] == "ALREADY_USED"
    found = events(w)
    assert (
        len(found) == 1
        and found[0]["event_type"] == "POSSIBLE_REPLAY"
        and found[0]["severity"] == "MEDIUM"
    )
    assert json.loads(found[0]["details_json"]) == {"rx_id": rx_id}


def test_the_same_pharmacist_rescanning_is_not_a_replay(w):
    rx_id = issue(w)
    assert dispense(w, rx_id, pin=get_pin(w, rx_id), headers=w.pharmacist_a).status_code == 200
    assert result(verify(w, qr_for(rx_id), w.pharmacist_a))["result"] == "ALREADY_USED"
    assert events(w) == []


def test_the_audit_chain_stays_valid_through_all_of_this(w):
    rx_id = issue(w)
    verify(w, qr_for(rx_id))
    verify(w, "junk")
    dispense(w, rx_id, pin=get_pin(w, rx_id))
    check = w.client.get("/api/admin/audit/verify", headers=w.auditor).json()
    assert check["ok"] is True and check["first_bad_seq"] is None


# --- the patient PIN endpoint -----------------------------------------------------------------------


def test_the_patient_can_see_a_pin_that_matches_the_stored_secret(w, frozen_clock):
    rx_id = issue(w)
    response = w.client.get(f"/api/prescriptions/{rx_id}/pin", headers=w.patient1_h)
    assert response.status_code == 200
    body = response.json()
    assert len(body["pin"]) == 6 and body["pin"].isdigit()
    assert body["step_seconds"] == 120 and 1 <= body["seconds_remaining"] <= 120

    row = stored(rx_id)
    settings = get_settings()
    secret = crypto.unwrap_key(
        settings.master_key_bytes, row.redeem_secret_wrapped, rx_id=rx_id,
        kek_version=row.kek_version, purpose=b"redeem",
    )  # fmt: skip
    assert body["pin"] == pin.current_pin(secret, rx_id, frozen_clock.now_utc(), 120)


def test_the_pin_changes_each_time_step_and_never_enters_the_audit_log(w, frozen_clock):
    rx_id = issue(w)
    first = get_pin(w, rx_id)
    frozen_clock.advance(timedelta(seconds=240))
    second = get_pin(w, rx_id, headers=bearer(w.client, "ravi@example.test"))
    assert first != second
    with session() as db:
        blob = json.dumps([r.details_json for r in db.scalars(select(AuditLog))])
    assert first not in blob and second not in blob
    assert audit_actions().count("RX_PIN_VIEWED") == 2


def test_only_the_owning_patient_can_see_the_pin(w):
    rx_id = issue(w)
    url = f"/api/prescriptions/{rx_id}/pin"
    assert w.client.get(url, headers=w.patient2_h).status_code == 404
    for headers in (w.doctor, w.pharmacist_a, w.admin, w.auditor):
        assert w.client.get(url, headers=headers).status_code == 403


def test_no_pin_for_a_prescription_that_is_revoked_expired_used_or_pinless(w, frozen_clock):
    revoked = issue(w)
    w.client.post(f"/api/prescriptions/{revoked}/revoke", headers=w.doctor)
    assert (
        w.client.get(f"/api/prescriptions/{revoked}/pin", headers=w.patient1_h).status_code == 409
    )

    pinless = issue(w, require_pin=False)
    assert (
        w.client.get(f"/api/prescriptions/{pinless}/pin", headers=w.patient1_h).status_code == 404
    )

    short = issue(w, validity_days=1)
    frozen_clock.advance(timedelta(days=1, seconds=1))
    fresh = bearer(w.client, "ravi@example.test")
    assert w.client.get(f"/api/prescriptions/{short}/pin", headers=fresh).status_code == 409


def test_prescription_summaries_tell_the_patient_whether_a_pin_applies(w):
    issue(w)
    issue(w, require_pin=False)
    rows = w.client.get("/api/prescriptions/mine", headers=w.patient1_h).json()
    assert sorted(r["require_pin"] for r in rows) == [False, True]


def test_stored_prescriptions_are_untouched_by_reading_the_pin(w):
    rx_id = issue(w)
    before = stored(rx_id)
    get_pin(w, rx_id)
    after = stored(rx_id)
    assert (before.fills_used, before.status, before.payload_enc) == (
        after.fills_used,
        after.status,
        after.payload_enc,
    )
    with session() as db:
        assert (
            db.get(Prescription, rx_id) is not None
            and db.scalars(select(SecurityEvent)).first() is None
        )


def test_recent_activity_counts_only_my_checks_today(w):
    qr = qr_for(issue(w))
    verify(w, qr)
    verify(w, "PRM2.not-a-real-code")
    verify(w, qr, w.pharmacist_b)
    body = w.client.get("/api/verify/recent", headers=w.pharmacist_a).json()
    assert (
        body["verified_today"] == 1 and body["flagged_today"] == 1 and body["dispensed_today"] == 0
    )
    assert [r["result"] for r in body["recent"]] == ["INVALID_QR", "VALID"]  # newest first
    assert body["recent"][1]["rx_ref"] and len(body["recent"][1]["rx_ref"]) == 8
    assert body["recent"][0]["rx_ref"] is None
    other = w.client.get("/api/verify/recent", headers=w.pharmacist_b).json()
    assert other["verified_today"] == 1 and other["flagged_today"] == 0

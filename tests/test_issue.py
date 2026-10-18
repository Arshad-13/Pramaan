"""P4: issuing prescriptions, encrypted storage, downloads, revocation, lookup, key rotation."""

from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import get_settings
from app.core import crypto
from app.core.canonical import sha256_hex
from app.core.keys import load_public_key
from app.core.qr import build_qr, decode_qr, parse_qr
from app.main import app
from app.models import AuditLog, DoctorKey, Prescription, Role, RxStatus
from tests.helpers import PASSWORD, SIGNING_PASSWORD, bearer, login, make_user, session

DOCTOR_EMAIL = "dr.shah@clinic.test"


def med(**o):
    return {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5, **o}


def body(patient_id, **o):
    return {
        "patient_id": patient_id,
        "medicines": [med()],
        "notes": "After food",
        "validity_days": 30,
        "max_fills": 1,
        "signing_password": SIGNING_PASSWORD,
        **o,
    }


@pytest.fixture
def w(fresh_db):
    with TestClient(app) as client:
        make_user("admin@example.test", Role.admin)
        admin = bearer(client, "admin@example.test")
        created = client.post(
            "/api/admin/users",
            headers=admin,
            json={"email": DOCTOR_EMAIL, "name": "Dr. A. Shah", "license_no": "GJ-12345",
                  "org_name": "Shah Clinic, Surat"},
        ).json()  # fmt: skip
        client.post(
            "/api/auth/activate",
            json={"email": DOCTOR_EMAIL, "token": created["activation_token"],
                  "login_password": PASSWORD, "signing_password": SIGNING_PASSWORD},
        )  # fmt: skip
        patient1 = make_user("ravi@example.test", Role.patient, name="Ravi Patel")
        patient2 = make_user("sneha@example.test", Role.patient, name="Sneha Rao")
        make_user("dr.other@clinic.test", Role.doctor, name="Dr. B. Other")
        make_user("pharm@example.test", Role.pharmacist)
        yield SimpleNamespace(
            client=client,
            admin=admin,
            doctor=bearer(client, DOCTOR_EMAIL),
            other_doctor=bearer(client, "dr.other@clinic.test"),
            patient1=patient1,
            patient2=patient2,
            patient1_h=bearer(client, "ravi@example.test"),
            patient2_h=bearer(client, "sneha@example.test"),
            pharmacist=bearer(client, "pharm@example.test"),
        )


def issue(w, patient=None, **o):
    return w.client.post(
        "/api/prescriptions", headers=w.doctor, json=body(patient or w.patient1, **o)
    )


def stored(rx_id: str) -> Prescription:
    with session() as db:
        row = db.get(Prescription, rx_id)
        db.expunge(row)
        return row


def decrypt_stored(row: Prescription) -> bytes:
    settings = get_settings()
    dek = crypto.unwrap_dek(
        settings.master_key_bytes, row.wrapped_dek, rx_id=row.id, kek_version=row.kek_version
    )
    return crypto.decrypt_payload(dek, row.id, row.payload_enc)


def pdf_page(pdf: bytes):
    return pymupdf.open(stream=pdf, filetype="pdf")[0]


def audit_rows():
    with session() as db:
        return list(db.scalars(select(AuditLog).order_by(AuditLog.seq)))


# --- issuing -----------------------------------------------------------------------------------


def test_issue_returns_an_id_and_stores_only_ciphertext(w):
    response = issue(w)
    assert response.status_code == 201, response.text
    out = response.json()
    rx_id = out["rx_id"]
    assert len(rx_id) == 36 and out["max_fills"] == 1 and len(out["fingerprint"]) == 14
    assert out["risk"] == {"score": 0, "flags": [], "explanations": []} and out["warnings"] == []
    assert "qr" not in json.dumps(out).lower()  # the QR text is only inside the PDF

    row = stored(rx_id)
    for secret in (b"Amoxicillin", b"Ravi", b"After food", b"Shah"):
        assert secret not in row.payload_enc  # payload is encrypted at rest
    on_disk = Path(row.pdf_path).read_bytes()
    assert (
        not on_disk.startswith(b"%PDF") and b"Amoxicillin" not in on_disk and b"Ravi" not in on_disk
    )


def test_the_owner_can_download_a_decryptable_pdf_with_the_signed_content(w):
    rx_id = issue(w).json()["rx_id"]
    response = w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    page = pdf_page(response.content)
    shown = page.get_text("text")
    for expected in ("Shah Clinic, Surat", "Dr. A. Shah", "GJ-12345", "Patient: Ravi Patel",
                     "Amoxicillin", "500 mg", "TDS", "5 days", "After food"):  # fmt: skip
        assert expected in shown
    assert hashlib_sha256(response.content) == stored(rx_id).pdf_sha256


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_signature_hash_and_qr_all_agree(w):
    rx_id = issue(w).json()["rx_id"]
    row = stored(rx_id)
    canonical = decrypt_stored(row)
    assert sha256_hex(canonical) == row.payload_hash

    with session() as db:
        key = db.get(DoctorKey, row.key_id)
        public_key = load_public_key(key.public_key_pem)
    signature = crypto.b64u_decode(row.signature_b64)
    assert crypto.verify(public_key, canonical, signature)
    assert not crypto.verify(public_key, canonical + b" ", signature)

    payload = json.loads(canonical)
    assert payload["rx_id"] == rx_id and payload["key_id"] == row.key_id
    assert payload["doctor"]["name"] == "Dr. A. Shah" and payload["patient"]["name"] == "Ravi Patel"
    assert row.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ") == payload["expires_at"]

    pdf = w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor).content
    pix = pdf_page(pdf).get_pixmap(dpi=200)
    image = cv2.cvtColor(
        np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3), cv2.COLOR_RGB2BGR
    )
    scanned = decode_qr(image)
    assert scanned == build_qr(rx_id, row.key_id, row.payload_hash, signature)
    assert parse_qr(scanned).payload_hash == row.payload_hash


def test_times_are_seconds_precision_utc_from_the_injectable_clock(w, frozen_clock):
    out = issue(w, validity_days=45).json()
    assert out["issued_at"].startswith("2026-10-18T10:30:00")
    assert out["expires_at"].startswith("2026-12-02T10:30:00")
    payload = json.loads(decrypt_stored(stored(out["rx_id"])))
    assert (
        payload["issued_at"] == "2026-10-18T10:30:00Z"
        and payload["expires_at"] == "2026-12-02T10:30:00Z"
    )


def test_issue_writes_one_audit_entry_without_personal_data(w):
    rx_id = issue(w).json()["rx_id"]
    issued = [r for r in audit_rows() if r.action == "RX_ISSUED"]
    assert len(issued) == 1 and issued[0].resource_id == rx_id
    everything = json.dumps([(r.details_json, r.resource_id, r.action) for r in audit_rows()])
    for secret in ("Amoxicillin", "Ravi", "After food", SIGNING_PASSWORD, "Shah"):
        assert secret not in everything
    assert json.loads(issued[0].details_json)["medicines"] == 1


def test_each_prescription_gets_its_own_key_and_nonce(w):
    a, b = stored(issue(w).json()["rx_id"]), stored(issue(w).json()["rx_id"])
    assert a.wrapped_dek != b.wrapped_dek and a.payload_enc != b.payload_enc
    assert a.redeem_secret_wrapped and a.redeem_secret_wrapped != b.redeem_secret_wrapped


def test_pin_secret_is_optional(w):
    row = stored(issue(w, require_pin=False).json()["rx_id"])
    assert row.require_pin is False and row.redeem_secret_wrapped is None


# --- access control ----------------------------------------------------------------------------


def test_only_the_doctor_and_the_patient_can_download(w):
    rx_id = issue(w).json()["rx_id"]
    url = f"/api/prescriptions/{rx_id}/pdf"
    assert w.client.get(url, headers=w.patient1_h).status_code == 200
    assert (
        w.client.get(url, headers=w.patient2_h).status_code == 404
    )  # someone else's: 404, not 403
    assert w.client.get(url, headers=w.other_doctor).status_code == 404
    assert w.client.get(url, headers=w.pharmacist).status_code == 403
    assert w.client.get(url, headers=w.admin).status_code == 403
    w.client.cookies.clear()
    assert w.client.get(url).status_code == 401
    assert w.client.get("/api/prescriptions/not-a-real-id/pdf", headers=w.doctor).status_code == 404


def test_downloads_are_audited(w):
    rx_id = issue(w).json()["rx_id"]
    w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.patient1_h)
    assert [r.actor_role for r in audit_rows() if r.action == "RX_PDF_DOWNLOADED"] == ["patient"]


def test_only_doctors_can_issue(w):
    for headers in (w.patient1_h, w.pharmacist, w.admin):
        assert (
            w.client.post("/api/prescriptions", headers=headers, json=body(w.patient1)).status_code
            == 403
        )


def test_a_stored_pdf_swapped_between_prescriptions_cannot_be_read(w):
    first, second = issue(w).json()["rx_id"], issue(w).json()["rx_id"]
    shutil.copyfile(stored(first).pdf_path, stored(second).pdf_path)  # attacker swaps the files
    assert w.client.get(f"/api/prescriptions/{second}/pdf", headers=w.doctor).status_code == 404
    assert w.client.get(f"/api/prescriptions/{first}/pdf", headers=w.doctor).status_code == 200


def test_a_modified_stored_pdf_is_refused(w):
    rx_id = issue(w).json()["rx_id"]
    path = Path(stored(rx_id).pdf_path)
    blob = bytearray(path.read_bytes())
    blob[40] ^= 1
    path.write_bytes(bytes(blob))
    assert w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor).status_code == 404


# --- signing password and lockout --------------------------------------------------------------


def test_wrong_signing_password_is_a_generic_403_and_creates_nothing(w):
    response = issue(w, signing_password="not-the-right-password")
    assert response.status_code == 403
    assert response.json()["detail"] == "Could not unlock your signing key."
    with session() as db:
        assert db.scalar(select(Prescription.id)) is None
    assert [r.action for r in audit_rows()].count("SIGN_UNLOCK_FAIL") == 1


def test_the_login_password_does_not_unlock_the_signing_key(w):
    assert issue(w, signing_password=PASSWORD).status_code == 403


def test_five_wrong_passwords_lock_signing_even_for_the_right_one(w, frozen_clock):
    for _ in range(5):
        assert issue(w, signing_password="wrong-password-123").status_code == 403
    locked = issue(w)  # correct password, but locked
    assert locked.status_code == 423 and "locked" in locked.json()["detail"].lower()
    actions = [r.action for r in audit_rows()]
    assert actions.count("SIGN_UNLOCK_FAIL") == 5 and actions.count("SIGN_LOCKED") == 1

    frozen_clock.advance(timedelta(minutes=14))
    assert issue(w).status_code == 423
    frozen_clock.advance(timedelta(minutes=2))
    assert issue(w).status_code == 201


def test_a_correct_password_resets_the_failure_counter(w):
    for _ in range(4):
        issue(w, signing_password="wrong-password-123")
    assert issue(w).status_code == 201
    for _ in range(4):
        issue(w, signing_password="wrong-password-123")
    assert issue(w).status_code == 201  # never reached five in a row


def test_invalid_input_does_not_count_as_a_password_attempt(w):
    bad = body(w.patient1, medicines=[med(name="W" * 40)], signing_password="wrong-password-123")
    assert w.client.post("/api/prescriptions", headers=w.doctor, json=bad).status_code == 400
    with session() as db:
        assert db.scalars(select(DoctorKey)).one().failed_unlocks == 0


def test_issuing_needs_an_active_key(w):
    with session() as db:
        db.execute(text("UPDATE doctor_keys SET status = 'REVOKED'"))
        db.commit()
    response = issue(w)
    assert response.status_code == 403 and "signing key" in response.json()["detail"]


# --- validation --------------------------------------------------------------------------------


def test_unknown_and_non_patient_ids_are_404(w):
    assert issue(w, patient="00000000-0000-0000-0000-000000000000").status_code == 404
    admin_id = w.client.get("/api/auth/me", headers=w.admin).json()["public_id"]
    assert issue(w, patient=admin_id).status_code == 404


@pytest.mark.parametrize(
    "override",
    [
        {"medicines": []},
        {"medicines": [med()] * 9},
        {"medicines": [med(dose_mg=0)]},
        {"medicines": [med(dose_mg=100000)]},
        {"medicines": [med(frequency="WEEKLY")]},
        {"medicines": [med(duration_days=0)]},
        {"medicines": [med(name="x")]},
        {"validity_days": 91},
        {"validity_days": 0},
        {"max_fills": 6},
        {"age_years": 130},
        {"notes": "x" * 501},
        {"is_admin": True},  # unknown fields are refused
        {"medicines": [{**med(), "extra": 1}]},
    ],
)
def test_input_validation(w, override):
    assert issue(w, **override).status_code == 422


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"medicines": [med(name="\u092a\u0930\u093f\u0902")]}, "cannot be printed"),
        ({"medicines": [med(name="W" * 40)]}, "too long"),
        ({"notes": "\n".join(["line"] * 6)}, "printed lines"),
    ],
)
def test_content_that_cannot_be_printed_faithfully_is_refused(w, override, fragment):
    response = issue(w, **override)
    assert response.status_code == 400 and fragment in response.json()["detail"]


def test_hidden_characters_are_rejected(w):
    assert issue(w, medicines=[med(name="Amox\u202eicillin")]).status_code == 422


def test_notes_may_span_lines_and_age_is_printed(w):
    response = issue(w, notes="Take with water.\nAvoid alcohol.", age_years=34)
    assert response.status_code == 201
    shown = pdf_page(
        w.client.get(f"/api/prescriptions/{response.json()['rx_id']}/pdf", headers=w.doctor).content
    ).get_text("text")
    assert "Avoid alcohol." in shown and "Patient: Ravi Patel, 34 yrs" in shown


def test_eight_medicines_fit_on_one_page(w):
    meds = [med(name=f"Medicine {i}", dose_mg=100 + i) for i in range(8)]
    assert issue(w, medicines=meds).status_code == 201


def test_a_failed_commit_leaves_no_orphan_file(w, monkeypatch):
    from sqlalchemy.orm import Session

    storage = Path(get_settings().storage_dir)
    before = set(storage.glob("*.pdf.enc"))
    real_commit = Session.commit

    def boom(self):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Session, "commit", boom)
    quiet = TestClient(app, raise_server_exceptions=False, headers=w.doctor)
    assert quiet.post("/api/prescriptions", json=body(w.patient1)).status_code == 500
    monkeypatch.setattr(Session, "commit", real_commit)
    assert set(storage.glob("*.pdf.enc")) == before


# --- listing -----------------------------------------------------------------------------------


def test_doctors_and_patients_each_see_only_their_own(w):
    mine = issue(w, w.patient1).json()["rx_id"]
    for_other = issue(w, w.patient2).json()["rx_id"]
    # reassign the second prescription to another doctor, straight in the table
    with session() as db:
        db.execute(
            text(
                "UPDATE prescriptions SET doctor_id = "
                "(SELECT id FROM users WHERE email = 'dr.other@clinic.test') WHERE id = :i"
            ),
            {"i": for_other},
        )
        db.commit()

    doctor_view = w.client.get("/api/prescriptions/mine", headers=w.doctor).json()
    assert [r["id"] for r in doctor_view] == [mine]
    row = doctor_view[0]
    assert row["patient_name"] == "Ravi Patel" and row["doctor_name"] == "Dr. A. Shah"
    assert row["medicines"][0]["name"] == "Amoxicillin" and row["status"] == "ISSUED"
    assert row["risk_score"] == 0 and row["readable"] is True

    patient_view = w.client.get("/api/prescriptions/mine", headers=w.patient1_h).json()
    assert [r["id"] for r in patient_view] == [mine] and patient_view[0]["risk_score"] is None
    # patient 2 sees only their own prescription, which now belongs to the other doctor
    assert [
        r["id"] for r in w.client.get("/api/prescriptions/mine", headers=w.patient2_h).json()
    ] == [for_other]
    assert [
        r["id"] for r in w.client.get("/api/prescriptions/mine", headers=w.other_doctor).json()
    ] == [for_other]
    assert w.client.get("/api/prescriptions/mine", headers=w.pharmacist).status_code == 403


def test_status_reads_expired_after_the_signed_expiry(w, frozen_clock):
    issue(w, validity_days=1)
    assert w.client.get("/api/prescriptions/mine", headers=w.doctor).json()[0]["status"] == "ISSUED"
    frozen_clock.advance(timedelta(days=1, seconds=1))
    fresh = bearer(w.client, DOCTOR_EMAIL)  # the earlier 30-minute session has expired too
    assert w.client.get("/api/prescriptions/mine", headers=fresh).json()[0]["status"] == "EXPIRED"


def test_a_tampered_stored_payload_is_flagged_unreadable_not_shown(w):
    rx_id = issue(w).json()["rx_id"]
    row = stored(rx_id)
    flipped = bytes([row.payload_enc[20] ^ 1])
    with session() as db:
        db.execute(
            text("UPDATE prescriptions SET payload_enc = :b WHERE id = :i"),
            {"b": row.payload_enc[:20] + flipped + row.payload_enc[21:], "i": rx_id},
        )
        db.commit()
    entry = w.client.get("/api/prescriptions/mine", headers=w.doctor).json()[0]
    assert entry["readable"] is False and entry["medicines"] == [] and entry["patient_name"] is None


# --- revoking ----------------------------------------------------------------------------------


def test_revoke_flow(w):
    rx_id = issue(w).json()["rx_id"]

    def revoke(headers):
        return w.client.post(f"/api/prescriptions/{rx_id}/revoke", headers=headers)

    assert revoke(w.other_doctor).status_code == 404
    assert revoke(w.patient1_h).status_code == 403
    assert revoke(w.pharmacist).status_code == 403
    ok = revoke(w.doctor)
    assert ok.status_code == 200 and ok.json()["status"] == "REVOKED"
    assert stored(rx_id).status == RxStatus.REVOKED
    assert revoke(w.doctor).status_code == 409
    assert [r.action for r in audit_rows()].count("RX_REVOKED") == 1
    assert (
        w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor).status_code == 200
    )  # still viewable


def test_a_dispensed_prescription_cannot_be_revoked(w):
    rx_id = issue(w).json()["rx_id"]
    with session() as db:
        db.execute(
            text("UPDATE prescriptions SET status='DISPENSED', fills_used=1 WHERE id=:i"),
            {"i": rx_id},
        )
        db.commit()
    assert w.client.post(f"/api/prescriptions/{rx_id}/revoke", headers=w.doctor).status_code == 409


# --- patient lookup ----------------------------------------------------------------------------


def lookup(w, headers=None, **params):
    return w.client.get("/api/patients/lookup", headers=headers or w.doctor, params=params)


def test_lookup_by_exact_email_or_code(w):
    found = lookup(w, email="RAVI@example.test")
    assert found.status_code == 200
    assert found.json()["public_id"] == w.patient1 and found.json()["name"] == "Ravi Patel"
    code = found.json()["patient_code"]
    assert lookup(w, code=code.lower()).json()["public_id"] == w.patient1


@pytest.mark.parametrize(
    "params", [{"email": "ravi@example"}, {"email": "rav"}, {"code": "T-"}, {"email": "x@y.test"}]
)
def test_partial_or_unknown_matches_find_nothing(w, params):
    assert lookup(w, **params).status_code == 404


def test_lookup_needs_exactly_one_parameter(w):
    assert lookup(w).status_code == 400
    assert lookup(w, email="ravi@example.test", code="X").status_code == 400


def test_lookup_only_returns_active_patients_and_only_to_doctors(w):
    assert lookup(w, email=DOCTOR_EMAIL).status_code == 404  # a doctor is not a patient
    with session() as db:
        db.execute(text("UPDATE users SET is_active = 0 WHERE email = 'ravi@example.test'"))
        db.commit()
    assert lookup(w, email="ravi@example.test").status_code == 404
    for headers in (w.patient2_h, w.pharmacist, w.admin):
        assert lookup(w, headers=headers, email="sneha@example.test").status_code == 403


def test_lookup_exposes_only_id_name_and_code(w):
    assert set(lookup(w, email="ravi@example.test").json()) == {"public_id", "name", "patient_code"}


# --- key rotation ------------------------------------------------------------------------------


def rotate(w, current=SIGNING_PASSWORD, new="a-brand-new-signing-phrase", headers=None):
    return w.client.post(
        "/api/keys/rotate",
        headers=headers or w.doctor,
        json={"current_signing_password": current, "new_signing_password": new},
    )


def test_rotation_retires_the_old_key_and_old_prescriptions_still_verify(w):
    first = issue(w).json()["rx_id"]
    old_key_id = stored(first).key_id
    response = rotate(w)
    assert response.status_code == 200 and response.json()["status"] == "ACTIVE"
    new_key_id = response.json()["key_id"]
    assert new_key_id != old_key_id

    keys = {
        k["key_id"]: k["status"] for k in w.client.get("/api/keys/mine", headers=w.doctor).json()
    }
    assert keys == {old_key_id: "RETIRED", new_key_id: "ACTIVE"}

    # the first prescription is still verifiable with the retired key...
    with session() as db:
        public_key = load_public_key(db.get(DoctorKey, old_key_id).public_key_pem)
    row = stored(first)
    assert crypto.verify(public_key, decrypt_stored(row), crypto.b64u_decode(row.signature_b64))
    # ...new prescriptions use the new key, and the OLD password no longer signs
    assert (
        stored(issue(w, signing_password="a-brand-new-signing-phrase").json()["rx_id"]).key_id
        == new_key_id
    )
    assert issue(w).status_code == 403
    assert "KEY_ROTATED" in [r.action for r in audit_rows()]


def test_rotation_checks_the_current_password_and_the_lockout(w):
    for _ in range(5):
        assert rotate(w, current="wrong-password-123").status_code == 403
    assert rotate(w).status_code == 423  # the same lockout as issuing


@pytest.mark.parametrize(
    "new", ["short", PASSWORD, SIGNING_PASSWORD]  # weak / same as login / same as current
)
def test_rotation_rejects_unsuitable_new_passwords(w, new):
    assert rotate(w, new=new).status_code == 400


def test_only_doctors_manage_keys(w):
    for headers in (w.patient1_h, w.pharmacist, w.admin):
        assert w.client.get("/api/keys/mine", headers=headers).status_code == 403
        assert rotate(w, headers=headers).status_code == 403


def test_keys_endpoint_never_returns_key_material(w):
    keys = w.client.get("/api/keys/mine", headers=w.doctor).json()
    assert set(keys[0]) == {"key_id", "status", "created_at", "revoked_at", "revoke_reason"}


# --- suspended doctors -------------------------------------------------------------------------


def test_a_suspended_doctor_cannot_issue(w):
    doctor_id = w.client.get("/api/auth/me", headers=w.doctor).json()["public_id"]
    assert (
        w.client.patch(f"/api/admin/users/{doctor_id}/deactivate", headers=w.admin).status_code
        == 200
    )
    assert issue(w).status_code == 401  # the session is gone immediately
    assert login(w.client, DOCTOR_EMAIL).status_code == 403

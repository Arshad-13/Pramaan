"""A ready-made cast for API tests: admin, an activated doctor, patients, two pharmacists.

`build_world(client)` creates everyone through the real flows where it matters (the doctor is
created by the admin and activates, so a real signing key exists) and returns handy helpers for
issuing, verifying and dispensing.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.core.crypto import b64u_decode
from app.core.qr import build_qr
from app.models import Prescription, Role
from tests.helpers import PASSWORD, SIGNING_PASSWORD, bearer, make_user, session

DOCTOR_EMAIL = "dr.shah@clinic.test"


@dataclass
class World:
    client: TestClient
    admin: dict
    doctor: dict
    other_doctor: dict
    patient1: str  # public ids
    patient2: str
    patient1_h: dict
    patient2_h: dict
    pharmacist_a: dict
    pharmacist_b: dict
    pharmacist_a_id: str
    pharmacist_b_id: str
    auditor: dict


def med(**o):
    return {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5, **o}


def build_world(client: TestClient) -> World:
    make_user("admin@example.test", Role.admin)
    make_user("auditor@example.test", Role.auditor)
    admin = bearer(client, "admin@example.test")
    created = client.post(
        "/api/admin/users",
        headers=admin,
        json={
            "email": DOCTOR_EMAIL,
            "name": "Dr. A. Shah",
            "license_no": "GJ-12345",
            "org_name": "Shah Clinic, Surat",
        },
    ).json()
    client.post(
        "/api/auth/activate",
        json={
            "email": DOCTOR_EMAIL,
            "token": created["activation_token"],
            "login_password": PASSWORD,
            "signing_password": SIGNING_PASSWORD,
        },
    )
    patient1 = make_user("ravi@example.test", Role.patient, name="Ravi Patel")
    patient2 = make_user("sneha@example.test", Role.patient, name="Sneha Rao")
    make_user("dr.other@clinic.test", Role.doctor, name="Dr. B. Other")
    pa = make_user("pharm.a@example.test", Role.pharmacist, name="Asha Mehta")
    pb = make_user("pharm.b@example.test", Role.pharmacist, name="Bharat Joshi")
    return World(
        client=client,
        admin=admin,
        doctor=bearer(client, DOCTOR_EMAIL),
        other_doctor=bearer(client, "dr.other@clinic.test"),
        patient1=patient1,
        patient2=patient2,
        patient1_h=bearer(client, "ravi@example.test"),
        patient2_h=bearer(client, "sneha@example.test"),
        pharmacist_a=bearer(client, "pharm.a@example.test"),
        pharmacist_b=bearer(client, "pharm.b@example.test"),
        pharmacist_a_id=pa,
        pharmacist_b_id=pb,
        auditor=bearer(client, "auditor@example.test"),
    )


def issue(w: World, patient: str | None = None, **overrides) -> str:
    body = {
        "patient_id": patient or w.patient1,
        "medicines": [med()],
        "notes": "After food",
        "validity_days": 30,
        "max_fills": 1,
        "signing_password": SIGNING_PASSWORD,
        **overrides,
    }
    response = w.client.post("/api/prescriptions", headers=w.doctor, json=body)
    assert response.status_code == 201, response.text
    return response.json()["rx_id"]


def stored(rx_id: str) -> Prescription:
    with session() as db:
        row = db.get(Prescription, rx_id)
        db.expunge(row)
        return row


def qr_for(rx_id: str) -> str:
    """The QR text that was printed on the prescription, rebuilt from the stored values."""
    row = stored(rx_id)
    return build_qr(row.id, row.key_id, row.payload_hash, b64u_decode(row.signature_b64))


def verify(w: World, qr: str, headers: dict | None = None):
    return w.client.post(
        "/api/verify/qr", headers=headers or w.pharmacist_a, json={"qr_string": qr}
    )


def get_pin(w: World, rx_id: str, headers: dict | None = None) -> str:
    response = w.client.get(f"/api/prescriptions/{rx_id}/pin", headers=headers or w.patient1_h)
    assert response.status_code == 200, response.text
    return response.json()["pin"]


def dispense(w: World, rx_id: str, qr: str | None = None, pin: str | None = None,
             headers: dict | None = None, **extra):  # fmt: skip
    body = {"qr_string": qr or qr_for(rx_id), **extra}
    if pin is not None:
        body["patient_pin"] = pin
    return w.client.post(
        f"/api/prescriptions/{rx_id}/dispense", headers=headers or w.pharmacist_a, json=body
    )


def sql(statement: str, **params) -> None:
    """Attacker's view: change the database underneath the application."""
    from sqlalchemy import text

    with session() as db:
        db.execute(text(statement), params)
        db.commit()

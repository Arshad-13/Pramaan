"""P3: doctor activation, pharmacist approval, suspension, and the audit/admin endpoints."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import crypto
from app.core.keys import ProtectedKey, WrongPasswordError, unlock_private_key
from app.main import app
from app.models import (
    ActivationToken,
    ApprovalStatus,
    AuditLog,
    DoctorKey,
    KeyStatus,
    Role,
)
from tests.helpers import PASSWORD, SIGNING_PASSWORD, bearer, get_user, login, make_user, session

DOCTOR = {
    "email": "dr.shah@clinic.test",
    "name": "Dr. A. Shah",
    "license_no": "GJ-12345",
    "org_name": "Shah Clinic, Surat",
}


@pytest.fixture
def client(fresh_db):
    with TestClient(app) as c:
        make_user("admin@example.test", Role.admin)
        make_user("auditor@example.test", Role.auditor)
        yield c


@pytest.fixture
def admin(client):
    return bearer(client, "admin@example.test")


@pytest.fixture
def auditor(client):
    return bearer(client, "auditor@example.test")


def create_doctor(client, admin, **overrides):
    response = client.post("/api/admin/users", headers=admin, json={**DOCTOR, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def activate(client, token, **overrides):
    body = {
        "email": DOCTOR["email"],
        "token": token,
        "login_password": PASSWORD,
        "signing_password": SIGNING_PASSWORD,
        **overrides,
    }
    return client.post("/api/auth/activate", json=body)


def active_doctor(client, admin):
    created = create_doctor(client, admin)
    assert activate(client, created["activation_token"]).status_code == 204
    return created


# --- creating doctors --------------------------------------------------------------------------


def test_admin_creates_a_doctor_without_a_password_and_gets_a_one_time_token(client, admin):
    created = create_doctor(client, admin)
    assert len(created["activation_token"]) >= 20
    assert created["user"]["role"] == "doctor" and created["user"]["license_no"] == "GJ-12345"
    assert "password" not in json.dumps(created["user"]).lower()
    user = get_user(DOCTOR["email"])
    assert user.password_hash is None and user.is_active


def test_only_a_hash_of_the_token_is_stored(client, admin):
    token = create_doctor(client, admin)["activation_token"]
    with session() as db:
        row = db.scalars(select(ActivationToken)).one()
        assert row.token_sha256 == hashlib.sha256(token.encode()).hexdigest()
        assert token not in row.token_sha256


@pytest.mark.parametrize("who", ["patient", "doctor", "pharmacist", "auditor"])
def test_non_admins_cannot_create_doctors(client, who):
    make_user(f"{who}@other.test", Role(who))
    response = client.post(
        "/api/admin/users", headers=bearer(client, f"{who}@other.test"), json=DOCTOR
    )
    assert response.status_code == 403


def test_duplicate_and_invalid_doctor_requests(client, admin):
    create_doctor(client, admin)
    assert client.post("/api/admin/users", headers=admin, json=DOCTOR).status_code == 409
    assert (
        client.post("/api/admin/users", headers=admin, json={**DOCTOR, "email": "bad"}).status_code
        == 422
    )
    assert (
        client.post("/api/admin/users", headers=admin, json={**DOCTOR, "role": "admin"}).status_code
        == 422
    )


def test_doctor_cannot_sign_in_before_activating(client, admin):
    create_doctor(client, admin)
    assert login(client, DOCTOR["email"]).status_code == 401


# --- activating --------------------------------------------------------------------------------


def test_activation_creates_a_protected_key_and_enables_sign_in(client, admin):
    created = create_doctor(client, admin)
    assert activate(client, created["activation_token"]).status_code == 204
    assert login(client, DOCTOR["email"]).status_code == 200

    with session() as db:
        key = db.scalars(select(DoctorKey)).one()
        assert key.status == KeyStatus.ACTIVE and len(key.key_id) == 16
        assert key.kdf_iterations >= 100_000
        assert b"PRIVATE KEY" not in key.enc_private_key  # stored encrypted, not as a PEM
        protected = ProtectedKey(
            key.kdf, key.kdf_salt, key.kdf_iterations, key.nonce, key.enc_private_key
        )
        private = unlock_private_key(protected, SIGNING_PASSWORD, key_id=key.key_id)
        assert crypto.verify(private.public_key(), b"m", crypto.sign(private, b"m"))
        with pytest.raises(WrongPasswordError):  # the LOGIN password does not unlock the key
            unlock_private_key(protected, PASSWORD, key_id=key.key_id)


def test_admin_never_sees_either_password(client, admin):
    created = create_doctor(client, admin)
    activate(client, created["activation_token"])
    with session() as db:
        blob = json.dumps(
            [(r.details_json, r.action, r.resource_id) for r in db.scalars(select(AuditLog))]
        )
        assert PASSWORD not in blob and SIGNING_PASSWORD not in blob
        assert created["activation_token"] not in blob
    assert PASSWORD not in json.dumps(created) and SIGNING_PASSWORD not in json.dumps(created)


def test_signing_password_must_differ_from_login_password(client, admin):
    token = create_doctor(client, admin)["activation_token"]
    assert activate(client, token, signing_password=PASSWORD).status_code == 400
    # The failed attempt did not burn the token.
    assert activate(client, token).status_code == 204


@pytest.mark.parametrize("field", ["login_password", "signing_password"])
def test_weak_activation_passwords_are_rejected(client, admin, field):
    token = create_doctor(client, admin)["activation_token"]
    assert activate(client, token, **{field: "short"}).status_code == 400


def test_bad_wrong_or_mismatched_tokens_get_one_generic_error(client, admin):
    token = create_doctor(client, admin)["activation_token"]
    responses = [
        activate(client, "x" * 32),
        activate(client, token, email="someone.else@clinic.test"),
    ]
    assert all(r.status_code == 400 for r in responses)
    assert responses[0].json() == responses[1].json()


def test_token_cannot_be_reused(client, admin):
    token = create_doctor(client, admin)["activation_token"]
    assert activate(client, token).status_code == 204
    assert activate(client, token, login_password="different-password-1").status_code == 400


def test_token_expires_after_24_hours(client, admin, frozen_clock):
    token = create_doctor(client, admin)["activation_token"]
    frozen_clock.advance(timedelta(hours=24, seconds=1))
    assert activate(client, token).status_code == 400


def test_reissue_invalidates_the_old_token(client, admin):
    created = create_doctor(client, admin)
    new = client.post(
        f"/api/admin/users/{created['user']['public_id']}/reissue-token", headers=admin
    ).json()["activation_token"]
    assert new != created["activation_token"]
    assert activate(client, created["activation_token"]).status_code == 400
    assert activate(client, new).status_code == 204


def test_reissue_is_refused_for_activated_doctors_and_other_roles(client, admin):
    created = active_doctor(client, admin)
    assert (
        client.post(
            f"/api/admin/users/{created['user']['public_id']}/reissue-token", headers=admin
        ).status_code
        == 400
    )
    pid = make_user("p@example.test", Role.patient)
    assert client.post(f"/api/admin/users/{pid}/reissue-token", headers=admin).status_code == 400


def test_a_patient_account_cannot_be_activated_as_a_doctor(client, admin):
    make_user("p@example.test", Role.patient, password=None)
    token = create_doctor(client, admin)["activation_token"]
    assert activate(client, token, email="p@example.test").status_code == 400


# --- suspension --------------------------------------------------------------------------------


def test_suspending_a_doctor_revokes_keys_and_kills_sessions(client, admin):
    created = active_doctor(client, admin)
    doctor_headers = bearer(client, DOCTOR["email"])
    assert client.get("/api/auth/me", headers=doctor_headers).status_code == 200

    response = client.patch(
        f"/api/admin/users/{created['user']['public_id']}/deactivate", headers=admin
    )
    assert response.status_code == 200 and response.json()["is_active"] is False

    assert client.get("/api/auth/me", headers=doctor_headers).status_code == 401  # immediate
    assert login(client, DOCTOR["email"]).status_code == 403
    with session() as db:
        key = db.scalars(select(DoctorKey)).one()
        assert key.status == KeyStatus.REVOKED and key.revoke_reason == "DOCTOR_SUSPENDED"
        assert key.revoked_at is not None
        actions = [r.action for r in db.scalars(select(AuditLog))]
        assert "ADMIN_USER_DEACTIVATED" in actions and "KEY_REVOKED" in actions


def test_admin_cannot_deactivate_themselves_or_twice(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()["public_id"]
    assert client.patch(f"/api/admin/users/{me}/deactivate", headers=admin).status_code == 400
    pid = make_user("p@example.test", Role.patient)
    assert client.patch(f"/api/admin/users/{pid}/deactivate", headers=admin).status_code == 200
    assert client.patch(f"/api/admin/users/{pid}/deactivate", headers=admin).status_code == 409


def test_unknown_user_ids_are_404(client, admin):
    ghost = "00000000-0000-0000-0000-000000000000"
    for call in (
        client.patch(f"/api/admin/users/{ghost}/deactivate", headers=admin),
        client.post(f"/api/admin/users/{ghost}/approve", headers=admin),
        client.post(f"/api/admin/users/{ghost}/reject", headers=admin),
    ):
        assert call.status_code == 404


# --- pharmacist approval -----------------------------------------------------------------------


def register_pharmacist(client, email="ph@example.test"):
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "name": "Meera Shah",
            "password": PASSWORD,
            "role": "pharmacist",
            "license_no": "GJ-PH-1",
            "org_name": "City Pharmacy",
        },
    )
    assert response.status_code == 201
    return response.json()["public_id"]


def test_pharmacist_approval_flow(client, admin):
    pid = register_pharmacist(client)
    assert login(client, "ph@example.test").status_code == 403

    pending = client.get(
        "/api/admin/users?approval_status=PENDING&role=pharmacist", headers=admin
    ).json()
    assert pending["total"] == 1 and pending["items"][0]["public_id"] == pid

    assert (
        client.post(f"/api/admin/users/{pid}/approve", headers=admin).json()["approval_status"]
        == "APPROVED"
    )
    assert login(client, "ph@example.test").status_code == 200
    assert (
        client.post(f"/api/admin/users/{pid}/approve", headers=admin).status_code == 409
    )  # decided


def test_rejected_pharmacist_cannot_sign_in(client, admin):
    pid = register_pharmacist(client)
    assert client.post(f"/api/admin/users/{pid}/reject", headers=admin).status_code == 200
    assert login(client, "ph@example.test").status_code == 403


def test_approval_only_applies_to_pharmacists(client, admin):
    pid = make_user("p@example.test", Role.patient)
    assert client.post(f"/api/admin/users/{pid}/approve", headers=admin).status_code == 400


def test_user_list_filters_and_pagination(client, admin):
    for i in range(3):
        make_user(f"pat{i}@example.test", Role.patient)
    patients = client.get("/api/admin/users?role=patient&limit=2", headers=admin).json()
    assert patients["total"] == 3 and len(patients["items"]) == 2
    assert client.get("/api/admin/users?role=wizard", headers=admin).status_code == 422
    assert client.get("/api/admin/users?limit=0", headers=admin).status_code == 422


# --- audit trail and auditor endpoints ---------------------------------------------------------


def test_account_actions_leave_a_verifiable_audit_trail(client, admin, auditor):
    created = active_doctor(client, admin)
    pid = register_pharmacist(client)
    client.post(f"/api/admin/users/{pid}/approve", headers=admin)
    client.patch(f"/api/admin/users/{created['user']['public_id']}/deactivate", headers=admin)

    entries = client.get("/api/admin/audit?limit=200", headers=auditor).json()
    actions = [e["action"] for e in entries["items"]]
    for expected in (
        "ADMIN_USER_CREATED",
        "ACCOUNT_ACTIVATED",
        "KEY_GENERATED",
        "USER_REGISTER",
        "PHARMACIST_APPROVED",
        "ADMIN_USER_DEACTIVATED",
        "KEY_REVOKED",
        "LOGIN_SUCCESS",
    ):
        assert expected in actions

    verified = client.get("/api/admin/audit/verify", headers=auditor).json()
    assert verified["ok"] is True and verified["first_bad_seq"] is None and verified["checked"] > 5


def test_failed_logins_are_audited_without_the_email_or_password(client):
    make_user("p@example.test", Role.patient)
    login(client, "p@example.test", "wrong-password-123")
    login(client, "ghost@example.test", "wrong-password-123")
    with session() as db:
        blob = json.dumps([(r.details_json, r.resource_id) for r in db.scalars(select(AuditLog))])
    assert "wrong-password-123" not in blob and "ghost@example.test" not in blob
    assert "p@example.test" not in blob


def test_verify_detects_tampering_through_the_api(client, auditor):
    from sqlalchemy import text

    from app.db import get_engine

    make_user("p@example.test", Role.patient)
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE audit_log SET details_json = :d WHERE seq = 1"),
            {"d": '{"role":"tampered"}'},
        )
    result = client.get("/api/admin/audit/verify", headers=auditor).json()
    assert result["ok"] is False and result["first_bad_seq"] == 1


def test_checkpoint_endpoint_signs_and_anchors(client, auditor):
    make_user("p@example.test", Role.patient)
    result = client.post("/api/admin/audit/checkpoint", headers=auditor).json()
    assert result["ok"] is True and result["checkpoints"] == 1 and result["anchors"] == 1


def test_admins_cannot_read_or_verify_the_audit_log(client, admin):
    for call in (
        client.get("/api/admin/audit", headers=admin),
        client.get("/api/admin/audit/verify", headers=admin),
        client.post("/api/admin/audit/checkpoint", headers=admin),
    ):
        assert call.status_code == 403


def test_security_events_endpoint_is_readable_by_admin_and_auditor(client, admin, auditor):
    assert client.get("/api/admin/security-events", headers=admin).json() == []
    assert client.get("/api/admin/security-events", headers=auditor).json() == []


def test_approved_status_defaults_documented(client):
    make_user("p@example.test", Role.patient)
    assert get_user("p@example.test").approval_status == ApprovalStatus.APPROVED

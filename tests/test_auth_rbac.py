"""P3: registration, sign-in, lockout, sessions, CSRF, and the role x endpoint matrix."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import ApprovalStatus, AuditLog, Role
from tests.conftest import TEST_ENV
from tests.helpers import PASSWORD, bearer, get_user, login, make_user, session

ALL_ROLES = ["doctor", "patient", "pharmacist", "admin", "auditor"]

REG = {
    "email": "Ravi@Example.test",
    "name": "Ravi Patel",
    "password": PASSWORD,
    "role": "patient",
}


@pytest.fixture
def client(fresh_db):
    with TestClient(app) as c:
        yield c


def audit_actions() -> list[str]:
    with session() as db:
        return [r.action for r in db.scalars(select(AuditLog).order_by(AuditLog.seq))]


# --- registration -------------------------------------------------------------------------------


def test_patient_registration(client):
    response = client.post("/api/auth/register", json=REG)
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "patient" and body["approval_status"] == "APPROVED"
    assert body["email"] == "ravi@example.test"  # normalised
    assert len(body["patient_code"]) == 9 and body["patient_code"][4] == "-"
    assert "password" not in str(body).lower() and "hash" not in str(body).lower()
    assert audit_actions() == ["USER_REGISTER"]


def test_pharmacist_registration_is_pending_and_needs_licence(client):
    base = {**REG, "role": "pharmacist", "email": "ph@example.test"}
    assert client.post("/api/auth/register", json=base).status_code == 422
    ok = client.post(
        "/api/auth/register", json={**base, "license_no": "GJ-PH-77", "org_name": "City Pharmacy"}
    )
    assert ok.status_code == 201
    assert ok.json()["approval_status"] == "PENDING" and ok.json()["patient_code"] is None


@pytest.mark.parametrize("role", ["admin", "doctor", "auditor", "root", ""])
def test_privileged_roles_cannot_self_register(client, role):
    assert client.post("/api/auth/register", json={**REG, "role": role}).status_code == 422


@pytest.mark.parametrize(
    ("override", "status"),
    [
        ({"password": "short"}, 400),
        ({"password": "password123"}, 400),
        ({"email": "not-an-email"}, 422),
        ({"name": "A"}, 422),
        ({"name": "Evil\u202eName"}, 422),
        ({"is_active": False}, 422),  # unknown fields are refused (no mass assignment)
        ({"approval_status": "APPROVED"}, 422),
    ],
)
def test_registration_validation(client, override, status):
    assert client.post("/api/auth/register", json={**REG, **override}).status_code == status


def test_duplicate_email_is_a_conflict_case_insensitively(client):
    assert client.post("/api/auth/register", json=REG).status_code == 201
    again = client.post("/api/auth/register", json={**REG, "email": "RAVI@example.TEST"})
    assert again.status_code == 409


# --- sign-in ------------------------------------------------------------------------------------


def test_login_sets_httponly_samesite_cookies_and_returns_token(client):
    make_user("p@example.test", Role.patient)
    response = login(client, "p@example.test")
    assert response.status_code == 200
    assert response.json()["role"] == "patient" and response.json()["token_type"] == "bearer"
    cookies = {c.split("=")[0]: c.lower() for c in response.headers.get_list("set-cookie")}
    assert (
        "httponly" in cookies["pramaan_session"] and "samesite=strict" in cookies["pramaan_session"]
    )
    assert (
        "httponly" not in cookies["pramaan_csrf"] and "samesite=strict" in cookies["pramaan_csrf"]
    )
    assert client.get("/api/auth/me").json()["email"] == "p@example.test"  # cookie session works


def test_me_hides_internal_fields(client):
    make_user("p@example.test", Role.patient)
    body = client.get("/api/auth/me", headers=bearer(client, "p@example.test")).json()
    assert set(body) == {
        "public_id",
        "email",
        "name",
        "role",
        "license_no",
        "org_name",
        "patient_code",
        "approval_status",
        "is_active",
        "created_at",
    }


def test_unknown_email_and_wrong_password_are_indistinguishable(client):
    make_user("p@example.test", Role.patient)
    unknown = login(client, "ghost@example.test")
    wrong = login(client, "p@example.test", "wrong-password-123")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_failed_logins_lock_the_account_with_the_same_generic_error(client, frozen_clock):
    make_user("p@example.test", Role.patient)
    for _ in range(5):
        assert login(client, "p@example.test", "wrong-password-123").status_code == 401
    # Even the correct password is refused while locked, with the same body.
    locked = login(client, "p@example.test")
    assert locked.status_code == 401
    assert locked.json() == login(client, "ghost@example.test").json()
    assert "ACCOUNT_LOCKED" in audit_actions()

    frozen_clock.advance(timedelta(minutes=14))
    assert login(client, "p@example.test").status_code == 401
    frozen_clock.advance(timedelta(minutes=2))
    assert login(client, "p@example.test").status_code == 200


def test_success_resets_the_failure_counter(client):
    make_user("p@example.test", Role.patient)
    for _ in range(4):
        login(client, "p@example.test", "wrong-password-123")
    assert login(client, "p@example.test").status_code == 200
    for _ in range(4):
        login(client, "p@example.test", "wrong-password-123")
    assert login(client, "p@example.test").status_code == 200  # never reached 5 in a row


def test_pending_and_rejected_pharmacists_get_a_clear_403_only_with_the_right_password(client):
    make_user("pend@example.test", Role.pharmacist, approval=ApprovalStatus.PENDING)
    make_user("rej@example.test", Role.pharmacist, approval=ApprovalStatus.REJECTED)
    assert login(client, "pend@example.test").status_code == 403
    assert "approval" in login(client, "pend@example.test").json()["detail"].lower()
    assert login(client, "rej@example.test").status_code == 403
    assert login(client, "pend@example.test", "wrong-password-123").status_code == 401


def test_account_without_a_password_cannot_sign_in(client):
    make_user("doc@example.test", Role.doctor, password=None)
    assert login(client, "doc@example.test", PASSWORD).status_code == 401


def test_login_validates_input(client):
    assert client.post("/api/auth/login", json={"email": "x"}).status_code == 422
    assert (
        client.post(
            "/api/auth/login", json={"email": "a@b.test", "password": "x", "role": "admin"}
        ).status_code
        == 422
    )


# --- sessions -----------------------------------------------------------------------------------


def test_logout_invalidates_every_session(client):
    make_user("p@example.test", Role.patient)
    first = bearer(client, "p@example.test")
    second = bearer(client, "p@example.test")
    assert client.post("/api/auth/logout", headers=first).status_code == 204
    assert client.get("/api/auth/me", headers=first).status_code == 401
    assert client.get("/api/auth/me", headers=second).status_code == 401  # all sessions end


def test_token_expires_on_the_injected_clock(client, frozen_clock):
    make_user("p@example.test", Role.patient)
    headers = bearer(client, "p@example.test")
    frozen_clock.advance(timedelta(minutes=29))
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    frozen_clock.advance(timedelta(minutes=2))
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_forged_tokens_are_rejected(client):
    make_user("p@example.test", Role.patient)
    claims = {"sub": "1", "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0}
    for forged in (
        jwt.encode(claims, "not-the-real-secret-not-the-real-secret", algorithm="HS256"),
        jwt.encode(claims, None, algorithm="none"),
        "garbage",
    ):
        assert (
            client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code
            == 401
        )


def test_a_token_for_a_deleted_or_unknown_user_is_rejected(client):
    claims = {"sub": "9999", "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0}
    token = jwt.encode(claims, TEST_ENV["SECRET_KEY"], algorithm="HS256")
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


def test_role_comes_from_the_database_not_the_token(client):
    """Even a validly signed token cannot carry a role claim that grants anything."""
    make_user("p@example.test", Role.patient)
    uid = get_user("p@example.test").id
    claims = {"sub": str(uid), "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0, "role": "admin"}
    token = jwt.encode(claims, TEST_ENV["SECRET_KEY"], algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).json()["role"] == "patient"
    assert client.get("/api/admin/users", headers=headers).status_code == 403


def test_change_password_ends_old_sessions_and_old_password(client):
    make_user("p@example.test", Role.patient)
    headers = bearer(client, "p@example.test")
    bad = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": "wrong-password-123", "new_password": "brand-new-password-1"},
    )
    assert bad.status_code == 400
    weak = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 400
    ok = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "brand-new-password-1"},
    )
    assert ok.status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    assert login(client, "p@example.test", PASSWORD).status_code == 401
    assert login(client, "p@example.test", "brand-new-password-1").status_code == 200


# --- CSRF ---------------------------------------------------------------------------------------


def test_cookie_sessions_need_a_csrf_header_on_state_changing_requests(client):
    make_user("p@example.test", Role.patient)
    login(client, "p@example.test")
    body = {"current_password": "wrong-password-123", "new_password": "brand-new-password-1"}
    url = "/api/auth/change-password"

    assert client.post(url, json=body).status_code == 403  # no header
    assert client.post(url, json=body, headers={"X-CSRF-Token": "nope"}).status_code == 403
    csrf = client.cookies.get("pramaan_csrf")
    assert (
        client.post(url, json=body, headers={"X-CSRF-Token": csrf}).status_code == 400
    )  # passed CSRF


def test_csrf_token_from_another_session_is_rejected(client):
    make_user("a@example.test", Role.patient)
    make_user("b@example.test", Role.patient)
    login(client, "b@example.test")
    other = client.cookies.get("pramaan_csrf")
    client.cookies.clear()
    login(client, "a@example.test")
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "x" * 12, "new_password": "y" * 12},
        headers={"X-CSRF-Token": other},
    )
    assert response.status_code == 403


def test_safe_methods_do_not_need_csrf(client):
    make_user("p@example.test", Role.patient)
    login(client, "p@example.test")
    assert client.get("/api/auth/me").status_code == 200


def test_bearer_requests_do_not_need_csrf(client):
    make_user("p@example.test", Role.patient)
    headers = bearer(client, "p@example.test")
    client.cookies.clear()
    response = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": "wrong-password-123", "new_password": "brand-new-password-1"},
    )
    assert response.status_code == 400


def test_cookie_logout_requires_csrf_and_clears_cookies(client):
    make_user("p@example.test", Role.patient)
    login(client, "p@example.test")
    assert client.post("/api/auth/logout").status_code == 403
    response = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": client.cookies.get("pramaan_csrf")}
    )
    assert response.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


# --- role x endpoint matrix -----------------------------------------------------------------------

PUBLIC, ANY = "public", "any"
FAKE_ID = "00000000-0000-0000-0000-000000000000"

EXPECTED_ACCESS: dict[tuple[str, str], object] = {
    ("GET", "/api/health"): PUBLIC,
    ("POST", "/api/auth/register"): PUBLIC,
    ("POST", "/api/auth/login"): PUBLIC,
    ("POST", "/api/auth/activate"): PUBLIC,
    ("GET", "/api/auth/me"): ANY,
    ("POST", "/api/auth/logout"): ANY,
    ("POST", "/api/auth/change-password"): ANY,
    ("POST", "/api/admin/users"): {"admin"},
    ("GET", "/api/admin/users"): {"admin"},
    ("POST", "/api/admin/users/{user_id}/approve"): {"admin"},
    ("POST", "/api/admin/users/{user_id}/reject"): {"admin"},
    ("POST", "/api/admin/users/{user_id}/reissue-token"): {"admin"},
    ("PATCH", "/api/admin/users/{user_id}/deactivate"): {"admin"},
    ("GET", "/api/admin/audit"): {"auditor"},
    ("GET", "/api/admin/audit/verify"): {"auditor"},
    ("POST", "/api/admin/audit/checkpoint"): {"auditor"},
    ("GET", "/api/admin/security-events"): {"admin", "auditor"},
    ("POST", "/api/prescriptions"): {"doctor"},
    ("GET", "/api/prescriptions/mine"): {"doctor", "patient"},
    ("GET", "/api/prescriptions/{rx_id}/pdf"): {"doctor", "patient"},
    ("POST", "/api/prescriptions/{rx_id}/revoke"): {"doctor"},
    ("GET", "/api/patients/lookup"): {"doctor"},
    ("GET", "/api/keys/mine"): {"doctor"},
    ("POST", "/api/keys/rotate"): {"doctor"},
    ("POST", "/api/verify/qr"): {"pharmacist"},
    ("POST", "/api/prescriptions/{rx_id}/dispense"): {"pharmacist"},
    ("GET", "/api/prescriptions/{rx_id}/pin"): {"patient"},
}


def _api_routes() -> set[tuple[str, str]]:
    """Every /api operation, read from the generated OpenAPI schema (works with nested routers
    and is independent of whether the interactive docs are enabled)."""
    schema = app.openapi()
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        if path.startswith("/api")
        for method in operations
    }


def test_every_api_route_is_classified_in_the_matrix():
    """Adding an endpoint without deciding who may call it fails this test."""
    assert _api_routes() == set(EXPECTED_ACCESS)


@pytest.fixture(scope="module")
def matrix_env():
    from app import models
    from app.db import get_engine

    models.Base.metadata.drop_all(get_engine())
    models.Base.metadata.create_all(get_engine())
    with TestClient(app) as c:
        for role in ALL_ROLES:
            make_user(f"{role}@matrix.test", Role(role))
        yield c


def _headers(client: TestClient, role: str | None, path: str, cache: dict) -> dict[str, str]:
    if role is None:
        return {}
    if path.endswith(("/logout", "/change-password")):
        return bearer(client, f"{role}@matrix.test")  # these end the session: use a fresh login
    if role not in cache:
        cache[role] = bearer(client, f"{role}@matrix.test")
    return cache[role]


@pytest.mark.parametrize("role", [None, *ALL_ROLES])
@pytest.mark.parametrize(("method", "path"), sorted(EXPECTED_ACCESS))
def test_role_endpoint_matrix(matrix_env, role, method, path, _cache={}):  # noqa: B006
    matrix_env.cookies.clear()  # logins above set cookies; "anonymous" must really be anonymous
    allowed = EXPECTED_ACCESS[(method, path)]
    url = path.replace("{user_id}", FAKE_ID).replace("{rx_id}", FAKE_ID)
    headers = _headers(matrix_env, role, path, _cache)
    response = matrix_env.request(
        method, url, headers=headers, json={} if method != "GET" else None
    )
    if path.endswith(("/logout", "/change-password")):
        _cache.pop(role, None)  # these end every session of the user: drop the cached token

    if allowed == PUBLIC:
        should_pass = True
    elif role is None:
        assert response.status_code == 401, f"{method} {path} anonymous -> {response.status_code}"
        return
    elif allowed == ANY:
        should_pass = True
    else:
        should_pass = role in allowed

    if should_pass:
        # Past the auth layer: any outcome except 401/403 (400/404/422/2xx are fine here).
        assert response.status_code not in (401, 403), f"{role} blocked from {method} {path}"
    else:
        assert (
            response.status_code == 403
        ), f"{role} reached {method} {path}: {response.status_code}"

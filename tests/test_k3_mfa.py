"""Phase K3: authenticator-app sign-in (RFC 6238), recovery codes, lockout, rotation."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.core import clock, totp
from app.core.ratelimit import limiter
from app.main import app
from app.models import Role, User
from app.services import rotation
from tests.helpers import PASSWORD, bearer, make_user, session

EMAIL = "mfa.user@example.test"
START = "2026-11-02T09:00:30Z"


def utc(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


# --- the algorithm ------------------------------------------------------------------------------

RFC_SECRET = b"12345678901234567890"  # the RFC 6238 test secret (SHA-1)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ],
)
def test_matches_the_rfc_6238_test_vectors(seconds, expected):
    # The RFC lists 8-digit codes; the last six digits are the 6-digit code.
    assert totp.code_for_step(RFC_SECRET, totp.step_at(utc(seconds))) == expected


def test_a_code_is_accepted_one_step_either_side_but_not_two():
    now = utc(1111111109)
    step = totp.step_at(now)
    for offset in (-1, 0, 1):
        assert totp.verify(RFC_SECRET, totp.code_for_step(RFC_SECRET, step + offset), now, 0)
    for offset in (-2, 2):
        assert (
            totp.verify(RFC_SECRET, totp.code_for_step(RFC_SECRET, step + offset), now, 0) is None
        )


def test_a_code_cannot_be_used_twice_or_after_a_newer_one():
    now = utc(1111111109)
    step = totp.step_at(now)
    code = totp.code_for_step(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code, now, 0) == step
    assert totp.verify(RFC_SECRET, code, now, step) is None  # same code again
    older = totp.code_for_step(RFC_SECRET, step - 1)
    assert totp.verify(RFC_SECRET, older, now, step) is None  # an older code after a newer one


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 3456x", "١٢٣٤٥٦"])
def test_malformed_codes_are_refused(bad):
    assert totp.verify(RFC_SECRET, bad, utc(59), 0) is None


def test_the_provisioning_link_names_the_issuer_and_the_parameters():
    uri = totp.provisioning_uri(RFC_SECRET, "a.b+c@example.test")
    assert uri.startswith("otpauth://totp/Pramaan%3Aa.b%2Bc%40example.test?secret=")
    assert "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ" in uri  # base32 of the RFC secret
    assert "issuer=Pramaan" in uri and "digits=6" in uri and "period=30" in uri


def test_recovery_codes_are_random_well_formed_and_hash_the_same_however_typed():
    codes = totp.new_recovery_codes()
    assert len(codes) == len(set(codes)) == 8
    assert all(len(c) == 11 and c[5] == "-" for c in codes)
    key = b"k" * 32
    assert totp.recovery_hash(key, codes[0]) == totp.recovery_hash(
        key, codes[0].upper().replace("-", " ")
    )
    assert totp.recovery_hash(key, codes[0]) != totp.recovery_hash(key, codes[1])
    assert totp.recovery_hash(key, codes[0]) != totp.recovery_hash(b"j" * 32, codes[0])


# --- over the API -------------------------------------------------------------------------------


@pytest.fixture
def client(fresh_db):
    limiter.reset()
    clock.freeze(START)
    make_user(EMAIL, Role.patient)
    with TestClient(app) as c:
        yield c
    limiter.reset()


def current_code(secret_b32: str, offset: int = 0) -> str:
    secret = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    return totp.code_for_step(secret, totp.step_at(clock.now_utc()) + offset)


def next_period() -> None:
    clock.advance(timedelta(seconds=totp.PERIOD))


def sign_in(client):
    return client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})


def turn_on(client) -> tuple[str, list[str], dict]:
    headers = bearer(client, EMAIL)
    enrol = client.post("/api/auth/mfa/enrol", headers=headers, json={"password": PASSWORD})
    assert enrol.status_code == 200, enrol.text
    secret = enrol.json()["secret"]
    enabled = client.post(
        "/api/auth/mfa/enable", headers=headers, json={"code": current_code(secret)}
    )
    assert enabled.status_code == 200, enabled.text
    next_period()  # the code used to enable is spent; the next sign-in needs a fresh one
    return secret, enabled.json()["recovery_codes"], headers


def stored_user() -> User:
    with session() as db:
        user = db.scalar(select(User).where(User.email == EMAIL))
        db.expunge(user)
        return user


def audit_total(client, action: str) -> int:
    make_user(f"aud-{action.lower()}@example.test", Role.auditor)
    headers = bearer(client, f"aud-{action.lower()}@example.test")
    return client.get(f"/api/admin/audit?action={action}", headers=headers).json()["total"]


def test_set_up_needs_the_password_and_a_code_from_the_app(client):
    headers = bearer(client, EMAIL)
    wrong = client.post("/api/auth/mfa/enrol", headers=headers, json={"password": "not-it-at-all"})
    assert wrong.status_code == 400

    enrol = client.post("/api/auth/mfa/enrol", headers=headers, json={"password": PASSWORD}).json()
    assert enrol["otpauth_uri"].startswith("otpauth://totp/Pramaan")
    size = len(enrol["qr_matrix"])
    assert size >= 21 and all(len(row) == size for row in enrol["qr_matrix"])
    assert client.get("/api/auth/me", headers=headers).json()["mfa_enabled"] is False

    bad = client.post("/api/auth/mfa/enable", headers=headers, json={"code": "000000"})
    assert bad.status_code == 400
    ok = client.post(
        "/api/auth/mfa/enable", headers=headers, json={"code": current_code(enrol["secret"])}
    )
    assert ok.status_code == 200 and len(ok.json()["recovery_codes"]) == 8
    assert client.get("/api/auth/me", headers=headers).json()["mfa_enabled"] is True
    assert (
        client.post("/api/auth/mfa/enrol", headers=headers, json={"password": PASSWORD}).status_code
        == 409
    )
    assert audit_total(client, "MFA_ENABLED") == 1


def test_enable_without_starting_set_up_is_refused(client):
    headers = bearer(client, EMAIL)
    assert (
        client.post("/api/auth/mfa/enable", headers=headers, json={"code": "123456"}).status_code
        == 400
    )


def test_the_secret_and_recovery_codes_are_not_stored_in_the_clear(client):
    secret, codes, _ = turn_on(client)
    user = stored_user()
    raw = base64.b32decode(secret + "=" * (-len(secret) % 8))
    assert user.totp_secret_enc is not None and raw not in user.totp_secret_enc
    assert secret.encode() not in user.totp_secret_enc
    stored = user.recovery_codes_json or ""
    assert len(json.loads(stored)) == 8 and not any(c.replace("-", "") in stored for c in codes)


def test_signing_in_with_the_second_step(client):
    secret, _, _ = turn_on(client)
    client.cookies.clear()

    first = sign_in(client)
    assert first.status_code == 200
    body = first.json()
    assert body["mfa_required"] is True and "access_token" not in body
    assert "pramaan_session" not in first.headers.get("set-cookie", "")  # no session yet
    token = body["mfa_token"]
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )

    wrong = client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": "000000"})
    assert wrong.status_code == 401
    done = client.post(
        "/api/auth/login/mfa", json={"mfa_token": token, "code": current_code(secret)}
    )
    assert done.status_code == 200 and done.json()["role"] == "patient"
    session_headers = {"Authorization": f"Bearer {done.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=session_headers).json()["email"] == EMAIL
    assert audit_total(client, "LOGIN_SUCCESS") >= 1


def test_a_code_works_once(client):
    secret, _, _ = turn_on(client)
    code = current_code(secret)
    token = sign_in(client).json()["mfa_token"]
    assert (
        client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": code}).status_code
        == 200
    )
    again = client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": code})
    assert again.status_code == 401


def test_the_step_token_expires_and_dies_when_the_person_signs_out_everywhere(client):
    secret, _, headers = turn_on(client)
    token = sign_in(client).json()["mfa_token"]
    clock.advance(timedelta(minutes=6))
    late = client.post(
        "/api/auth/login/mfa", json={"mfa_token": token, "code": current_code(secret)}
    )
    assert late.status_code == 401

    fresh = sign_in(client).json()["mfa_token"]
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    after = client.post(
        "/api/auth/login/mfa", json={"mfa_token": fresh, "code": current_code(secret)}
    )
    assert after.status_code == 401  # signing out everywhere also cancels pending sign-ins


def test_a_recovery_code_works_once_and_is_recorded(client):
    _, codes, _ = turn_on(client)
    token = sign_in(client).json()["mfa_token"]
    typed = codes[0].upper().replace("-", " ")  # however it is typed
    ok = client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": typed})
    assert ok.status_code == 200
    assert len(json.loads(stored_user().recovery_codes_json)) == 7
    assert audit_total(client, "MFA_RECOVERY_USED") == 1

    token = sign_in(client).json()["mfa_token"]
    used = client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": codes[0]})
    assert used.status_code == 401
    other = client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": codes[1]})
    assert other.status_code == 200


def test_wrong_codes_lock_the_account_and_the_password_step_does_not_reset_the_count(client):
    secret, _, _ = turn_on(client)
    limit = get_settings().max_failed_logins
    token = sign_in(client).json()["mfa_token"]
    for _ in range(limit - 1):
        assert (
            client.post(
                "/api/auth/login/mfa", json={"mfa_token": token, "code": "000000"}
            ).status_code
            == 401
        )
    # Re-entering the right password must not give a fresh set of guesses.
    token = sign_in(client).json()["mfa_token"]
    assert stored_user().failed_logins == limit - 1
    assert (
        client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": "000001"}).status_code
        == 401
    )
    assert stored_user().locked_until is not None
    # Locked: even the right code is refused, and so is the password step.
    locked = client.post(
        "/api/auth/login/mfa", json={"mfa_token": token, "code": current_code(secret)}
    )
    assert locked.status_code == 401
    assert sign_in(client).status_code == 401


def test_turning_it_off_needs_password_and_a_code_and_restores_plain_sign_in(client):
    secret, _, headers = turn_on(client)
    code = current_code(secret)
    assert (
        client.post(
            "/api/auth/mfa/disable",
            headers=headers,
            json={"password": "wrong-password-x", "code": code},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/mfa/disable", headers=headers, json={"password": PASSWORD, "code": "000000"}
        ).status_code
        == 400
    )
    assert stored_user().totp_enabled is True
    off = client.post(
        "/api/auth/mfa/disable", headers=headers, json={"password": PASSWORD, "code": code}
    )
    assert off.status_code == 204
    user = stored_user()
    assert (
        user.totp_enabled is False
        and user.totp_secret_enc is None
        and user.recovery_codes_json is None
    )
    assert "access_token" in sign_in(client).json()
    assert audit_total(client, "MFA_DISABLED") == 1


def test_an_administrator_can_reset_a_lost_second_factor(client):
    turn_on(client)
    make_user("boss@example.test", Role.admin)
    admin = bearer(client, "boss@example.test")
    public_id = stored_user().public_id
    done = client.post(f"/api/admin/users/{public_id}/reset-mfa", headers=admin)
    assert done.status_code == 200 and done.json()["mfa_enabled"] is False
    assert stored_user().totp_enabled is False
    assert "access_token" in sign_in(client).json()
    again = client.post(f"/api/admin/users/{public_id}/reset-mfa", headers=admin)
    assert again.status_code == 409
    other = client.post(f"/api/admin/users/{public_id}/reset-mfa", headers=bearer(client, EMAIL))
    assert other.status_code == 403


def test_the_secret_survives_master_key_rotation(client, monkeypatch):
    import base64 as b64

    secret, _, _ = turn_on(client)
    settings = get_settings()
    old_kek, old_version = settings.master_key_bytes, settings.master_key_version
    new_kek = os.urandom(32)
    with session() as db:
        rotation.rotate(
            db,
            old_kek=old_kek,
            new_kek=new_kek,
            old_version=old_version,
            new_version=old_version + 1,
        )
        db.commit()
    monkeypatch.setattr(settings, "master_key", b64.b64encode(new_kek).decode())
    monkeypatch.setattr(settings, "master_key_version", old_version + 1)
    assert stored_user().totp_kek_version == old_version + 1

    token = sign_in(client).json()["mfa_token"]
    done = client.post(
        "/api/auth/login/mfa", json={"mfa_token": token, "code": current_code(secret)}
    )
    assert done.status_code == 200

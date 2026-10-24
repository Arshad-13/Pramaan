"""P9: rate limits, client IP, security headers, remaining alert rules, master-key rotation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from app.config import get_settings
from app.core import crypto
from app.core.net import client_ip
from app.core.ratelimit import RateLimiter, limiter
from app.errors import TooManyRequests
from app.main import app
from app.models import Prescription, Role, SecurityEvent
from app.services import rotation
from tests.helpers import PASSWORD, bearer, login, make_user, session
from tests.world import build_world, dispense, get_pin, issue, qr_for, sql, verify


@pytest.fixture
def w(fresh_db):
    limiter.reset()
    with TestClient(app) as client:
        yield build_world(client)
    limiter.reset()


@pytest.fixture
def limits_on(monkeypatch):
    """Turn rate limiting on for one test (the suite runs with it off)."""
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    limiter.reset()
    yield
    limiter.reset()


def events_of(kind: str) -> list[SecurityEvent]:
    with session() as db:
        return list(db.scalars(select(SecurityEvent).where(SecurityEvent.event_type == kind)))


# --- client IP ---------------------------------------------------------------------------------


def request(peer: str | None, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234) if peer else None})


def test_forwarded_header_is_ignored_unless_the_peer_is_a_trusted_proxy(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "")
    assert client_ip(request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"
    assert client_ip(request(None)) is None


def test_trusted_proxy_reveals_the_real_client_and_cannot_be_spoofed(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "10.0.0.1, 10.0.0.2")
    # the attacker prepends a fake address; only the entry added by our own proxy chain counts
    assert client_ip(request("10.0.0.1", "6.6.6.6, 198.51.100.7, 10.0.0.2")) == "198.51.100.7"
    assert client_ip(request("10.0.0.1", "198.51.100.7")) == "198.51.100.7"
    assert client_ip(request("10.0.0.1", "not-an-ip")) == "10.0.0.1"
    assert client_ip(request("10.0.0.1")) == "10.0.0.1"
    assert client_ip(request("192.0.2.5", "198.51.100.7")) == "192.0.2.5"  # peer not trusted


# --- the limiter ----------------------------------------------------------------------------------


def test_limiter_counts_per_key_and_forgets_after_the_window(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    now = [100.0]
    lim = RateLimiter(clock=lambda: now[0])
    for _ in range(3):
        lim.check("a", 3, 60)
    with pytest.raises(TooManyRequests) as err:
        lim.check("a", 3, 60)
    assert err.value.headers["Retry-After"] == "60"
    lim.check("b", 3, 60)  # another key is unaffected
    now[0] += 30
    with pytest.raises(TooManyRequests) as err:
        lim.check("a", 3, 60)
    assert err.value.headers["Retry-After"] == "30"
    now[0] += 31
    lim.check("a", 3, 60)  # the oldest attempts have aged out


def test_limiter_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", False)
    lim = RateLimiter()
    for _ in range(100):
        lim.check("a", 1, 60)


# --- limits on the endpoints ----------------------------------------------------------------------


def test_sixth_rapid_login_from_one_address_gets_429(w, limits_on):
    for _ in range(5):
        assert login(w.client, "nobody@example.test", "wrong-password-1").status_code == 401
    response = login(w.client, "someone.else@example.test", "wrong-password-1")
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert response.json()["detail"].startswith("Too many")


def test_one_account_cannot_be_hammered_from_many_addresses(w, limits_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_ips", "testclient")
    codes = [
        w.client.post(
            "/api/auth/login",
            json={"email": "ravi@example.test", "password": "wrong-password-1"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        ).status_code
        for i in range(1, 7)
    ]
    assert codes == [401] * 5 + [429]
    # a different account from yet another address is not affected
    ok = w.client.post(
        "/api/auth/login",
        json={"email": "sneha@example.test", "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert ok.status_code == 200


def test_unknown_and_known_accounts_are_limited_alike(w, limits_on):
    for _ in range(5):
        login(w.client, "ghost@example.test", "wrong-password-1")
    assert login(w.client, "ghost@example.test", "wrong-password-1").status_code == 429


def test_registration_and_activation_are_limited_per_address(w, limits_on):
    codes = [
        w.client.post(
            "/api/auth/activate",
            json={
                "email": "x@y.test",
                "token": "t" * 20,
                "login_password": "a" * 12,
                "signing_password": "b" * 12,
            },
        ).status_code
        for _ in range(11)
    ]
    assert codes[-1] == 429 and 429 not in codes[:10]


def test_verification_budget_is_per_user_and_shared_by_scan_and_upload(w, limits_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "verify_rate_per_minute", 3)
    qr = qr_for(issue(w))
    assert [verify(w, qr).status_code for _ in range(3)] == [200, 200, 200]
    assert verify(w, qr).status_code == 429
    upload = w.client.post(
        "/api/verify/upload",
        headers=w.pharmacist_a,
        files={"file": ("a.pdf", b"%PDF-", "application/pdf")},
    )
    assert upload.status_code == 429
    assert verify(w, qr, headers=w.pharmacist_b).status_code == 200  # another pharmacist is fine


# --- security headers, CORS, docs ---------------------------------------------------------------------


def test_every_response_carries_the_security_headers(w):
    for path in ("/api/health", "/api/auth/me", "/definitely-not-a-page"):
        headers = w.client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert "script-src 'self'" in headers["content-security-policy"]
        assert "object-src 'none'" in headers["content-security-policy"]
        assert "camera=(self)" in headers["permissions-policy"]


def test_api_responses_are_never_cached(w):
    assert w.client.get("/api/health").headers["cache-control"] == "no-store"
    assert (
        w.client.get("/api/prescriptions", headers=w.patient1_h).headers["cache-control"]
        == "no-store"
    )


def test_csp_forbids_inline_and_remote_scripts(w):
    csp = w.client.get("/api/health").headers["content-security-policy"]
    script = next(part for part in csp.split(";") if part.strip().startswith("script-src"))
    assert "unsafe-inline" not in script and "unsafe-eval" not in script and "http" not in script


def test_cors_allows_only_the_configured_origin(w):
    ok = w.client.options(
        "/api/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    evil = w.client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in evil.headers


def test_api_docs_are_off_unless_debug(w):
    assert w.client.get("/api/docs").status_code != 200
    assert w.client.get("/api/openapi.json").status_code != 200


def test_errors_do_not_leak_internals(w):
    body = w.client.post(
        "/api/verify/qr", headers=w.pharmacist_a, json={"qr_string": "x" * 50}
    ).json()
    assert "Traceback" not in str(body) and "sqlalchemy" not in str(body).lower()


# --- the remaining alert rules ------------------------------------------------------------------------


def test_locking_an_account_raises_a_medium_alert(w):
    for _ in range(get_settings().max_failed_logins):
        login(w.client, "ravi@example.test", "wrong-password-1")
    found = events_of("FAILED_LOGINS")
    assert len(found) == 1 and found[0].severity.value == "MEDIUM"
    assert "ravi" not in found[0].details_json  # counts only, no personal data


def test_locking_the_signing_key_raises_a_medium_alert(w):
    for _ in range(get_settings().max_failed_unlocks):
        w.client.post(
            "/api/prescriptions",
            headers=w.doctor,
            json={
                "patient_id": w.patient1,
                "medicines": [
                    {"name": "Amoxicillin", "dose_mg": 500, "frequency": "TDS", "duration_days": 5}
                ],
                "signing_password": "wrong-signing-password",
            },
        )
    found = events_of("SIGNING_LOCKED")
    assert len(found) == 1 and found[0].severity.value == "MEDIUM"


def test_three_different_pharmacists_scanning_one_prescription_raises_one_alert(w):
    make_user("pharm.c@example.test", Role.pharmacist, name="Chirag Desai")
    third = bearer(w.client, "pharm.c@example.test")
    qr = qr_for(issue(w))
    assert "MULTI_PHARMACY_SCANS" not in verify(w, qr, w.pharmacist_a).json()["risk"]["flags"]
    verify(w, qr, w.pharmacist_b)
    assert events_of("MULTI_PHARMACY_SCANS") == []
    body = verify(w, qr, third).json()
    assert body["risk"]["flags"] == ["MULTI_PHARMACY_SCANS"]
    assert body["risk"]["score"] == 15 and body["result"] == "VALID"  # a nudge, not a verdict
    assert any("Several different pharmacists" in text for text in body["risk"]["explanations"])
    verify(w, qr, third)
    found = events_of("MULTI_PHARMACY_SCANS")
    assert len(found) == 1 and found[0].severity.value == "MEDIUM"


def test_one_pharmacist_scanning_repeatedly_is_not_multi_pharmacy(w):
    qr = qr_for(issue(w))
    for _ in range(5):
        verify(w, qr, w.pharmacist_a)
    assert events_of("MULTI_PHARMACY_SCANS") == []


def test_a_broken_audit_chain_raises_one_high_alert(w):
    issue(w)
    sql("UPDATE audit_log SET details_json = :d WHERE seq = 3", d='{"x":1}')
    auditor = bearer(w.client, "auditor@example.test")
    first = w.client.get("/api/admin/audit/verify", headers=auditor).json()
    assert first["ok"] is False
    w.client.get("/api/admin/audit/verify", headers=auditor)
    found = events_of("AUDIT_CHAIN_BROKEN")
    assert len(found) == 1 and found[0].severity.value == "HIGH"


def test_a_healthy_audit_chain_raises_no_alert(w):
    issue(w)
    auditor = bearer(w.client, "auditor@example.test")
    assert w.client.get("/api/admin/audit/verify", headers=auditor).json()["ok"] is True
    assert events_of("AUDIT_CHAIN_BROKEN") == []


def test_alerts_are_visible_to_admins_newest_first(w):
    for _ in range(get_settings().max_failed_logins):
        login(w.client, "ravi@example.test", "wrong-password-1")
    listing = w.client.get("/api/admin/security-events", headers=w.admin).json()
    assert listing[0]["event_type"] == "FAILED_LOGINS"


# --- master-key rotation --------------------------------------------------------------------------------


def rotate_now(fresh: bytes, **override):
    settings = get_settings()
    args = (
        dict(
            old_kek=settings.master_key_bytes,
            new_kek=fresh,
            old_version=settings.master_key_version,
            new_version=settings.master_key_version + 1,
        )
        | override
    )
    with session() as db:
        try:
            count = rotation.rotate(db, **args)
        except rotation.RotationError:
            db.rollback()
            raise
        db.commit()
        return count


@pytest.fixture
def new_key(monkeypatch):
    """A fresh master key; `install` makes the running app use it (as editing .env would)."""
    import base64
    import os

    raw = os.urandom(32)

    def install():
        monkeypatch.setattr(get_settings(), "master_key", base64.b64encode(raw).decode())
        monkeypatch.setattr(
            get_settings(), "master_key_version", get_settings().master_key_version + 1
        )

    return raw, install


def test_rotation_keeps_everything_readable_and_dispensable(w, new_key):
    raw, install = new_key
    rx_id = issue(w)
    qr = qr_for(rx_id)
    pdf_before = w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor).content
    assert rotate_now(raw) == 1
    install()

    pdf_after = w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor).content
    assert pdf_after == pdf_before
    assert verify(w, qr).json()["result"] == "VALID"
    pin = get_pin(w, rx_id)  # the patient PIN secret was re-wrapped too
    assert dispense(w, rx_id, pin=pin).status_code == 200
    with session() as db:
        assert db.get(Prescription, rx_id).kek_version == get_settings().master_key_version


def test_rotation_is_recorded_in_the_audit_log(w, new_key):
    raw, _ = new_key
    issue(w)
    rotate_now(raw)
    auditor = bearer(w.client, "auditor@example.test")
    entries = w.client.get("/api/admin/audit?limit=10", headers=auditor).json()["items"]
    assert "KEK_ROTATED" in [e["action"] for e in entries]
    assert w.client.get("/api/admin/audit/verify", headers=auditor).json()["ok"] is True


def test_old_key_no_longer_opens_rotated_records(w, new_key):
    raw, _ = new_key
    rx_id = issue(w)
    rotate_now(raw)  # the app still holds the OLD key, as if .env was not updated
    assert w.client.get(f"/api/prescriptions/{rx_id}/pdf", headers=w.doctor).status_code == 404


def test_rotation_with_the_wrong_current_key_changes_nothing(w, new_key):
    raw, _ = new_key
    issue(w)
    with session() as db:
        before = db.scalars(select(Prescription.wrapped_dek)).all()
    with pytest.raises(rotation.RotationError):
        rotate_now(raw, old_kek=crypto.new_key())
    with session() as db:
        assert db.scalars(select(Prescription.wrapped_dek)).all() == before


def test_rotation_refuses_to_proceed_if_a_stored_pdf_is_damaged(w, new_key):
    from pathlib import Path

    raw, _ = new_key
    rx_id = issue(w)
    with session() as db:
        path = Path(db.get(Prescription, rx_id).pdf_path)
    data = bytearray(path.read_bytes())
    data[50] ^= 0xFF
    path.write_bytes(bytes(data))
    with session() as db:
        before = db.scalars(select(Prescription.wrapped_dek)).all()
    with pytest.raises(rotation.RotationError):
        rotate_now(raw)
    with session() as db:
        assert db.scalars(select(Prescription.wrapped_dek)).all() == before


@pytest.mark.parametrize("override", [{"new_version": 1}, {"new_kek": None}])
def test_rotation_rejects_pointless_requests(w, new_key, override):
    raw, _ = new_key
    issue(w)
    if override.get("new_kek", 0) is None:
        override = {"new_kek": get_settings().master_key_bytes}
    with pytest.raises(rotation.RotationError):
        rotate_now(raw, **override)

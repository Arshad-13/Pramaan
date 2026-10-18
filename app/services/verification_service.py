"""Verification pipeline and dispensing (Spec Sections 7.3, 8.3, 10).

`evaluate()` decides what a QR code means, in a fixed order:
  2. parse the code strictly                    -> INVALID_QR
  3. find the prescription                      -> NOT_FOUND
  4. decrypt the stored payload; recompute its hash; compare with the stored hash and the QR's
  5. check the doctor's ECDSA signature (and that the QR's signature and key match)
  6. cross-check the plain database columns against the SIGNED payload
        (any mismatch means someone edited the database)       -> TAMPERED
  7. doctor / key state                         -> REVOKED
  9. status and expiry (expiry comes from the signed payload)  -> REVOKED / ALREADY_USED / EXPIRED
 10. stored risk score                          -> SUSPICIOUS
 11. otherwise                                  -> VALID
Precedence when several apply: TAMPERED > REVOKED > ALREADY_USED > EXPIRED > SUSPICIOUS > VALID.
(Steps 1 and 8, reading an uploaded photo/PDF, arrive in Phase 7.)

Verification is READ-ONLY with respect to the prescription: only `dispense()` consumes a fill.
`dispense()` re-runs the checks inside the same transaction, checks the patient PIN, then performs
one atomic conditional UPDATE; UNIQUE(rx_id, fill_no) backs it up at the database level.

Data minimisation: nothing about a prescription is returned unless its signature verified; and the
patient is shown only as an initial plus surname.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, clock, crypto
from app.core import pin as pin_mod
from app.core.canonical import sha256_hex
from app.core.keys import load_public_key
from app.core.payload import iso_z
from app.core.qr import ParsedQR, QRFormatError, parse_qr
from app.errors import BadRequest, Conflict, Forbidden, Locked
from app.models import (
    Dispense,
    DoctorKey,
    KeyStatus,
    Prescription,
    RxStatus,
    Severity,
    User,
    VerificationAttempt,
)
from app.schemas import ChecksOut, VerifyOut
from app.services import events

PRECEDENCE = (
    "TAMPERED",
    "REVOKED",
    "ALREADY_USED",
    "EXPIRED",
    "SUSPICIOUS",
    "REVIEW_REQUIRED",
    "VALID",
)
PIN_ATTEMPT_LIMIT = 3
PIN_ATTEMPT_WINDOW_MINUTES = 5

_REASON_RESULT = {
    "DOCTOR_KEY_REVOKED": "REVOKED",
    "DOCTOR_SUSPENDED": "REVOKED",
    "RX_REVOKED": "REVOKED",
    "FULLY_DISPENSED": "ALREADY_USED",
    "RX_EXPIRED": "EXPIRED",
    "RISK_ABOVE_THRESHOLD": "SUSPICIOUS",
}


@dataclass
class Evaluation:
    result: str
    reasons: list[str] = field(default_factory=list)
    rx: Prescription | None = None
    parsed: ParsedQR | None = None
    payload: dict[str, Any] | None = None
    authentic: bool = False  # the signature over the stored payload verified
    checks: dict[str, Any] = field(default_factory=dict)
    doctor: User | None = None
    patient: User | None = None
    risk_score: int = 0
    risk_flags: list[str] = field(default_factory=list)


def mask_name(name: str) -> str:
    """'Ravi Patel' -> 'R. Patel' (initial + surname); a single word becomes 'R.'"""
    parts = name.split()
    if not parts:
        return ""
    if len(parts) == 1:
        return f"{parts[0][0]}."
    return f"{parts[0][0]}. {parts[-1]}"


def _kek() -> tuple[bytes, int]:
    s = get_settings()
    return s.master_key_bytes, s.master_key_version


def _parse_iso_z(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=clock.now_utc().tzinfo)
    except (ValueError, TypeError):
        return None


# --- the decision pipeline ---------------------------------------------------


def evaluate(db: Session, qr_string: str) -> Evaluation:
    try:
        parsed = parse_qr(qr_string)
    except QRFormatError:
        return Evaluation("INVALID_QR", ["MALFORMED_QR"])

    rx = db.get(Prescription, parsed.rx_id)
    if rx is None:
        return Evaluation("NOT_FOUND", ["NOT_FOUND"], parsed=parsed)

    ev = Evaluation("TAMPERED", rx=rx, parsed=parsed)
    tamper: list[str] = []

    def flag(reason: str) -> None:
        if reason not in tamper:
            tamper.append(reason)

    # 4. decrypt, re-hash, compare
    plain: bytes | None = None
    payload: dict[str, Any] | None = None
    try:
        kek, _ = _kek()
        dek = crypto.unwrap_dek(kek, rx.wrapped_dek, rx_id=rx.id, kek_version=rx.kek_version)
        plain = crypto.decrypt_payload(dek, rx.id, rx.payload_enc)
        payload = json.loads(plain)
    except (crypto.DecryptionError, ValueError):
        flag("DB_RECORD_ALTERED")
        plain = None
    hash_match = False
    if plain is not None:
        actual = sha256_hex(plain)
        if not crypto.constant_time_equal(actual, rx.payload_hash):
            flag("DB_RECORD_ALTERED")
        if not crypto.constant_time_equal(actual, parsed.payload_hash):
            flag("QR_HASH_MISMATCH")
        hash_match = "DB_RECORD_ALTERED" not in tamper and "QR_HASH_MISMATCH" not in tamper

    # 5. signature, key id
    key: DoctorKey | None = None
    signature_valid = False
    if plain is not None and payload is not None:
        key = db.get(DoctorKey, str(payload.get("key_id", "")))
        if key is None:
            flag("KEY_NOT_FOUND")
        else:
            if payload.get("key_id") != parsed.key_id:
                flag("KEY_ID_MISMATCH")
            try:
                stored_sig = crypto.b64u_decode(rx.signature_b64)
                signature_valid = crypto.verify(
                    load_public_key(key.public_key_pem), plain, stored_sig
                )
                if not crypto.constant_time_equal(parsed.signature, stored_sig):
                    signature_valid = False
            except ValueError:
                signature_valid = False
            if not signature_valid:
                flag("INVALID_SIGNATURE")

    # 6. plain columns must agree with the signed payload
    doctor = db.get(User, rx.doctor_id)
    patient = db.get(User, rx.patient_id)
    if payload is not None:
        try:
            consistent = (
                payload["rx_id"] == rx.id
                and doctor is not None
                and payload["doctor"]["id"] == doctor.public_id
                and patient is not None
                and payload["patient"]["id"] == patient.public_id
                and payload["key_id"] == rx.key_id
                and payload["issued_at"] == iso_z(rx.issued_at)
                and payload["expires_at"] == iso_z(rx.expires_at)
                and payload["max_fills"] == rx.max_fills
            )
        except (KeyError, TypeError):
            consistent = False
        if not consistent:
            flag("DB_RECORD_ALTERED")

    ev.checks = {
        "signature_valid": signature_valid,
        "hash_match": hash_match,
        "key_state": key.status.value if key else None,
        "doctor_active": None,
        "status": None,
        "fills_remaining": None,
        "not_expired": None,
        "content_check": "NOT_CHECKED",
        "file_integrity": None,
    }
    if tamper or payload is None or key is None:
        ev.reasons = tamper or ["DB_RECORD_ALTERED"]
        return ev

    # From here on the record is authentic: use the SIGNED values.
    ev.authentic = True
    ev.payload, ev.doctor, ev.patient = payload, doctor, patient
    reasons: list[str] = []

    # 7. doctor and key state
    if key.status == KeyStatus.REVOKED:
        reasons.append("DOCTOR_KEY_REVOKED")
    if doctor is None or not doctor.is_active:
        reasons.append("DOCTOR_SUSPENDED")

    # 9. status and expiry (expiry from the signed payload)
    if rx.status.value == "REVOKED":
        reasons.append("RX_REVOKED")
    if rx.status.value == "DISPENSED" or rx.fills_used >= rx.max_fills:
        reasons.append("FULLY_DISPENSED")
    expires = _parse_iso_z(payload["expires_at"])
    expired = expires is None or clock.now_utc() >= expires
    if expired:
        reasons.append("RX_EXPIRED")

    # 10. risk (issue-time score; Phase 6 fills it, later phases add verify-time signals)
    ev.risk_score = rx.risk_score
    try:
        ev.risk_flags = list(json.loads(rx.risk_flags))
    except ValueError:
        ev.risk_flags = []
    if ev.risk_score >= get_settings().risk_threshold:
        reasons.append("RISK_ABOVE_THRESHOLD")

    ev.checks.update(
        doctor_active=bool(doctor and doctor.is_active),
        status=rx.status.value,
        fills_remaining=max(0, rx.max_fills - rx.fills_used),
        not_expired=not expired,
    )
    ev.reasons = reasons
    candidates = {_REASON_RESULT[r] for r in reasons}
    ev.result = next((r for r in PRECEDENCE if r in candidates), "VALID")
    return ev


# --- verify -----------------------------------------------------------------


def _to_out(ev: Evaluation) -> VerifyOut:
    rx = ev.rx
    base: dict[str, Any] = {
        "result": ev.result,
        "reason_codes": ev.reasons,
        "rx_id": rx.id if (rx and ev.authentic) else None,
        "checks": ChecksOut(**ev.checks) if ev.checks else None,
        "can_dispense": ev.result == "VALID",
        "pin_required": bool(rx.require_pin) if (rx and ev.authentic) else False,
        "warnings": [],
    }
    if not ev.authentic or ev.payload is None or rx is None:
        return VerifyOut(**base)
    p = ev.payload
    base.update(
        risk={"score": ev.risk_score, "flags": ev.risk_flags, "explanations": []},
        doctor={"name": p["doctor"]["name"], "license_no": p["doctor"]["license_no"]},
        patient={"name": mask_name(p["patient"]["name"])},
        medicines=p["medicines"],
        issued_at=p["issued_at"],
        expires_at=p["expires_at"],
    )
    return VerifyOut(**base)


def _record_attempt(db: Session, pharmacist: User, ev: Evaluation, ip: str | None) -> None:
    rx_id = ev.parsed.rx_id if ev.parsed else None
    db.add(
        VerificationAttempt(
            pharmacist_id=pharmacist.id,
            rx_id=rx_id,
            result=ev.result,
            reason_codes=json.dumps(ev.reasons),
            ts=clock.now_utc(),
            ip=ip,
        )
    )
    db.flush()
    failed = ev.result in events.FAILURE_RESULTS
    audit.append(
        db,
        pharmacist.id,
        pharmacist.role.value,
        "RX_VERIFY_FAILED" if failed else "RX_VERIFIED",
        rx_id,
        {"result": ev.result, "reasons": ev.reasons},
    )
    if failed:
        events.check_failed_verifications(db, pharmacist.id, ip)
    if ev.result == "ALREADY_USED" and ev.rx is not None:
        dispensers = set(
            db.scalars(select(Dispense.pharmacist_id).where(Dispense.rx_id == ev.rx.id))
        )
        if dispensers and pharmacist.id not in dispensers:
            events.record_event(
                db,
                event_type="POSSIBLE_REPLAY",
                severity=Severity.MEDIUM,
                user_id=pharmacist.id,
                ip=ip,
                details={"rx_id": ev.rx.id},
            )


def verify_qr(db: Session, pharmacist: User, qr_string: str, ip: str | None = None) -> VerifyOut:
    ev = evaluate(db, qr_string)
    _record_attempt(db, pharmacist, ev, ip)
    db.commit()
    return _to_out(ev)


# --- dispense -----------------------------------------------------------------


def _recent_pin_failures(db: Session, rx_id: str) -> int:
    from app.models import AuditLog

    since = clock.now_utc() - timedelta(minutes=PIN_ATTEMPT_WINDOW_MINUTES)
    return (
        db.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "PIN_FAIL", AuditLog.resource_id == rx_id, AuditLog.ts >= since
            )
        )
        or 0
    )


def _check_pin(
    db: Session, pharmacist: User, rx: Prescription, pin: str | None, ip: str | None
) -> None:
    if _recent_pin_failures(db, rx.id) >= PIN_ATTEMPT_LIMIT:
        raise Locked("Too many wrong PIN attempts. Try again in a few minutes.")
    if not pin:
        raise BadRequest("Ask the patient for the PIN shown in their account.")
    kek, _ = _kek()
    secret = crypto.unwrap_key(
        kek,
        rx.redeem_secret_wrapped or b"",
        rx_id=rx.id,
        kek_version=rx.kek_version,
        purpose=b"redeem",
    )
    if pin_mod.verify_pin(secret, rx.id, pin, clock.now_utc(), get_settings().pin_step_seconds):
        return
    audit.append(db, pharmacist.id, pharmacist.role.value, "PIN_FAIL", rx.id, {})
    if _recent_pin_failures(db, rx.id) >= PIN_ATTEMPT_LIMIT:
        events.record_event(
            db,
            event_type="PIN_LOCKED",
            severity=Severity.MEDIUM,
            user_id=pharmacist.id,
            ip=ip,
            details={"rx_id": rx.id},
        )
    db.commit()  # keep the failure on record even though the request fails
    raise Forbidden("That PIN is not correct.")


def dispense(
    db: Session,
    pharmacist: User,
    rx_id: str,
    qr_string: str,
    patient_pin: str | None,
    identity_checked: bool,
    ip: str | None = None,
) -> dict[str, Any]:
    """Re-verify, check the patient's consent, then consume one fill atomically."""
    ev = evaluate(db, qr_string)
    if ev.parsed is not None and ev.parsed.rx_id != rx_id:
        raise BadRequest("This code belongs to a different prescription.")
    if ev.result != "VALID" or ev.rx is None:
        _record_attempt(db, pharmacist, ev, ip)
        db.commit()
        raise Conflict(f"Cannot dispense: {ev.result}.")
    rx = ev.rx

    if rx.require_pin:
        _check_pin(db, pharmacist, rx, patient_pin, ip)
    elif not identity_checked:
        raise BadRequest("Confirm that you checked the patient's identity.")

    now = clock.now_utc()
    result = db.execute(
        update(Prescription)
        .where(
            Prescription.id == rx.id,
            Prescription.status == RxStatus.ISSUED,
            Prescription.fills_used < Prescription.max_fills,
            Prescription.expires_at > now,
        )
        .values(
            fills_used=Prescription.fills_used + 1,
            status=case(
                (Prescription.fills_used + 1 >= Prescription.max_fills, "DISPENSED"),
                else_="ISSUED",
            ),
        )
    )
    if result.rowcount != 1:  # lost a race (or state changed): report the current reason
        db.rollback()
        raise Conflict("This prescription can no longer be dispensed.")
    db.refresh(rx)
    db.add(Dispense(rx_id=rx.id, fill_no=rx.fills_used, pharmacist_id=pharmacist.id, ts=now))
    audit.append(
        db,
        pharmacist.id,
        pharmacist.role.value,
        "RX_DISPENSED",
        rx.id,
        {
            "fill_no": rx.fills_used,
            "pin_checked": bool(rx.require_pin),
            "identity_checked": identity_checked,
        },
    )
    db.commit()
    return {
        "rx_id": rx.id,
        "fill_no": rx.fills_used,
        "fills_remaining": rx.max_fills - rx.fills_used,
        "status": rx.status.value,
    }

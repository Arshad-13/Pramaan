"""Prescriptions: issue, list, download, revoke, and patient lookup (Spec Sections 6, 8.2, 12).

Issuing, in order:
  1. resolve the patient and the doctor's active key (cheap checks first);
  2. build and validate the payload (rejects anything that cannot be printed faithfully);
  3. unlock the private key with the signing password (lockout rules in key_service);
  4. canonical bytes -> SHA-256 -> ECDSA signature -> QR text;
  5. envelope-encrypt the payload and the PDF under a fresh per-prescription key;
  6. store everything and write the audit entry in ONE transaction.
The plaintext payload and PDF are never written to disk or the database.

Access rules (object-level): a doctor sees only prescriptions they issued, a patient only their
own; anyone else gets 404 (not 403) so existence is not revealed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, clock, crypto
from app.core import payload as payload_mod
from app.core import pin as pin_mod
from app.core.canonical import canonical_bytes, sha256_hex
from app.core.pdf import render_prescription_pdf
from app.core.qr import build_qr, new_rx_id
from app.errors import BadRequest, Conflict, NotFound
from app.models import ApprovalStatus, Prescription, Role, RxStatus, User
from app.schemas import IssueIn, IssueOut, MedicineOut, PinOut, PrescriptionOut, RiskOut
from app.services import key_service


def _kek() -> tuple[bytes, int]:
    settings = get_settings()
    return settings.master_key_bytes, settings.master_key_version


def _pdf_path(rx_id: str) -> Path:
    return Path(get_settings().storage_dir) / f"{rx_id}.pdf.enc"


# --- issuing ------------------------------------------------------------------------------------


def _find_patient(db: Session, public_id: str) -> User:
    patient = db.scalar(
        select(User).where(
            User.public_id == public_id,
            User.role == Role.patient,
            User.is_active.is_(True),
            User.approval_status == ApprovalStatus.APPROVED,
        )
    )
    if patient is None:
        raise NotFound("Patient not found.")
    return patient


def issue_prescription(db: Session, doctor: User, data: IssueIn) -> IssueOut:
    if not doctor.license_no or not doctor.org_name:
        raise BadRequest("Your profile is missing a registration number or clinic name.")
    patient = _find_patient(db, data.patient_id)
    key = key_service.active_key(db, doctor)

    rx_id = new_rx_id()
    issued_at = clock.now_utc().replace(microsecond=0)
    expires_at = issued_at + timedelta(days=data.validity_days)
    try:
        payload = payload_mod.build_payload(
            rx_id=rx_id,
            key_id=key.key_id,
            issued_at=issued_at,
            expires_at=expires_at,
            max_fills=data.max_fills,
            doctor={
                "id": doctor.public_id,
                "name": doctor.name,
                "license_no": doctor.license_no,
                "clinic": doctor.org_name,
            },
            patient={"id": patient.public_id, "name": patient.name, "age_years": data.age_years},
            medicines=[m.model_dump() for m in data.medicines],
            notes=data.notes,
        )
        canonical = canonical_bytes(payload)
    except (payload_mod.PayloadError, ValueError) as exc:
        raise BadRequest(str(exc)) from exc

    # Only now spend the password-hashing time: input is valid.
    key, private_key = key_service.unlock_active_key(db, doctor, data.signing_password)

    payload_hash = sha256_hex(canonical)
    signature = crypto.sign(private_key, canonical)
    del private_key  # drop our reference to the unlocked key as soon as we have signed
    qr_string = build_qr(rx_id, key.key_id, payload_hash, signature)

    kek, kek_version = _kek()
    dek = crypto.new_key()
    payload_enc = crypto.encrypt_payload(dek, rx_id, canonical)
    pdf_bytes = render_prescription_pdf(payload, payload_hash, qr_string)
    pdf_enc = crypto.encrypt_pdf(dek, rx_id, pdf_bytes)
    redeem = crypto.new_key()

    row = Prescription(
        id=rx_id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        key_id=key.key_id,
        payload_enc=payload_enc,
        payload_hash=payload_hash,
        signature_b64=crypto.b64u_encode(signature),
        wrapped_dek=crypto.wrap_dek(kek, dek, rx_id=rx_id, kek_version=kek_version),
        kek_version=kek_version,
        status=RxStatus.ISSUED,
        max_fills=data.max_fills,
        fills_used=0,
        redeem_secret_wrapped=(
            crypto.wrap_key(kek, redeem, rx_id=rx_id, kek_version=kek_version, purpose=b"redeem")
            if data.require_pin
            else None
        ),
        require_pin=data.require_pin,
        risk_score=0,
        risk_flags="[]",
        risk_features_json="{}",
        override_reason=data.override_reason,
        issued_at=issued_at,
        expires_at=expires_at,
        pdf_path=str(_pdf_path(rx_id)),
        pdf_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )
    db.add(row)
    audit.append(
        db, doctor.id, doctor.role.value, "RX_ISSUED", rx_id,
        {
            "key_id": key.key_id,
            "medicines": len(data.medicines),
            "max_fills": data.max_fills,
            "validity_days": data.validity_days,
        },
    )  # fmt: skip

    path = _pdf_path(rx_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_enc)
    try:
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)  # never leave an orphan file behind a failed commit
        raise

    return IssueOut(
        rx_id=rx_id,
        issued_at=issued_at,
        expires_at=expires_at,
        max_fills=data.max_fills,
        key_id=key.key_id,
        fingerprint=payload_mod.fingerprint(payload_hash),
        risk=RiskOut(score=0, flags=[], explanations=[]),
        warnings=[],
    )


# --- reading ------------------------------------------------------------------------------------


def get_owned(db: Session, user: User, rx_id: str) -> Prescription:
    """The prescription if `user` is its doctor or its patient; otherwise 404."""
    row = db.get(Prescription, rx_id)
    owns = row is not None and (
        (user.role == Role.doctor and row.doctor_id == user.id)
        or (user.role == Role.patient and row.patient_id == user.id)
    )
    if not owns:
        raise NotFound("Prescription not found.")
    return row


def _decrypt_payload(row: Prescription) -> dict[str, Any]:
    kek, _ = _kek()
    dek = crypto.unwrap_dek(kek, row.wrapped_dek, rx_id=row.id, kek_version=row.kek_version)
    plain = crypto.decrypt_payload(dek, row.id, row.payload_enc)
    if not crypto.constant_time_equal(sha256_hex(plain), row.payload_hash):
        raise crypto.DecryptionError("payload hash mismatch")
    return json.loads(plain)


def display_status(row: Prescription) -> str:
    """Stored status, except an unused prescription past its signed expiry reads as EXPIRED."""
    if row.status == RxStatus.ISSUED and clock.now_utc() >= row.expires_at:
        return "EXPIRED"
    return row.status.value


def summarise(row: Prescription, viewer: User) -> PrescriptionOut:
    base = dict(
        id=row.id,
        status=display_status(row),
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        max_fills=row.max_fills,
        fills_used=row.fills_used,
        key_id=row.key_id,
        fingerprint=payload_mod.fingerprint(row.payload_hash),
        risk_score=row.risk_score if viewer.role == Role.doctor else None,
        require_pin=row.require_pin,
    )
    try:
        p = _decrypt_payload(row)
    except (crypto.DecryptionError, ValueError, KeyError):
        return PrescriptionOut(
            **base, doctor_name=None, patient_name=None, medicines=[], notes="", readable=False
        )
    return PrescriptionOut(
        **base,
        doctor_name=p["doctor"]["name"],
        patient_name=p["patient"]["name"],
        medicines=[MedicineOut(**m) for m in p["medicines"]],
        notes=p.get("notes", ""),
    )


def list_mine(db: Session, user: User, limit: int = 100) -> list[PrescriptionOut]:
    column = Prescription.doctor_id if user.role == Role.doctor else Prescription.patient_id
    rows = db.scalars(
        select(Prescription)
        .where(column == user.id)
        .order_by(Prescription.issued_at.desc())
        .limit(limit)
    ).all()
    return [summarise(r, user) for r in rows]


def get_summary(db: Session, user: User, rx_id: str) -> PrescriptionOut:
    return summarise(get_owned(db, user, rx_id), user)


def get_pdf(db: Session, user: User, rx_id: str) -> bytes:
    row = get_owned(db, user, rx_id)
    path = Path(row.pdf_path)
    try:
        encrypted = path.read_bytes()
        kek, _ = _kek()
        dek = crypto.unwrap_dek(kek, row.wrapped_dek, rx_id=row.id, kek_version=row.kek_version)
        pdf = crypto.decrypt_pdf(dek, row.id, encrypted)
    except (OSError, crypto.DecryptionError):
        raise NotFound("The stored document could not be read.") from None
    if hashlib.sha256(pdf).hexdigest() != row.pdf_sha256:
        raise NotFound("The stored document could not be read.")
    audit.append(db, user.id, user.role.value, "RX_PDF_DOWNLOADED", row.id, {})
    db.commit()
    return pdf


# --- revoking and lookup ------------------------------------------------------------------------


def revoke(db: Session, doctor: User, rx_id: str) -> PrescriptionOut:
    row = get_owned(db, doctor, rx_id)
    # Conditional UPDATE: it cannot race with a dispense that is consuming the same prescription.
    result = db.execute(
        update(Prescription)
        .where(Prescription.id == row.id, Prescription.status == RxStatus.ISSUED)
        .values(status=RxStatus.REVOKED)
    )
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("Only prescriptions that have not been dispensed or revoked can be revoked.")
    audit.append(db, doctor.id, doctor.role.value, "RX_REVOKED", row.id, {})
    db.commit()
    db.refresh(row)
    return summarise(row, doctor)


def lookup_patient(db: Session, *, email: str | None, code: str | None) -> User:
    """Exact match on email OR patient code. No partial search: a doctor cannot browse patients."""
    if (email is None) == (code is None):
        raise BadRequest("Provide either an email address or a patient code.")
    condition = (
        User.email == email.strip().lower()
        if email is not None
        else User.patient_code == (code or "").strip().upper()
    )
    patient = db.scalar(
        select(User).where(
            condition,
            User.role == Role.patient,
            User.is_active.is_(True),
            User.approval_status == ApprovalStatus.APPROVED,
        )
    )
    if patient is None:
        raise NotFound("No patient found with those details.")
    return patient


# --- patient dispense PIN ---------------------------------------------------------------


def get_pin(db: Session, patient: User, rx_id: str) -> PinOut:
    """The patient's current dispense PIN for one of their own, still-usable prescriptions."""
    row = get_owned(db, patient, rx_id)
    if not row.require_pin or row.redeem_secret_wrapped is None:
        raise NotFound("This prescription does not use a PIN.")
    if display_status(row) != "ISSUED":
        raise Conflict("This prescription can no longer be dispensed.")
    settings = get_settings()
    kek, _ = _kek()
    secret = crypto.unwrap_key(
        kek, row.redeem_secret_wrapped, rx_id=row.id, kek_version=row.kek_version, purpose=b"redeem"
    )
    now = clock.now_utc()
    audit.append(db, patient.id, patient.role.value, "RX_PIN_VIEWED", row.id, {})
    db.commit()
    return PinOut(
        pin=pin_mod.current_pin(secret, row.id, now, settings.pin_step_seconds),
        seconds_remaining=pin_mod.seconds_remaining(now, settings.pin_step_seconds),
        step_seconds=settings.pin_step_seconds,
    )

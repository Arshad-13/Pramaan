"""Doctor signing keys: unlocking with the signing password, lockout, listing, rotation.

Purpose: the only place that decrypts a doctor's private key. The key exists in memory only for
         the duration of one signing call; the signing password is never stored or logged.
Rules  : wrong password => generic 403 + audit entry; MAX_FAILED_UNLOCKS in a row => the key is
         locked for LOCKOUT_MINUTES (423), even for the right password, so a stolen session cannot
         be used to guess the signing password at speed (Spec Sections 7.2, 8.1).
"""

from __future__ import annotations

from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit, clock
from app.core.keys import (
    ProtectedKey,
    WrongPasswordError,
    compute_key_id,
    generate_keypair,
    protect_private_key,
    public_key_pem,
    unlock_private_key,
)
from app.core.security import (
    PasswordPolicyError,
    passwords_equal,
    validate_password,
    verify_password,
)
from app.errors import BadRequest, Forbidden, Locked
from app.models import DoctorKey, KeyStatus, Severity, User
from app.services import events


def active_key(db: Session, doctor: User) -> DoctorKey:
    key = db.scalar(
        select(DoctorKey).where(
            DoctorKey.user_id == doctor.id, DoctorKey.status == KeyStatus.ACTIVE
        )
    )
    if key is None:
        raise Forbidden("You have no active signing key. Ask an administrator.")
    return key


def unlock_active_key(
    db: Session, doctor: User, signing_password: str
) -> tuple[DoctorKey, ec.EllipticCurvePrivateKey]:
    """Decrypt the doctor's active key, enforcing the failed-attempt lockout."""
    settings = get_settings()
    now = clock.now_utc()
    key = active_key(db, doctor)

    if key.unlock_locked_until is not None and key.unlock_locked_until <= now:
        key.unlock_locked_until = None
        key.failed_unlocks = 0
    if key.unlock_locked_until is not None:
        minutes = max(1, int((key.unlock_locked_until - now).total_seconds() // 60) + 1)
        raise Locked(
            f"Signing is locked after too many wrong passwords. Try again in {minutes} minutes."
        )

    protected = ProtectedKey(
        key.kdf, key.kdf_salt, key.kdf_iterations, key.nonce, key.enc_private_key
    )
    try:
        private_key = unlock_private_key(protected, signing_password, key_id=key.key_id)
    except WrongPasswordError:
        key.failed_unlocks += 1
        audit.append(
            db,
            doctor.id,
            doctor.role.value,
            "SIGN_UNLOCK_FAIL",
            doctor.public_id,
            {"key_id": key.key_id},
        )
        if key.failed_unlocks >= settings.max_failed_unlocks:
            key.unlock_locked_until = now + timedelta(minutes=settings.lockout_minutes)
            audit.append(
                db, doctor.id, doctor.role.value, "SIGN_LOCKED", doctor.public_id,
                {"key_id": key.key_id, "minutes": settings.lockout_minutes},
            )  # fmt: skip
            events.record_event(
                db,
                event_type="SIGNING_LOCKED",
                severity=Severity.MEDIUM,
                user_id=doctor.id,
                ip=None,
                details={"key_id": key.key_id, "minutes": settings.lockout_minutes},
            )
        db.commit()  # keep the counter and audit entries even though the request fails
        raise Forbidden("Could not unlock your signing key.") from None

    key.failed_unlocks = 0
    return key, private_key


def list_keys(db: Session, doctor: User) -> list[DoctorKey]:
    return list(
        db.scalars(
            select(DoctorKey)
            .where(DoctorKey.user_id == doctor.id)
            .order_by(DoctorKey.created_at.desc())
        )
    )


def rotate_key(db: Session, doctor: User, current_password: str, new_password: str) -> DoctorKey:
    """Replace the active key. The old key becomes RETIRED (it still verifies old prescriptions)."""
    old, _private = unlock_active_key(db, doctor, current_password)
    try:
        validate_password(new_password)
    except PasswordPolicyError as exc:
        raise BadRequest(str(exc)) from exc
    if verify_password(doctor.password_hash, new_password):
        raise BadRequest("The signing password must be different from your login password.")
    if passwords_equal(current_password, new_password):
        raise BadRequest("Choose a new signing password different from the current one.")

    private_key = generate_keypair()
    protected = protect_private_key(
        private_key, new_password, iterations=get_settings().pbkdf2_iterations
    )
    new_key_id = compute_key_id(private_key.public_key())

    old.status = KeyStatus.RETIRED
    db.flush()  # free the "one ACTIVE key per doctor" slot before adding the new one
    new = DoctorKey(
        key_id=new_key_id,
        user_id=doctor.id,
        public_key_pem=public_key_pem(private_key.public_key()),
        enc_private_key=protected.ciphertext,
        kdf=protected.kdf,
        kdf_salt=protected.kdf_salt,
        kdf_iterations=protected.kdf_iterations,
        nonce=protected.nonce,
        status=KeyStatus.ACTIVE,
    )
    db.add(new)
    audit.append(
        db, doctor.id, doctor.role.value, "KEY_ROTATED", doctor.public_id,
        {"old_key_id": old.key_id, "new_key_id": new_key_id},
    )  # fmt: skip
    db.commit()
    return new

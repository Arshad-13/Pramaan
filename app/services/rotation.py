"""Master-key (KEK) rotation (Spec Sections 7.4 and 8.5).

Every prescription has its own data key (DEK) that encrypts its payload and PDF; the DEK, and the
patient-PIN secret, are wrapped by the master key. Rotating the master key therefore only
re-wraps those small values: the (large) encrypted files are never rewritten.

`rotate()` does the whole job inside the caller's transaction and PROVES the result before
returning: with the new key, every payload decrypts and hashes to its recorded value, and every
stored PDF decrypts to its recorded hash. Any failure raises, and the caller rolls back, so the
database is never left half-rotated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, crypto
from app.core.canonical import sha256_hex
from app.models import Prescription


class RotationError(Exception):
    pass


def rotate(
    db: Session,
    *,
    old_kek: bytes,
    new_kek: bytes,
    old_version: int,
    new_version: int,
) -> int:
    """Re-wrap every prescription's keys under `new_kek`. Returns how many were rotated."""
    if new_version <= old_version:
        raise RotationError("The new key version must be higher than the current one.")
    if old_kek == new_kek:
        raise RotationError("The new key is the same as the current one.")
    rows = list(db.scalars(select(Prescription).order_by(Prescription.id)))
    for row in rows:
        try:
            dek = crypto.unwrap_dek(
                old_kek, row.wrapped_dek, rx_id=row.id, kek_version=row.kek_version
            )
            new_redeem = None
            if row.redeem_secret_wrapped is not None:
                new_redeem = crypto.rewrap_key(
                    old_kek,
                    new_kek,
                    row.redeem_secret_wrapped,
                    rx_id=row.id,
                    old_version=row.kek_version,
                    new_version=new_version,
                    purpose=b"redeem",
                ).wrapped
            row.wrapped_dek = crypto.wrap_dek(new_kek, dek, rx_id=row.id, kek_version=new_version)
            row.redeem_secret_wrapped = new_redeem
            row.kek_version = new_version
        except crypto.DecryptionError as exc:
            raise RotationError(
                f"Prescription {row.id} could not be unwrapped with the current key "
                f"(version {row.kek_version}). Nothing was changed."
            ) from exc

    _prove_readable(rows, new_kek)
    audit.append(
        db,
        None,
        None,
        "KEK_ROTATED",
        None,
        {"from_version": old_version, "to_version": new_version, "prescriptions": len(rows)},
    )
    return len(rows)


def _prove_readable(rows: list[Prescription], new_kek: bytes) -> None:
    for row in rows:
        try:
            dek = crypto.unwrap_dek(
                new_kek, row.wrapped_dek, rx_id=row.id, kek_version=row.kek_version
            )
            plain = crypto.decrypt_payload(dek, row.id, row.payload_enc)
            if sha256_hex(plain) != row.payload_hash:
                raise RotationError(f"Prescription {row.id}: payload does not match its hash.")
            pdf_file = Path(row.pdf_path)
            if pdf_file.is_file():
                pdf = crypto.decrypt_pdf(dek, row.id, pdf_file.read_bytes())
                if hashlib.sha256(pdf).hexdigest() != row.pdf_sha256:
                    raise RotationError(f"Prescription {row.id}: PDF does not match its hash.")
            if row.redeem_secret_wrapped is not None:
                crypto.unwrap_key(
                    new_kek,
                    row.redeem_secret_wrapped,
                    rx_id=row.id,
                    kek_version=row.kek_version,
                    purpose=b"redeem",
                )
        except crypto.DecryptionError as exc:
            raise RotationError(f"Prescription {row.id} is not readable after rotation.") from exc

"""Signed model files (Spec Section 11.7).

Purpose: a joblib/pickle file runs code when it is loaded, so a swapped model file would be a way
         to run code on the server. The training script signs the file; loading verifies the
         signature FIRST and only then unpickles, from the same bytes that were verified.
Format : `<model>.joblib` plus `<model>.joblib.sig` holding base64url(ECDSA(SHA-256 of the file)),
         signed with the audit signing key under the domain-separation context PRAMAAN-MODEL-v1.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

import joblib
from cryptography.hazmat.primitives.asymmetric import ec

from app.core import crypto


class ModelError(Exception):
    """The model cannot be used. `kind` says why: MISSING, UNSIGNED, BAD_SIGNATURE or CORRUPT."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def sig_path(path: Path) -> Path:
    return path.with_name(path.name + ".sig")


def save_model(obj: Any, path: Path, signing_key: ec.EllipticCurvePrivateKey) -> str:
    """Write the model and its signature. Returns the file's SHA-256 (hex)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    joblib.dump(obj, buffer, compress=3)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).digest()
    signature = crypto.sign(signing_key, digest, crypto.MODEL_CONTEXT)
    path.write_bytes(data)
    sig_path(path).write_text(crypto.b64u_encode(signature), encoding="ascii")
    return digest.hex()


def load_model(path: Path, public_key: ec.EllipticCurvePublicKey) -> Any:
    """Verify, then load. Raises ModelError (never returns an unverified model)."""
    if not path.is_file():
        raise ModelError("MISSING", "No model file.")
    sig_file = sig_path(path)
    if not sig_file.is_file():
        raise ModelError("UNSIGNED", "The model file has no signature.")
    data = path.read_bytes()
    try:
        signature = crypto.b64u_decode(sig_file.read_text(encoding="ascii").strip())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ModelError("BAD_SIGNATURE", "The model signature is malformed.") from exc
    if not crypto.verify(
        public_key, hashlib.sha256(data).digest(), signature, crypto.MODEL_CONTEXT
    ):
        raise ModelError("BAD_SIGNATURE", "The model file does not match its signature.")
    try:
        return joblib.load(io.BytesIO(data))  # only after the signature verified
    except Exception as exc:  # noqa: BLE001 - any failure to unpickle means the file is unusable
        raise ModelError("CORRUPT", "The model file could not be loaded.") from exc

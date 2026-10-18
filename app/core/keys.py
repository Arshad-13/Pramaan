"""Doctor key management (Spec Section 7.2).

Purpose: generate ECDSA P-256 keypairs and protect the private key with a password.
Inputs : a signing password (never stored), PBKDF2 iteration count.
Outputs: `ProtectedKey` (what the database stores) and unlocked private keys (memory only).

Why:
- The private key is encrypted with AES-256-GCM under a key derived from the doctor's signing
  password with PBKDF2-HMAC-SHA256 (a deliberately slow KDF: it makes password guessing against
  a stolen database expensive).
- The key_id is bound into the AAD, so an encrypted key cannot be swapped between doctors.
- A wrong password fails authentication (GCM tag), it never yields a "wrong but valid" key.
- Python cannot reliably zero memory; callers must drop references to unlocked keys right
  after signing and never log them.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.crypto import NONCE_LEN, DecryptionError, aes_decrypt, aes_encrypt

KDF_PBKDF2 = "pbkdf2-sha256"
MIN_ITERATIONS = 100_000
SALT_LEN = 16
KEY_ID_LEN = 16  # hex characters


class WrongPasswordError(Exception):
    """The signing password did not unlock the key (or the stored key was altered)."""


@dataclass(frozen=True)
class ProtectedKey:
    """What the `doctor_keys` table stores for the private key."""

    kdf: str
    kdf_salt: bytes
    kdf_iterations: int
    nonce: bytes
    ciphertext: bytes  # AES-GCM ciphertext + tag of the PKCS8 PEM (nonce stored separately)


def generate_keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def public_key_pem(public_key: ec.EllipticCurvePublicKey) -> str:
    return public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


def load_public_key(pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("expected an ECDSA P-256 public key")
    return key


def compute_key_id(public_key: ec.EllipticCurvePublicKey) -> str:
    """First 16 hex chars of SHA-256 over the public key's SubjectPublicKeyInfo DER."""
    der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    digest = hashes.Hash(hashes.SHA256())
    digest.update(der)
    return digest.finalize().hex()[:KEY_ID_LEN]


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    # NFKC so the same password typed on different devices/keyboards derives the same key.
    secret = unicodedata.normalize("NFKC", password).encode("utf-8")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
    ).derive(secret)


def _aad(key_id: str) -> bytes:
    return b"pramaan-doctor-key:" + key_id.encode("ascii")


def protect_private_key(
    private_key: ec.EllipticCurvePrivateKey, password: str, *, iterations: int
) -> ProtectedKey:
    """Encrypt the private key under a key derived from `password`."""
    if iterations < MIN_ITERATIONS:
        raise ValueError(f"PBKDF2 iterations must be at least {MIN_ITERATIONS}")
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_id = compute_key_id(private_key.public_key())
    salt = os.urandom(SALT_LEN)
    blob = aes_encrypt(_derive(password, salt, iterations), pem, _aad(key_id))
    return ProtectedKey(
        kdf=KDF_PBKDF2,
        kdf_salt=salt,
        kdf_iterations=iterations,
        nonce=blob[:NONCE_LEN],
        ciphertext=blob[NONCE_LEN:],
    )


def unlock_private_key(
    protected: ProtectedKey, password: str, *, key_id: str
) -> ec.EllipticCurvePrivateKey:
    """Decrypt the private key. Raises WrongPasswordError on any failure (no detail leaked)."""
    if protected.kdf != KDF_PBKDF2:
        raise ValueError(f"unsupported KDF: {protected.kdf}")
    try:
        pem = aes_decrypt(
            _derive(password, protected.kdf_salt, protected.kdf_iterations),
            protected.nonce + protected.ciphertext,
            _aad(key_id),
        )
    except DecryptionError as exc:
        raise WrongPasswordError("could not unlock signing key") from exc
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise WrongPasswordError("could not unlock signing key")
    return key


def load_signing_key_from_file(path: str | Path) -> ec.EllipticCurvePrivateKey:
    """Load the server's audit/model signing key (a PKCS8 PEM on disk, never in the database)."""
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("expected an ECDSA P-256 private key")
    return key

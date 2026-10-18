"""Cryptographic primitives (Spec Sections 7.3-7.5).

Purpose: ECDSA P-256 signing, AES-256-GCM encryption, envelope encryption, HMAC helpers and
         base64url transport. Pure functions: no database, no settings, no I/O.
Rules  : only `cryptography` primitives; fresh random nonce for every encryption;
         constant-time comparisons; verification never raises on a bad signature.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Domain separation: a signature made for one purpose can never validate for another,
# even with the same key. Each context ends in a NUL so no context is a prefix of another.
SIGN_CONTEXT = b"PRAMAAN-RX-v2\x00"
AUDIT_CONTEXT = b"PRAMAAN-AUDIT-v1\x00"
MODEL_CONTEXT = b"PRAMAAN-MODEL-v1\x00"

SIGNATURE_LEN = 64  # raw r || s, 32 bytes each (P-256)
KEY_LEN = 32
NONCE_LEN = 12


class DecryptionError(Exception):
    """Authenticated decryption failed: wrong key, wrong context (AAD), or modified data."""


# --- base64url (no padding) ---------------------------------------------------------------

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]*$")


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    """Strict decode: alphabet only, no padding, and the encoding must be the canonical one."""
    if not _B64URL_RE.match(text) or len(text) % 4 == 1:
        raise ValueError("invalid base64url")
    try:
        data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64url") from exc
    if b64u_encode(data) != text:  # rejects non-zero trailing bits (malleable encodings)
        raise ValueError("non-canonical base64url")
    return data


# --- signatures ---------------------------------------------------------------------------


def sign(
    private_key: ec.EllipticCurvePrivateKey, payload: bytes, context: bytes = SIGN_CONTEXT
) -> bytes:
    """ECDSA-P256 over SHA-256(context || payload). Returns a fixed 64-byte r||s."""
    der = private_key.sign(context + payload, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify(
    public_key: ec.EllipticCurvePublicKey,
    payload: bytes,
    signature: bytes,
    context: bytes = SIGN_CONTEXT,
) -> bool:
    """True only for a valid signature. Any problem (bad length, wrong key type) => False."""
    if not isinstance(signature, bytes | bytearray) or len(signature) != SIGNATURE_LEN:
        return False
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    try:
        public_key.verify(encode_dss_signature(r, s), context + payload, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError, AttributeError):
        return False
    return True


# --- AES-256-GCM ---------------------------------------------------------------------------


def new_key() -> bytes:
    """A fresh random 256-bit key (used for per-prescription DEKs and redeem secrets)."""
    return os.urandom(KEY_LEN)


def aes_encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Returns nonce || ciphertext||tag. A fresh random nonce is used every call."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def aes_decrypt(key: bytes, blob: bytes, aad: bytes) -> bytes:
    """Inverse of `aes_encrypt`. Raises DecryptionError if anything was altered or mismatched."""
    if len(blob) < NONCE_LEN + 16:
        raise DecryptionError("ciphertext too short")
    try:
        return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("authentication failed") from exc


# --- envelope encryption --------------------------------------------------------------------
# Each prescription has its own random DEK that encrypts its payload and PDF. The DEK itself is
# wrapped by the master key (KEK). Rotating the KEK only re-wraps small DEKs; ciphertext files
# are never rewritten. Binding rx_id (and the KEK version) into the AAD means a blob cannot be
# swapped between prescriptions, between purposes, or replayed under another KEK version.


def _aad(purpose: bytes, rx_id: str, extra: bytes = b"") -> bytes:
    return b"pramaan:" + purpose + b":" + rx_id.encode("ascii") + (b":" + extra if extra else b"")


def encrypt_payload(dek: bytes, rx_id: str, plaintext: bytes) -> bytes:
    return aes_encrypt(dek, plaintext, _aad(b"payload", rx_id))


def decrypt_payload(dek: bytes, rx_id: str, blob: bytes) -> bytes:
    return aes_decrypt(dek, blob, _aad(b"payload", rx_id))


def encrypt_pdf(dek: bytes, rx_id: str, plaintext: bytes) -> bytes:
    return aes_encrypt(dek, plaintext, _aad(b"pdf", rx_id))


def decrypt_pdf(dek: bytes, rx_id: str, blob: bytes) -> bytes:
    return aes_decrypt(dek, blob, _aad(b"pdf", rx_id))


def wrap_key(kek: bytes, key: bytes, *, rx_id: str, kek_version: int, purpose: bytes) -> bytes:
    """Wrap a 32-byte key (a DEK or a redeem secret) under the KEK."""
    return aes_encrypt(kek, key, _aad(purpose, rx_id, str(kek_version).encode()))


def unwrap_key(
    kek: bytes, wrapped: bytes, *, rx_id: str, kek_version: int, purpose: bytes
) -> bytes:
    return aes_decrypt(kek, wrapped, _aad(purpose, rx_id, str(kek_version).encode()))


def wrap_dek(kek: bytes, dek: bytes, *, rx_id: str, kek_version: int) -> bytes:
    return wrap_key(kek, dek, rx_id=rx_id, kek_version=kek_version, purpose=b"dek")


def unwrap_dek(kek: bytes, wrapped: bytes, *, rx_id: str, kek_version: int) -> bytes:
    return unwrap_key(kek, wrapped, rx_id=rx_id, kek_version=kek_version, purpose=b"dek")


@dataclass(frozen=True)
class Rewrapped:
    wrapped: bytes
    kek_version: int


def rewrap_key(
    old_kek: bytes,
    new_kek: bytes,
    wrapped: bytes,
    *,
    rx_id: str,
    old_version: int,
    new_version: int,
    purpose: bytes,
) -> Rewrapped:
    """KEK rotation: unwrap with the old KEK, wrap with the new one."""
    key = unwrap_key(old_kek, wrapped, rx_id=rx_id, kek_version=old_version, purpose=purpose)
    return Rewrapped(
        wrap_key(new_kek, key, rx_id=rx_id, kek_version=new_version, purpose=purpose),
        new_version,
    )


# --- hashing and MACs ------------------------------------------------------------------------


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def hmac_sha256_hex(key: bytes, data: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def constant_time_equal(a: str | bytes, b: str | bytes) -> bool:
    """Compare hashes/MACs/signatures without leaking where they differ."""
    if isinstance(a, str):
        a = a.encode("utf-8")
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hmac.compare_digest(a, b)

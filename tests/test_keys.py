"""P1: doctor key generation and password protection (Spec Section 7.2)."""

from __future__ import annotations

import dataclasses
import re

import pytest

from app.core import crypto
from app.core.keys import (
    KDF_PBKDF2,
    MIN_ITERATIONS,
    WrongPasswordError,
    compute_key_id,
    generate_keypair,
    load_public_key,
    load_signing_key_from_file,
    protect_private_key,
    public_key_pem,
    unlock_private_key,
)
from tests.conftest import TEST_ENV

ITER = MIN_ITERATIONS  # keep tests fast


@pytest.fixture(scope="module")
def private_key():
    return generate_keypair()


def test_key_id_is_16_hex_and_stable(private_key):
    key_id = compute_key_id(private_key.public_key())
    assert re.fullmatch(r"[0-9a-f]{16}", key_id)
    assert key_id == compute_key_id(private_key.public_key())
    assert key_id != compute_key_id(generate_keypair().public_key())


def test_public_key_pem_round_trip(private_key):
    pem = public_key_pem(private_key.public_key())
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert compute_key_id(load_public_key(pem)) == compute_key_id(private_key.public_key())


def test_load_public_key_rejects_other_curves():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pem = (
        ec.generate_private_key(ec.SECP384R1())
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    with pytest.raises(ValueError):
        load_public_key(pem)


def test_protect_and_unlock_round_trip_signs_correctly(private_key):
    protected = protect_private_key(private_key, "correct horse battery", iterations=ITER)
    key_id = compute_key_id(private_key.public_key())
    unlocked = unlock_private_key(protected, "correct horse battery", key_id=key_id)
    sig = crypto.sign(unlocked, b"payload")
    assert crypto.verify(private_key.public_key(), b"payload", sig)


def test_stored_blob_does_not_leak_the_private_key(private_key):
    protected = protect_private_key(private_key, "pw-123456789", iterations=ITER)
    blob = protected.ciphertext + protected.nonce + protected.kdf_salt
    assert b"PRIVATE KEY" not in blob
    assert protected.kdf == KDF_PBKDF2
    assert len(protected.kdf_salt) == 16 and len(protected.nonce) == 12


def test_wrong_password_fails(private_key):
    protected = protect_private_key(private_key, "right-password", iterations=ITER)
    key_id = compute_key_id(private_key.public_key())
    for wrong in ("wrong-password", "right-passwor", "", "RIGHT-PASSWORD"):
        with pytest.raises(WrongPasswordError):
            unlock_private_key(protected, wrong, key_id=key_id)


def test_each_protection_uses_fresh_salt_and_nonce(private_key):
    a = protect_private_key(private_key, "pw-123456789", iterations=ITER)
    b = protect_private_key(private_key, "pw-123456789", iterations=ITER)
    assert a.kdf_salt != b.kdf_salt and a.nonce != b.nonce and a.ciphertext != b.ciphertext


def test_encrypted_key_cannot_be_moved_to_another_key_id(private_key):
    protected = protect_private_key(private_key, "pw-123456789", iterations=ITER)
    with pytest.raises(WrongPasswordError):
        unlock_private_key(protected, "pw-123456789", key_id="0" * 16)


def test_tampered_ciphertext_or_salt_fails(private_key):
    protected = protect_private_key(private_key, "pw-123456789", iterations=ITER)
    key_id = compute_key_id(private_key.public_key())
    flipped = bytes([protected.ciphertext[0] ^ 1]) + protected.ciphertext[1:]
    with pytest.raises(WrongPasswordError):
        unlock_private_key(
            dataclasses.replace(protected, ciphertext=flipped), "pw-123456789", key_id=key_id
        )
    with pytest.raises(WrongPasswordError):
        unlock_private_key(
            dataclasses.replace(protected, kdf_salt=b"x" * 16), "pw-123456789", key_id=key_id
        )


def test_low_iteration_count_is_refused(private_key):
    with pytest.raises(ValueError):
        protect_private_key(private_key, "pw-123456789", iterations=MIN_ITERATIONS - 1)


def test_unknown_kdf_is_refused(private_key):
    protected = protect_private_key(private_key, "pw-123456789", iterations=ITER)
    with pytest.raises(ValueError):
        unlock_private_key(
            dataclasses.replace(protected, kdf="md5"),
            "pw-123456789",
            key_id=compute_key_id(private_key.public_key()),
        )


def test_password_unicode_forms_are_equivalent(private_key):
    composed, decomposed = "p\u00e4ssw\u00f6rd-123", "pa\u0308sswo\u0308rd-123"
    protected = protect_private_key(private_key, composed, iterations=ITER)
    key_id = compute_key_id(private_key.public_key())
    assert unlock_private_key(protected, decomposed, key_id=key_id) is not None


def test_server_signing_key_loads_from_pem_file():
    key = load_signing_key_from_file(TEST_ENV["AUDIT_SIGNING_KEY_PATH"])
    sig = crypto.sign(key, b"checkpoint", context=crypto.AUDIT_CONTEXT)
    assert crypto.verify(key.public_key(), b"checkpoint", sig, context=crypto.AUDIT_CONTEXT)

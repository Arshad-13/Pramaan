"""P1: signatures, AES-GCM, envelope encryption, HMAC, base64url (Spec Section 7.5)."""

from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from hypothesis import given
from hypothesis import strategies as st

from app.core import crypto
from app.core.canonical import canonical_bytes
from app.core.keys import generate_keypair

PAYLOAD = canonical_bytes({"rx_id": "abc", "medicines": [{"name": "Amoxicillin", "dose_mg": 500}]})


@pytest.fixture(scope="module")
def keypair():
    return generate_keypair()


# --- signatures ---------------------------------------------------------------------------


def test_sign_verify_round_trip(keypair):
    sig = crypto.sign(keypair, PAYLOAD)
    assert len(sig) == crypto.SIGNATURE_LEN
    assert crypto.verify(keypair.public_key(), PAYLOAD, sig)


def test_signatures_are_randomised_but_both_verify(keypair):
    a, b = crypto.sign(keypair, PAYLOAD), crypto.sign(keypair, PAYLOAD)
    assert a != b
    assert crypto.verify(keypair.public_key(), PAYLOAD, a)
    assert crypto.verify(keypair.public_key(), PAYLOAD, b)


@pytest.mark.parametrize("byte_index", [0, 1, len(PAYLOAD) // 2, len(PAYLOAD) - 1])
def test_one_flipped_bit_in_payload_fails(keypair, byte_index):
    sig = crypto.sign(keypair, PAYLOAD)
    tampered = bytearray(PAYLOAD)
    tampered[byte_index] ^= 0x01
    assert not crypto.verify(keypair.public_key(), bytes(tampered), sig)


@pytest.mark.parametrize("byte_index", range(0, crypto.SIGNATURE_LEN, 7))
def test_one_flipped_bit_in_signature_fails(keypair, byte_index):
    sig = bytearray(crypto.sign(keypair, PAYLOAD))
    sig[byte_index] ^= 0x01
    assert not crypto.verify(keypair.public_key(), PAYLOAD, bytes(sig))


def test_wrong_public_key_fails(keypair):
    other = generate_keypair()
    sig = crypto.sign(keypair, PAYLOAD)
    assert not crypto.verify(other.public_key(), PAYLOAD, sig)


def test_wrong_context_fails(keypair):
    sig = crypto.sign(keypair, PAYLOAD)  # prescription context
    assert not crypto.verify(keypair.public_key(), PAYLOAD, sig, context=crypto.AUDIT_CONTEXT)
    sig_audit = crypto.sign(keypair, PAYLOAD, context=crypto.AUDIT_CONTEXT)
    assert crypto.verify(keypair.public_key(), PAYLOAD, sig_audit, context=crypto.AUDIT_CONTEXT)
    assert not crypto.verify(keypair.public_key(), PAYLOAD, sig_audit)


def test_contexts_are_distinct_and_none_is_a_prefix_of_another():
    contexts = [crypto.SIGN_CONTEXT, crypto.AUDIT_CONTEXT, crypto.MODEL_CONTEXT]
    assert len(set(contexts)) == 3
    for a in contexts:
        for b in contexts:
            if a != b:
                assert not b.startswith(a)


def test_verify_never_raises_on_garbage_signature(keypair):
    for bad in (b"", b"\x00" * 64, b"\xff" * 64, b"x" * 63, b"x" * 65, b"x" * 200):
        assert crypto.verify(keypair.public_key(), PAYLOAD, bad) is False


@given(st.binary(max_size=200))
def test_verify_is_false_for_any_random_bytes(sig):
    pub = _PUB
    assert crypto.verify(pub, PAYLOAD, sig) is False


def test_verify_with_non_ec_key_returns_false(keypair):
    rsa_pub = rsa.generate_private_key(65537, 2048).public_key()
    sig = crypto.sign(keypair, PAYLOAD)
    assert crypto.verify(rsa_pub, PAYLOAD, sig) is False  # type: ignore[arg-type]


def test_other_curve_key_does_not_verify(keypair):
    p384 = ec.generate_private_key(ec.SECP384R1())
    sig = crypto.sign(keypair, PAYLOAD)
    assert not crypto.verify(p384.public_key(), PAYLOAD, sig)


_PUB = generate_keypair().public_key()

# --- base64url ------------------------------------------------------------------------------


@given(st.binary(max_size=100))
def test_b64u_round_trip(data):
    text = crypto.b64u_encode(data)
    assert "=" not in text and "+" not in text and "/" not in text
    assert crypto.b64u_decode(text) == data


def test_signature_encodes_to_86_chars(keypair):
    assert len(crypto.b64u_encode(crypto.sign(keypair, PAYLOAD))) == 86


@pytest.mark.parametrize("bad", ["abc=", "ab cd", "a+b/", "ab\n", "a", "abcde", "QQ==", "Zm9v!"])
def test_b64u_decode_is_strict(bad):
    with pytest.raises(ValueError):
        crypto.b64u_decode(bad)


def test_b64u_rejects_non_canonical_trailing_bits():
    # "QR" decodes to b"A" like "QQ" does, but only "QQ" is the canonical encoding.
    assert crypto.b64u_decode("QQ") == b"A"
    with pytest.raises(ValueError):
        crypto.b64u_decode("QR")


# --- AES-GCM --------------------------------------------------------------------------------


def test_aes_round_trip_and_fresh_nonce():
    key = crypto.new_key()
    a = crypto.aes_encrypt(key, b"secret", b"aad")
    b = crypto.aes_encrypt(key, b"secret", b"aad")
    assert a != b  # random nonce each time
    assert a[: crypto.NONCE_LEN] != b[: crypto.NONCE_LEN]
    assert crypto.aes_decrypt(key, a, b"aad") == b"secret"


def test_aes_ciphertext_does_not_contain_plaintext():
    blob = crypto.aes_encrypt(crypto.new_key(), b"Amoxicillin 500mg", b"aad")
    assert b"Amoxicillin" not in blob


@pytest.mark.parametrize("position", ["nonce", "ciphertext", "tag"])
def test_aes_tamper_is_detected(position):
    key = crypto.new_key()
    blob = bytearray(crypto.aes_encrypt(key, b"hello world", b"aad"))
    index = {"nonce": 0, "ciphertext": crypto.NONCE_LEN, "tag": len(blob) - 1}[position]
    blob[index] ^= 0x01
    with pytest.raises(crypto.DecryptionError):
        crypto.aes_decrypt(key, bytes(blob), b"aad")


def test_aes_swapped_aad_fails():
    key = crypto.new_key()
    blob = crypto.aes_encrypt(key, b"hello", b"rx-1")
    with pytest.raises(crypto.DecryptionError):
        crypto.aes_decrypt(key, blob, b"rx-2")


def test_aes_wrong_key_and_short_blob_fail():
    blob = crypto.aes_encrypt(crypto.new_key(), b"hello", b"aad")
    with pytest.raises(crypto.DecryptionError):
        crypto.aes_decrypt(crypto.new_key(), blob, b"aad")
    with pytest.raises(crypto.DecryptionError):
        crypto.aes_decrypt(crypto.new_key(), b"short", b"aad")


# --- envelope encryption --------------------------------------------------------------------

RX1, RX2 = "3f0c1b2e-0000-4000-8000-000000000001", "3f0c1b2e-0000-4000-8000-000000000002"


def test_envelope_round_trip():
    kek, dek = crypto.new_key(), crypto.new_key()
    wrapped = crypto.wrap_dek(kek, dek, rx_id=RX1, kek_version=1)
    assert crypto.unwrap_dek(kek, wrapped, rx_id=RX1, kek_version=1) == dek
    blob = crypto.encrypt_payload(dek, RX1, b'{"x":1}')
    assert crypto.decrypt_payload(dek, RX1, blob) == b'{"x":1}'


def test_payload_cannot_be_swapped_between_prescriptions():
    dek = crypto.new_key()
    blob = crypto.encrypt_payload(dek, RX1, b"data")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_payload(dek, RX2, blob)


def test_payload_and_pdf_ciphertexts_are_not_interchangeable():
    dek = crypto.new_key()
    blob = crypto.encrypt_payload(dek, RX1, b"data")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_pdf(dek, RX1, blob)


def test_wrapped_dek_bound_to_rx_kek_version_and_purpose():
    kek, dek = crypto.new_key(), crypto.new_key()
    wrapped = crypto.wrap_dek(kek, dek, rx_id=RX1, kek_version=1)
    with pytest.raises(crypto.DecryptionError):
        crypto.unwrap_dek(kek, wrapped, rx_id=RX2, kek_version=1)
    with pytest.raises(crypto.DecryptionError):
        crypto.unwrap_dek(kek, wrapped, rx_id=RX1, kek_version=2)
    with pytest.raises(crypto.DecryptionError):
        crypto.unwrap_dek(crypto.new_key(), wrapped, rx_id=RX1, kek_version=1)
    with pytest.raises(crypto.DecryptionError):  # a redeem secret slot cannot be read as a DEK
        crypto.unwrap_key(kek, wrapped, rx_id=RX1, kek_version=1, purpose=b"redeem")


def test_kek_rotation_keeps_everything_decryptable_without_touching_ciphertext():
    old_kek, new_kek = crypto.new_key(), crypto.new_key()
    items = []
    for i in range(5):
        rx = f"3f0c1b2e-0000-4000-8000-00000000010{i}"
        dek = crypto.new_key()
        items.append(
            (
                rx,
                crypto.encrypt_pdf(dek, rx, f"pdf-{i}".encode()),
                crypto.wrap_dek(old_kek, dek, rx_id=rx, kek_version=1),
            )
        )
    for rx, pdf_blob, wrapped in items:
        rotated = crypto.rewrap_key(
            old_kek, new_kek, wrapped, rx_id=rx, old_version=1, new_version=2, purpose=b"dek"
        )
        assert rotated.kek_version == 2
        dek = crypto.unwrap_dek(new_kek, rotated.wrapped, rx_id=rx, kek_version=2)
        assert crypto.decrypt_pdf(dek, rx, pdf_blob).startswith(b"pdf-")  # same ciphertext
        with pytest.raises(crypto.DecryptionError):  # old KEK no longer opens the new wrapping
            crypto.unwrap_dek(old_kek, rotated.wrapped, rx_id=rx, kek_version=2)


# --- hashing / MAC --------------------------------------------------------------------------


def test_hmac_depends_on_key_and_message():
    k1, k2 = os.urandom(32), os.urandom(32)
    assert crypto.hmac_sha256(k1, b"m") == crypto.hmac_sha256(k1, b"m")
    assert crypto.hmac_sha256(k1, b"m") != crypto.hmac_sha256(k2, b"m")
    assert crypto.hmac_sha256(k1, b"m") != crypto.hmac_sha256(k1, b"n")
    assert crypto.hmac_sha256_hex(k1, b"m") == crypto.hmac_sha256(k1, b"m").hex()


def test_hmac_rfc4231_vector():
    # RFC 4231 test case 2
    mac = crypto.hmac_sha256_hex(b"Jefe", b"what do ya want for nothing?")
    assert mac == "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"


def test_constant_time_equal():
    assert crypto.constant_time_equal("abc", "abc")
    assert crypto.constant_time_equal(b"abc", "abc")
    assert not crypto.constant_time_equal("abc", "abd")
    assert not crypto.constant_time_equal("abc", "abcd")

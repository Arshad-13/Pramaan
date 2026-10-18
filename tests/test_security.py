"""P3: passwords, JWT and CSRF primitives (Spec Section 8.1)."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core import security
from app.core.security import (
    PasswordPolicyError,
    TokenError,
    create_access_token,
    csrf_token_for,
    decode_access_token,
    hash_password,
    passwords_equal,
    validate_password,
    verify_password,
)
from tests.conftest import TEST_ENV

# --- passwords ----------------------------------------------------------------------------------


def test_hash_is_argon2id_and_verifies():
    hashed = hash_password("a-long-enough-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a-long-enough-password")
    assert not verify_password(hashed, "a-long-enough-passwor")


def test_hashes_are_salted():
    assert hash_password("same-password-123") != hash_password("same-password-123")


def test_missing_hash_never_verifies_but_still_does_the_work():
    assert verify_password(None, "anything-at-all-123") is False


def test_garbage_stored_hash_is_just_false():
    assert verify_password("not-a-hash", "whatever-password") is False


def test_unicode_forms_of_a_password_are_equivalent():
    composed, decomposed = "p\u00e4ssword-12345", "pa\u0308ssword-12345"
    assert verify_password(hash_password(composed), decomposed)
    assert passwords_equal(composed, decomposed)


@pytest.mark.parametrize(
    "bad",
    ["short", "123456789", "          ", "password123", "aaaaaaaaaaaa", "x" * 129],
)
def test_weak_passwords_are_rejected(bad):
    with pytest.raises(PasswordPolicyError):
        validate_password(bad)


@pytest.mark.parametrize(
    "good", ["correct-horse-battery", "xk3-mq9-zt7-w", "p\u00e4ssw\u00f6rd-long-1"]
)
def test_reasonable_passwords_are_accepted(good):
    validate_password(good)


# --- JWT ----------------------------------------------------------------------------------------


def test_token_round_trip(frozen_clock):
    token, claims = create_access_token(42, 3)
    decoded = decode_access_token(token)
    assert (decoded.user_id, decoded.token_version, decoded.jti) == (42, 3, claims.jti)
    assert decoded.expires_at == frozen_clock.now_utc() + timedelta(minutes=30)


def test_token_has_no_role_claim(frozen_clock):
    token, _ = create_access_token(1, 0)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert set(payload) == {"sub", "iat", "exp", "jti", "tv"}


def test_expiry_uses_the_injectable_clock(frozen_clock):
    token, _ = create_access_token(1, 0)
    frozen_clock.advance(timedelta(minutes=29, seconds=59))
    decode_access_token(token)
    frozen_clock.advance(timedelta(seconds=1))
    with pytest.raises(TokenError):
        decode_access_token(token)


def test_wrong_signature_is_rejected(frozen_clock):
    payload = {"sub": "1", "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0}
    forged = jwt.encode(payload, "a-completely-different-secret-key!!", algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token(forged)


def test_alg_none_is_rejected():
    payload = {"sub": "1", "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0}
    with pytest.raises(TokenError):
        decode_access_token(jwt.encode(payload, None, algorithm="none"))


def test_other_hmac_algorithms_are_rejected():
    payload = {"sub": "1", "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0}
    with pytest.raises(TokenError):
        decode_access_token(jwt.encode(payload, TEST_ENV["SECRET_KEY"], algorithm="HS512"))


@pytest.mark.parametrize("missing", ["sub", "iat", "exp", "jti", "tv"])
def test_required_claims_are_enforced(missing):
    payload = {"sub": "1", "iat": 1, "exp": 9999999999, "jti": "x", "tv": 0}
    del payload[missing]
    with pytest.raises(TokenError):
        decode_access_token(jwt.encode(payload, TEST_ENV["SECRET_KEY"], algorithm="HS256"))


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "Bearer x"])
def test_garbage_tokens_are_rejected(junk):
    with pytest.raises(TokenError):
        decode_access_token(junk)


def test_tampered_token_is_rejected(frozen_clock):
    token, _ = create_access_token(1, 0)
    head, body, sig = token.split(".")
    flipped = body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1]
    with pytest.raises(TokenError):
        decode_access_token(f"{head}.{flipped}.{sig}")


# --- CSRF ---------------------------------------------------------------------------------------


def test_csrf_token_is_deterministic_per_session_and_differs_between_sessions():
    assert csrf_token_for("jti-1") == csrf_token_for("jti-1")
    assert csrf_token_for("jti-1") != csrf_token_for("jti-2")
    assert len(csrf_token_for("jti-1")) == 64


def test_csrf_token_cannot_be_derived_without_the_secret():
    import hashlib

    guess = hashlib.sha256(b"pramaan-csrf:jti-1").hexdigest()
    assert csrf_token_for("jti-1") != guess


def test_cookie_names_are_stable():
    assert security.SESSION_COOKIE == "pramaan_session"
    assert security.CSRF_COOKIE == "pramaan_csrf"
    assert security.CSRF_HEADER == "X-CSRF-Token"

"""Passwords, JWT sessions and CSRF tokens (Spec Section 8.1).

Purpose: everything about proving "who is calling" that is not a database query.
Inputs : passwords, user ids, settings (SECRET_KEY, token lifetime).
Outputs: argon2id hashes, signed access tokens, CSRF tokens, session cookies.

Design notes:
- argon2id (the `argon2-cffi` defaults) for passwords; passwords are NFKC-normalised so the same
  password typed on different devices hashes the same.
- Verifying against a dummy hash when an account does not exist keeps response time similar, so
  timing does not reveal which emails are registered.
- JWTs use HS256 with an explicit algorithm allow-list (never trusting the token header) and carry
  `sub`, `iat`, `exp`, `jti` and `tv` (token version). Expiry is checked against our own clock so
  tests and the demo can freeze time. Role is NOT in the token: it is always read from the
  database, so a demoted or deactivated user loses access immediately.
- The CSRF token is an HMAC of the session's `jti`: it cannot be forged or planted from another
  site or subdomain, and needs no server-side storage.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response

from app.config import get_settings
from app.core import clock
from app.core.crypto import constant_time_equal, hmac_sha256_hex

ALGORITHM = "HS256"
SESSION_COOKIE = "pramaan_session"
CSRF_COOKIE = "pramaan_csrf"
CSRF_HEADER = "X-CSRF-Token"

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128  # bounds argon2 work per request
_COMMON_PASSWORDS = frozenset(
    {
        "password123", "1234567890", "qwertyuiop", "0123456789", "password1234",
        "iloveyou123", "1q2w3e4r5t", "abcdefghij", "welcome1234", "admin12345",
    }
)  # fmt: skip

_hasher = PasswordHasher()


class PasswordPolicyError(ValueError):
    """The password does not meet the policy; the message is safe to show to the user."""


class TokenError(Exception):
    """The session token is missing, malformed, expired or otherwise unusable."""


# --- passwords --------------------------------------------------------------------------------


def _prepare(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def validate_password(password: str) -> None:
    prepared = _prepare(password)
    if len(prepared) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(prepared) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    if not prepared.strip():
        raise PasswordPolicyError("Password cannot be only spaces.")
    if prepared.lower() in _COMMON_PASSWORDS or len(set(prepared)) < 4:
        raise PasswordPolicyError("That password is too easy to guess.")


def passwords_equal(a: str, b: str) -> bool:
    return constant_time_equal(_prepare(a), _prepare(b))


def hash_password(password: str) -> str:
    return _hasher.hash(_prepare(password))


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("pramaan-dummy-password-for-timing")


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-ish time whether or not an account/hash exists."""
    target = stored_hash or _dummy_hash()
    try:
        ok = _hasher.verify(target, _prepare(password))
    except (VerificationError, InvalidHashError):
        return False
    return ok and stored_hash is not None


# --- JWT ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Claims:
    user_id: int
    token_version: int
    jti: str
    expires_at: datetime


def _secret() -> str:
    return get_settings().secret_key


def create_access_token(user_id: int, token_version: int) -> tuple[str, Claims]:
    now = clock.now_utc()
    expires_at = now + timedelta(minutes=get_settings().access_token_minutes)
    jti = uuid.uuid4().hex
    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": jti,
            "tv": token_version,
        },
        _secret(),
        algorithm=ALGORITHM,
    )
    return token, Claims(user_id, token_version, jti, expires_at)


def decode_access_token(token: str) -> Claims:
    try:
        payload = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],  # allow-list: "none" and RS/ES confusion are rejected
            options={
                "require": ["exp", "iat", "sub", "jti", "tv"],
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        claims = Claims(
            user_id=int(payload["sub"]),
            token_version=int(payload["tv"]),
            jti=str(payload["jti"]),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=clock.now_utc().tzinfo),
        )
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise TokenError("invalid token") from exc
    if clock.now_utc() >= claims.expires_at:  # our clock, not the wall clock (testable)
        raise TokenError("expired token")
    return claims


# --- CSRF + cookies -------------------------------------------------------------------------------


def csrf_token_for(jti: str) -> str:
    return hmac_sha256_hex(_secret().encode("utf-8"), b"pramaan-csrf:" + jti.encode("ascii"))


def set_session_cookies(response: Response, token: str, claims: Claims) -> None:
    settings = get_settings()
    max_age = settings.access_token_minutes * 60
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True,
        samesite="strict", secure=settings.cookie_secure, path="/",
    )  # fmt: skip
    # Readable by our own JavaScript on purpose: it echoes this value in the X-CSRF-Token header.
    response.set_cookie(
        CSRF_COOKIE, csrf_token_for(claims.jti), max_age=max_age, httponly=False,
        samesite="strict", secure=settings.cookie_secure, path="/",
    )  # fmt: skip


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")

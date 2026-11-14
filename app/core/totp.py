"""Time-based one-time passwords for the second sign-in step (RFC 6238, built on RFC 4226).

Purpose: let a person add an authenticator app (any of the usual ones) as a second factor, with
         recovery codes for a lost phone. No new dependency: the algorithm is a few lines of HMAC.
Format : SHA-1, 6 digits, 30-second steps. That is what authenticator apps expect; SHA-1 is used
         here only as the HMAC hash, where it is not weakened by the collision attacks on plain
         SHA-1. A code is accepted one step before or after the current one (clock drift).
Replay : the caller stores the last accepted step; a code from that step or an earlier one is
         refused, so one code cannot be used twice even inside its 90-second window.
Codes  : recovery codes are random, shown once, and stored only as keyed hashes (the key lives
         outside the database), so a stolen database cannot be used to read or guess them.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote

from app.core.crypto import hmac_sha256_hex

PERIOD = 30
DIGITS = 6
WINDOW = 1  # steps accepted either side of now
SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommendation
RECOVERY_CODES = 8
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (i, l, o, 0, 1)
ISSUER = "Pramaan"


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def to_base32(secret: bytes) -> str:
    """The form authenticator apps take for typing in by hand (no padding)."""
    return base64.b32encode(secret).decode("ascii").rstrip("=")


def _hotp(secret: bytes, counter: int) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), digestmod="sha1").digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**DIGITS)).zfill(DIGITS)


def step_at(now: datetime) -> int:
    return int(now.timestamp()) // PERIOD


def code_for_step(secret: bytes, step: int) -> str:
    return _hotp(secret, step)


def verify(secret: bytes, code: str, now: datetime, last_step: int) -> int | None:
    """The step the code belongs to if it is valid and newer than `last_step`, else None."""
    code = code.replace(" ", "")
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    current = step_at(now)
    matched: int | None = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        # Every candidate is compared every time, so timing does not show which one matched.
        if hmac.compare_digest(_hotp(secret, step), code) and step > last_step:
            matched = step
    return matched


def provisioning_uri(secret: bytes, account: str) -> str:
    """The otpauth:// link that authenticator apps read from a QR code."""
    label = quote(f"{ISSUER}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={to_base32(secret)}&issuer={quote(ISSUER)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )


# --- recovery codes -----------------------------------------------------------------------------


def new_recovery_codes(count: int = RECOVERY_CODES) -> list[str]:
    """Codes like `k3m9x-q2w7p` (50 bits each)."""
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalise_recovery(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isascii() and ch.isalnum())


def looks_like_totp(code: str) -> bool:
    stripped = code.replace(" ", "")
    return len(stripped) == DIGITS and stripped.isascii() and stripped.isdigit()


def recovery_hash(key: bytes, code: str) -> str:
    return hmac_sha256_hex(key, b"pramaan:recovery:" + normalise_recovery(code).encode("ascii"))

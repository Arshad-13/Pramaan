"""Patient dispense PIN (Spec Section 8.3).

Purpose: a short-lived 6-digit code only the patient's app can show, required to dispense.
         A stolen or photographed prescription is useless without it.
Method : TOTP-style. PIN = truncate(HMAC-SHA256(redeem_secret, rx_id || ":" || counter)) where
         counter = floor(unix_time / step). The dynamic truncation is RFC 4226 section 5.3
         (verified against the RFC 6238 SHA-256 test vector in the tests).
Accept : the current time step and the previous one (clock skew / typing time), never the next.
Secret : a per-prescription random `redeem_secret` (stored wrapped by the KEK), so PINs for
         different prescriptions are unrelated.
"""

from __future__ import annotations

import hmac
import struct
from datetime import datetime

from app.core.crypto import hmac_sha256

PIN_DIGITS = 6


def _dynamic_truncate(mac: bytes, digits: int) -> str:
    """RFC 4226 section 5.3 dynamic truncation to a zero-padded decimal string."""
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def time_counter(now: datetime, step_seconds: int) -> int:
    return int(now.timestamp()) // step_seconds


def _pin_for_counter(secret: bytes, rx_id: str, counter: int) -> str:
    message = rx_id.encode("ascii") + b":" + struct.pack(">Q", counter)
    return _dynamic_truncate(hmac_sha256(secret, message), PIN_DIGITS)


def current_pin(secret: bytes, rx_id: str, now: datetime, step_seconds: int) -> str:
    return _pin_for_counter(secret, rx_id, time_counter(now, step_seconds))


def seconds_remaining(now: datetime, step_seconds: int) -> int:
    """Seconds until the displayed PIN changes (drives the countdown ring)."""
    return step_seconds - (int(now.timestamp()) % step_seconds)


def verify_pin(secret: bytes, rx_id: str, pin: str, now: datetime, step_seconds: int) -> bool:
    """Constant-time check against the current and previous time step."""
    if len(pin) != PIN_DIGITS or not pin.isascii() or not pin.isdigit():
        return False
    counter = time_counter(now, step_seconds)
    matched = False
    for candidate in (counter, counter - 1):
        # Evaluate both candidates every time so timing does not reveal which one matched.
        if hmac.compare_digest(_pin_for_counter(secret, rx_id, candidate), pin):
            matched = True
    return matched

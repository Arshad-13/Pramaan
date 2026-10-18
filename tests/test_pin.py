"""P1: patient dispense PIN (TOTP-style, Spec Section 8.3)."""

from __future__ import annotations

import hashlib
import hmac
import struct
from datetime import UTC, datetime, timedelta

import pytest

from app.core import pin

STEP = 120
RX = "3f0c1b2e-0000-4000-8000-000000000001"
T0 = datetime(2026, 10, 18, 10, 30, 0, tzinfo=UTC)
SECRET = b"\x01" * 32


def test_dynamic_truncation_matches_rfc6238_sha256_vector():
    # RFC 6238 appendix B: SHA-256, secret "12345678901234567890123456789012",
    # T = 59 s with a 30 s step (counter 1) => 8-digit TOTP 46119246.
    key = b"12345678901234567890123456789012"
    mac = hmac.new(key, struct.pack(">Q", 1), hashlib.sha256).digest()
    assert pin._dynamic_truncate(mac, 8) == "46119246"


def test_pin_is_six_digits_and_deterministic():
    value = pin.current_pin(SECRET, RX, T0, STEP)
    assert len(value) == 6 and value.isdigit()
    assert value == pin.current_pin(SECRET, RX, T0, STEP)


def test_pin_is_stable_within_a_step_and_changes_across_steps():
    start = T0.replace(second=0, minute=(T0.minute // 2) * 2)  # aligned to a 120 s boundary
    inside = pin.current_pin(SECRET, RX, start + timedelta(seconds=STEP - 1), STEP)
    assert inside == pin.current_pin(SECRET, RX, start, STEP)
    # Across many steps at least some PINs differ (a single collision is 1-in-a-million).
    values = {
        pin.current_pin(SECRET, RX, start + timedelta(seconds=STEP * i), STEP) for i in range(20)
    }
    assert len(values) > 15


def test_pin_depends_on_secret_and_rx_id():
    # Fixed inputs, so the outcome is deterministic (not a probabilistic assertion).
    base = pin.current_pin(SECRET, RX, T0, STEP)
    assert pin.current_pin(b"\x02" * 32, RX, T0, STEP) != base
    assert pin.current_pin(SECRET, RX.replace("0001", "0002"), T0, STEP) != base


def test_verify_accepts_current_and_previous_step_only():
    now = T0
    current = pin.current_pin(SECRET, RX, now, STEP)
    previous = pin.current_pin(SECRET, RX, now - timedelta(seconds=STEP), STEP)
    two_ago = pin.current_pin(SECRET, RX, now - timedelta(seconds=2 * STEP), STEP)
    future = pin.current_pin(SECRET, RX, now + timedelta(seconds=STEP), STEP)

    assert pin.verify_pin(SECRET, RX, current, now, STEP)
    assert pin.verify_pin(SECRET, RX, previous, now, STEP)
    for stale in {two_ago, future} - {current, previous}:
        assert not pin.verify_pin(SECRET, RX, stale, now, STEP)


def test_verify_rejects_wrong_secret_rx_and_malformed_input():
    good = pin.current_pin(SECRET, RX, T0, STEP)
    other_rx = "3f0c1b2e-0000-4000-8000-0000000000ff"
    assert not pin.verify_pin(b"\x02" * 32, RX, good, T0, STEP)
    assert not pin.verify_pin(SECRET, other_rx, good, T0, STEP)
    for bad in (
        "",
        "12345",
        "1234567",
        "12345a",
        "\u0661\u0662\u0663\u0664\u0665\u0666",
        " 12345",
        good + " ",
    ):
        assert not pin.verify_pin(SECRET, RX, bad, T0, STEP)


def test_seconds_remaining_counts_down_to_the_next_step():
    boundary = datetime.fromtimestamp((int(T0.timestamp()) // STEP) * STEP, tz=UTC)
    assert pin.seconds_remaining(boundary, STEP) == STEP
    assert pin.seconds_remaining(boundary + timedelta(seconds=119), STEP) == 1


@pytest.mark.parametrize("offset", [0, 1, 59, 119])
def test_pin_shown_is_always_accepted_at_that_moment(offset):
    now = T0 + timedelta(seconds=offset)
    assert pin.verify_pin(SECRET, RX, pin.current_pin(SECRET, RX, now, STEP), now, STEP)

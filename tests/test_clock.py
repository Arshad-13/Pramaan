"""P0: the injectable clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core import clock


def test_real_clock_is_aware_utc():
    now = clock.now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_freeze_and_advance(frozen_clock):
    assert clock.now_utc() == datetime(2026, 10, 18, 10, 30, tzinfo=UTC)
    clock.advance(timedelta(days=31))
    assert clock.now_utc() == datetime(2026, 11, 18, 10, 30, tzinfo=UTC)


def test_freeze_accepts_datetime_and_releases():
    clock.freeze(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    assert clock.now_utc().year == 2026
    clock.freeze(None)
    assert clock.now_utc().year >= 2026

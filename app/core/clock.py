"""Single source of time for the whole app.

Purpose: every module asks `now_utc()` for the time; nobody calls `datetime.now()` directly.
Inputs : optional FROZEN_TIME setting (demo) or `freeze()` (tests).
Outputs: timezone-aware UTC datetimes.

Why: expiry, lockout and PIN windows must be testable without `sleep`, and the live demo can
pin the clock so the "expired" and "valid" samples behave the same every rehearsal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_override: datetime | None = None


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def freeze(moment: datetime | str | None) -> None:
    """Pin the clock (tests/demo). Pass None to release it."""
    global _override
    if moment is None:
        _override = None
    elif isinstance(moment, str):
        _override = _parse_iso(moment)
    else:
        _override = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


def advance(delta: timedelta) -> None:
    """Move a frozen clock forward. Only valid while frozen."""
    global _override
    if _override is None:
        raise RuntimeError("advance() requires a frozen clock")
    _override = _override + delta


def now_utc() -> datetime:
    """Current time as an aware UTC datetime."""
    if _override is not None:
        return _override
    # Imported lazily so the clock stays usable even if settings are not loaded yet.
    from app.config import get_settings

    frozen = get_settings().frozen_time.strip()
    if frozen:
        return _parse_iso(frozen)
    return datetime.now(UTC)

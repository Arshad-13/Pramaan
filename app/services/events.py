"""Security events and alert rules (Spec Section 8.4).

Purpose: turn suspicious patterns into a `security_events` row plus a tamper-evident audit entry,
         so administrators and auditors can see them.
Rules implemented so far (the rest arrive with hardening):
  - POSSIBLE_REPLAY  (MEDIUM): a different pharmacist verifies a prescription that was already
    dispensed by someone else.
  - FAILED_VERIFICATIONS (HIGH): 5 or more failed verifications (tampered / not found / invalid
    code) by one pharmacist within 10 minutes.
Details hold only IDs and counts, never personal data.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.models import SecurityEvent, Severity, VerificationAttempt

FAILED_VERIFICATION_THRESHOLD = 5
FAILED_VERIFICATION_WINDOW_MINUTES = 10
FAILURE_RESULTS = ("TAMPERED", "NOT_FOUND", "INVALID_QR")


def record_event(
    db: Session,
    *,
    event_type: str,
    severity: Severity,
    user_id: int | None,
    ip: str | None,
    details: dict[str, Any] | None = None,
) -> SecurityEvent:
    """Store the event and mirror it into the audit log (same transaction; caller commits)."""
    details = details or {}
    event = SecurityEvent(
        user_id=user_id,
        ip=ip,
        event_type=event_type,
        severity=severity,
        details_json=json.dumps(details, sort_keys=True, separators=(",", ":")),
    )
    db.add(event)
    audit.append(
        db,
        user_id,
        None,
        "SECURITY_ALERT",
        None,
        {"event_type": event_type, "severity": severity.value, **details},
    )
    return event


def _recent_event_exists(db: Session, event_type: str, user_id: int, minutes: int) -> bool:
    since = clock.now_utc() - timedelta(minutes=minutes)
    return (
        db.scalar(
            select(func.count())
            .select_from(SecurityEvent)
            .where(
                SecurityEvent.event_type == event_type,
                SecurityEvent.user_id == user_id,
                SecurityEvent.ts >= since,
            )
        )
        or 0
    ) > 0


def check_failed_verifications(db: Session, pharmacist_id: int, ip: str | None) -> None:
    """Raise one HIGH alert when a pharmacist racks up repeated failed verifications."""
    since = clock.now_utc() - timedelta(minutes=FAILED_VERIFICATION_WINDOW_MINUTES)
    failures = (
        db.scalar(
            select(func.count())
            .select_from(VerificationAttempt)
            .where(
                VerificationAttempt.pharmacist_id == pharmacist_id,
                VerificationAttempt.result.in_(FAILURE_RESULTS),
                VerificationAttempt.ts >= since,
            )
        )
        or 0
    )
    if failures >= FAILED_VERIFICATION_THRESHOLD and not _recent_event_exists(
        db, "FAILED_VERIFICATIONS", pharmacist_id, FAILED_VERIFICATION_WINDOW_MINUTES
    ):
        record_event(
            db,
            event_type="FAILED_VERIFICATIONS",
            severity=Severity.HIGH,
            user_id=pharmacist_id,
            ip=ip,
            details={"failures": failures, "window_minutes": FAILED_VERIFICATION_WINDOW_MINUTES},
        )

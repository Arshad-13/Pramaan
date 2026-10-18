"""Tamper-evident audit log (Spec Section 9).

Purpose: record every security-relevant action so that editing, re-computing, reordering or
         deleting entries can be detected afterwards.
Inputs : the caller's SQLAlchemy session (we never commit: the audit row and the business change
         commit or roll back together), the action, and small `details` made of IDs and codes.
Outputs: chained `AuditLog` rows, signed `AuditCheckpoint` rows, an append-only anchor file, and
         `verify_chain()` results.

How tampering is caught:
- Each row's hash is HMAC-SHA256 keyed with AUDIT_KEY over (previous hash || canonical entry).
  Someone with only database access cannot recompute a valid chain; plain SHA-256 will not do.
- Every N entries a checkpoint (seq + head hash) is signed with the server's ECDSA audit key and
  also appended to an anchor file outside the database. If the tail is deleted, or the chain is
  rewritten by someone who somehow has the HMAC key, the checkpoints no longer match.
- Honest limits: a chain alone cannot see deletion of the *newest* rows until a later checkpoint or
  anchor records them; and an attacker who can change the DB, the anchor file, the HMAC key and the
  signing key (a full server compromise) defeats all of it. The anchor file should live on
  write-once storage in a real deployment.

Never put passwords, keys, tokens, PINs, names or other personal data in `details`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.canonical import CanonicalError, canonical_bytes
from app.core.crypto import (
    AUDIT_CONTEXT,
    b64u_decode,
    b64u_encode,
    constant_time_equal,
    hmac_sha256_hex,
    sign,
    verify,
)
from app.core.keys import load_signing_key_from_file
from app.models import AuditCheckpoint, AuditLog

logger = logging.getLogger("pramaan.audit")

GENESIS_HASH = "0" * 64
MAX_DETAILS_BYTES = 2048

AUDIT_ACTIONS = frozenset(
    {
        "USER_REGISTER", "ACCOUNT_ACTIVATED", "PHARMACIST_APPROVED", "PHARMACIST_REJECTED",
        "LOGIN_SUCCESS", "LOGIN_FAIL", "LOGOUT", "ACCOUNT_LOCKED",
        "KEY_GENERATED", "KEY_ROTATED", "KEY_REVOKED", "SIGN_UNLOCK_FAIL", "SIGN_LOCKED",
        "RX_ISSUED", "RX_ISSUED_WITH_OVERRIDE", "RX_REVOKED", "RX_PDF_DOWNLOADED",
        "RX_PIN_VIEWED", "RX_VERIFIED", "RX_VERIFY_FAILED", "RX_DISPENSED", "PIN_FAIL",
        "SECURITY_ALERT", "ADMIN_USER_CREATED", "ADMIN_USER_DEACTIVATED",
        "AUDIT_VERIFIED", "AUDIT_CHECKPOINT", "KEK_ROTATED",
    }
)  # fmt: skip

# Details keys that must never be logged (secrets) or that are personal data (names, contact).
_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "pin", "jwt", "token", "master_key", "audit_key", "secret_key", "signing_key",
        "name", "email", "phone", "address", "dob", "patient_name", "doctor_name",
    }
)  # fmt: skip
_FORBIDDEN_DETAIL_SUBSTRINGS = ("password", "secret", "private")


class AuditError(ValueError):
    """The audit entry is invalid (unknown action, forbidden detail, too large)."""


@dataclass(frozen=True)
class AuditKeys:
    """Everything needed to write and verify the log. Built from settings in production."""

    hmac_key: bytes
    signing_key: ec.EllipticCurvePrivateKey
    anchor_path: Path
    checkpoint_every: int = 50


@lru_cache
def default_keys() -> AuditKeys:
    import base64

    from app.config import get_settings

    s = get_settings()
    return AuditKeys(
        hmac_key=base64.b64decode(s.audit_key),
        signing_key=load_signing_key_from_file(s.audit_signing_key_path),
        anchor_path=Path(s.anchor_file),
        checkpoint_every=s.audit_checkpoint_every,
    )


# --- entry hashing --------------------------------------------------------------------------


def _fmt_ts(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _entry_body(
    seq: int,
    ts: datetime,
    actor_id: int | None,
    actor_role: str | None,
    action: str,
    resource_id: str | None,
    details: dict[str, Any],
) -> bytes:
    return canonical_bytes(
        {
            "seq": seq,
            "ts": _fmt_ts(ts),
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "resource_id": resource_id,
            "details": details,
        }
    )


def compute_entry_hash(hmac_key: bytes, prev_hash: str, body: bytes) -> str:
    return hmac_sha256_hex(hmac_key, prev_hash.encode("ascii") + body)


def _validate(action: str, details: dict[str, Any]) -> bytes:
    if action not in AUDIT_ACTIONS:
        raise AuditError(f"unknown audit action: {action}")
    for key in details:
        lowered = str(key).lower()
        if lowered in _FORBIDDEN_DETAIL_KEYS or any(
            s in lowered for s in _FORBIDDEN_DETAIL_SUBSTRINGS
        ):
            raise AuditError(f"forbidden audit detail key: {key}")
    try:
        encoded = canonical_bytes(details)
    except CanonicalError as exc:
        raise AuditError(f"audit details not representable: {exc}") from exc
    if len(encoded) > MAX_DETAILS_BYTES:
        raise AuditError("audit details too large")
    return encoded


# --- appending -------------------------------------------------------------------------------


def _last_row(db: Session) -> AuditLog | None:
    return db.scalars(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)).first()


def _append(
    db: Session,
    keys: AuditKeys,
    actor_id: int | None,
    actor_role: str | None,
    action: str,
    resource_id: str | None,
    details: dict[str, Any],
) -> AuditLog:
    details_json = _validate(action, details).decode("utf-8")
    # The SELECT below starts the transaction with BEGIN IMMEDIATE (see app/db.py), so the write
    # lock is already held: no other writer can take the same seq.
    last = _last_row(db)
    seq = 1 if last is None else last.seq + 1
    prev_hash = GENESIS_HASH if last is None else last.entry_hash
    ts = clock.now_utc()
    role = None if actor_role is None else str(actor_role)
    body = _entry_body(seq, ts, actor_id, role, action, resource_id, json.loads(details_json))
    row = AuditLog(
        seq=seq,
        ts=ts,
        actor_id=actor_id,
        actor_role=role,
        action=action,
        resource_id=resource_id,
        details_json=details_json,
        prev_hash=prev_hash,
        entry_hash=compute_entry_hash(keys.hmac_key, prev_hash, body),
    )
    db.add(row)
    db.flush()
    return row


def append(
    db: Session,
    actor_id: int | None,
    actor_role: str | None,
    action: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    *,
    keys: AuditKeys | None = None,
) -> AuditLog:
    """Add an entry in the caller's transaction (does not commit). Auto-checkpoints every N."""
    keys = keys or default_keys()
    row = _append(db, keys, actor_id, actor_role, action, resource_id, details or {})
    if keys.checkpoint_every > 0 and row.seq % keys.checkpoint_every == 0:
        create_checkpoint(db, actor_id=actor_id, actor_role=actor_role, keys=keys)
    return row


# --- checkpoints -----------------------------------------------------------------------------


def _checkpoint_message(seq: int, head_hash: str) -> bytes:
    return f"{seq}:{head_hash}".encode("ascii")


def create_checkpoint(
    db: Session,
    *,
    actor_id: int | None = None,
    actor_role: str | None = None,
    keys: AuditKeys | None = None,
) -> AuditCheckpoint | None:
    """Sign the current head. Returns None for an empty log. The anchor line is written only
    after the surrounding transaction commits (a rolled-back checkpoint must leave no trace)."""
    keys = keys or default_keys()
    head = _last_row(db)
    if head is None:
        return None
    signature = b64u_encode(
        sign(keys.signing_key, _checkpoint_message(head.seq, head.entry_hash), AUDIT_CONTEXT)
    )
    checkpoint = AuditCheckpoint(
        seq=head.seq, head_hash=head.entry_hash, ts=clock.now_utc(), signature_b64=signature
    )
    db.add(checkpoint)
    db.flush()
    line = json.dumps(
        {
            "seq": head.seq,
            "head_hash": head.entry_hash,
            "ts": _fmt_ts(checkpoint.ts),
            "signature": signature,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    db.info.setdefault("pending_anchors", []).append((keys.anchor_path, line))
    _append(db, keys, actor_id, actor_role, "AUDIT_CHECKPOINT", None, {"checkpoint_seq": head.seq})
    return checkpoint


def _write_anchor(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@event.listens_for(Session, "after_commit")
def _flush_anchors(session: Session) -> None:
    for path, line in session.info.pop("pending_anchors", []):
        try:
            _write_anchor(path, line)
        except OSError:  # the DB commit already succeeded; never fail the request over this
            logger.exception("could not write audit anchor")


@event.listens_for(Session, "after_rollback")
def _discard_anchors(session: Session) -> None:
    session.info.pop("pending_anchors", None)


# --- verification ----------------------------------------------------------------------------


def _read_anchors(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Return (valid-looking anchor dicts, number of malformed lines)."""
    if not path.is_file():
        return [], 0
    anchors, malformed = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if not (
                isinstance(item["seq"], int)
                and isinstance(item["head_hash"], str)
                and isinstance(item["signature"], str)
            ):
                raise ValueError
            anchors.append(item)
        except (ValueError, KeyError, TypeError):
            malformed += 1
    return anchors, malformed


def _signature_ok(keys: AuditKeys, seq: int, head_hash: str, signature_b64: str) -> bool:
    try:
        signature = b64u_decode(signature_b64)
    except ValueError:
        return False
    return verify(
        keys.signing_key.public_key(), _checkpoint_message(seq, head_hash), signature, AUDIT_CONTEXT
    )


def verify_chain(db: Session, *, keys: AuditKeys | None = None) -> dict[str, Any]:
    """Recompute every hash, then check checkpoints and the anchor file.

    Returns {"ok", "checked", "first_bad_seq", "checkpoint_ok", "truncated", "problems", ...}.
    `first_bad_seq` is the first entry whose hash/link/sequence is wrong (for a deleted entry,
    the missing sequence number).
    """
    keys = keys or default_keys()
    problems: list[str] = []
    checked = 0
    first_bad: int | None = None
    prev_hash = GENESIS_HASH
    expected_seq = 1
    hash_by_seq: dict[int, str] = {}

    for row in db.scalars(select(AuditLog).order_by(AuditLog.seq)).yield_per(500):
        hash_by_seq[row.seq] = row.entry_hash
        if first_bad is not None:
            continue  # keep collecting hashes for checkpoint comparison, stop judging the chain
        if row.seq != expected_seq:
            first_bad, reason = expected_seq, "SEQ_GAP"
        elif row.prev_hash != prev_hash:
            first_bad, reason = row.seq, "PREV_HASH_MISMATCH"
        else:
            try:
                body = _entry_body(
                    row.seq, row.ts, row.actor_id, row.actor_role, row.action,
                    row.resource_id, json.loads(row.details_json),
                )  # fmt: skip
                good = constant_time_equal(
                    compute_entry_hash(keys.hmac_key, prev_hash, body), row.entry_hash
                )
            except (ValueError, CanonicalError):
                good = False
            if not good:
                first_bad, reason = row.seq, "ENTRY_HASH_MISMATCH"
        if first_bad is not None:
            problems.append(f"{reason}@{first_bad}")
            continue
        prev_hash = row.entry_hash
        expected_seq += 1
        checked += 1

    last_seq = max(hash_by_seq, default=0)
    checkpoint_ok = True
    truncated = False
    highest_anchored = 0

    db_checkpoints = db.scalars(select(AuditCheckpoint).order_by(AuditCheckpoint.seq)).all()
    anchors, malformed = _read_anchors(keys.anchor_path)
    if malformed:
        checkpoint_ok = False
        problems.append(f"ANCHOR_MALFORMED x{malformed}")

    def check(label: str, seq: int, head_hash: str, signature: str) -> None:
        nonlocal checkpoint_ok, truncated, highest_anchored
        if not _signature_ok(keys, seq, head_hash, signature):
            checkpoint_ok = False
            problems.append(f"{label}_SIGNATURE_INVALID@{seq}")
            return  # an unsigned/forged record proves nothing; do not trust its seq
        highest_anchored = max(highest_anchored, seq)
        if seq not in hash_by_seq:
            truncated = True
            problems.append(f"{label}_SEQ_MISSING@{seq}")
        elif not constant_time_equal(hash_by_seq[seq], head_hash):
            checkpoint_ok = False
            problems.append(f"{label}_HASH_MISMATCH@{seq}")

    for cp in db_checkpoints:
        check("CHECKPOINT", cp.seq, cp.head_hash, cp.signature_b64)
    db_cp_keys = {(cp.seq, cp.head_hash) for cp in db_checkpoints}
    for anchor in anchors:
        check("ANCHOR", anchor["seq"], anchor["head_hash"], anchor["signature"])
        if (anchor["seq"], anchor["head_hash"]) not in db_cp_keys:
            checkpoint_ok = False  # the two stores must agree; a deleted DB checkpoint shows here
            problems.append(f"ANCHOR_NOT_IN_DB@{anchor['seq']}")

    if last_seq < highest_anchored:
        truncated = True
        problems.append(f"TAIL_TRUNCATED last={last_seq} anchored={highest_anchored}")

    return {
        "ok": first_bad is None and checkpoint_ok and not truncated,
        "checked": checked,
        "first_bad_seq": first_bad,
        "checkpoint_ok": checkpoint_ok,
        "truncated": truncated,
        "problems": problems,
        "last_seq": last_seq,
        "checkpoints": len(db_checkpoints),
        "anchors": len(anchors),
    }


def verify_and_record(
    db: Session, actor_id: int | None, actor_role: str | None, *, keys: AuditKeys | None = None
) -> dict[str, Any]:
    """Run verification and log that it happened (AUDIT_VERIFIED). Caller commits."""
    keys = keys or default_keys()
    result = verify_chain(db, keys=keys)
    _append(
        db, keys, actor_id, actor_role, "AUDIT_VERIFIED", None,
        {
            "ok": result["ok"],
            "checked": result["checked"],
            "first_bad_seq": result["first_bad_seq"],
        },
    )  # fmt: skip
    return result


def total_entries(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0

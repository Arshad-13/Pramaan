"""P2: HMAC-chained audit log, signed checkpoints, anchor file, tamper detection."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core import audit
from app.core.audit import AuditError, AuditKeys
from app.core.keys import load_signing_key_from_file
from app.db import SessionLocal
from app.models import AuditCheckpoint, AuditLog
from tests.conftest import TEST_ENV


@pytest.fixture
def keys(tmp_path: Path) -> AuditKeys:
    return AuditKeys(
        hmac_key=b"H" * 32,
        signing_key=load_signing_key_from_file(TEST_ENV["AUDIT_SIGNING_KEY_PATH"]),
        anchor_path=tmp_path / "anchors.jsonl",
        checkpoint_every=0,  # tests create checkpoints explicitly unless stated
    )


def fill(db, keys, n=10, start=0):
    for i in range(start, start + n):
        audit.append(db, 1, "doctor", "LOGIN_SUCCESS", f"res-{i}", {"i": i}, keys=keys)
    db.commit()


def raw(db, sql, **params):
    """Attacker view: change the database underneath the application."""
    db.execute(text(sql), params)
    db.commit()
    db.expire_all()


# --- appending ------------------------------------------------------------------------------


def test_entries_are_sequential_and_chained(db, keys):
    fill(db, keys, 5)
    rows = db.query(AuditLog).order_by(AuditLog.seq).all()
    assert [r.seq for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0].prev_hash == audit.GENESIS_HASH
    for prev, row in zip(rows, rows[1:], strict=False):
        assert row.prev_hash == prev.entry_hash
    assert all(len(r.entry_hash) == 64 for r in rows)


def test_hash_is_keyed_not_plain_sha256(db, keys):
    fill(db, keys, 1)
    row = db.query(AuditLog).one()
    body = audit._entry_body(
        row.seq, row.ts, row.actor_id, row.actor_role, row.action, row.resource_id,
        json.loads(row.details_json),
    )  # fmt: skip
    plain = hashlib.sha256(audit.GENESIS_HASH.encode() + body).hexdigest()
    assert row.entry_hash != plain
    assert row.entry_hash == audit.compute_entry_hash(keys.hmac_key, audit.GENESIS_HASH, body)
    other_key = audit.compute_entry_hash(b"X" * 32, audit.GENESIS_HASH, body)
    assert row.entry_hash != other_key


def test_append_does_not_commit(db, keys):
    audit.append(db, 1, "doctor", "LOGIN_SUCCESS", keys=keys)
    db.rollback()
    assert db.query(AuditLog).count() == 0


def test_role_enum_is_stored_as_plain_text(db, keys):
    from app.models import Role

    audit.append(db, 1, Role.doctor, "LOGIN_SUCCESS", keys=keys)
    db.commit()
    assert db.query(AuditLog).one().actor_role == "doctor"


@pytest.mark.parametrize(
    ("action", "details"),
    [
        ("NOT_A_REAL_ACTION", {}),
        ("LOGIN_FAIL", {"password": "x"}),
        ("LOGIN_FAIL", {"signing_password": "x"}),
        ("LOGIN_FAIL", {"Token": "abc"}),
        ("RX_ISSUED", {"patient_name": "Ravi"}),
        ("RX_ISSUED", {"email": "a@b.test"}),
        ("RX_ISSUED", {"pin": "123456"}),
        ("RX_ISSUED", {"private_key": "x"}),
        ("RX_ISSUED", {"ratio": 1.5}),  # floats are not canonical
        ("RX_ISSUED", {"blob": "x" * 3000}),
        ("RX_ISSUED", {"bidi": "a\u202eb"}),
    ],
)
def test_invalid_or_sensitive_entries_are_refused(db, keys, action, details):
    with pytest.raises(AuditError):
        audit.append(db, 1, "doctor", action, "rx", details, keys=keys)


def test_ids_and_codes_are_accepted(db, keys):
    audit.append(
        db, 1, "doctor", "RX_ISSUED", "rx-1", {"key_id": "9a1c0e77b2d4f605", "risk": 12}, keys=keys
    )
    db.commit()


# --- verification: clean ----------------------------------------------------------------------


def test_empty_log_verifies(db, keys):
    result = audit.verify_chain(db, keys=keys)
    assert result["ok"] and result["checked"] == 0 and result["first_bad_seq"] is None


def test_clean_chain_verifies(db, keys):
    fill(db, keys, 25)
    result = audit.verify_chain(db, keys=keys)
    assert result == {**result, "ok": True, "checked": 25, "first_bad_seq": None,
                      "checkpoint_ok": True, "truncated": False}  # fmt: skip


def test_verification_survives_round_trip_of_timestamps_and_unicode(db, keys):
    audit.append(db, 2, "pharmacist", "RX_VERIFIED", "rx", {"note": "caf\u00e9"}, keys=keys)
    db.commit()
    db.expire_all()
    assert audit.verify_chain(db, keys=keys)["ok"]


# --- verification: tampering ------------------------------------------------------------------


def test_edited_details_detected_at_the_right_seq(db, keys):
    fill(db, keys, 10)
    raw(db, "UPDATE audit_log SET details_json = :d WHERE seq = 6", d='{"i":999}')
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["first_bad_seq"] == 6 and result["checked"] == 5


@pytest.mark.parametrize(
    "assignment",
    [
        "actor_role = 'admin'",
        "actor_id = 99",
        "action = 'RX_REVOKED'",
        "resource_id = 'other'",
        "ts = '2020-01-01 00:00:00.000000'",
    ],
)
def test_every_signed_field_is_covered(db, keys, assignment):
    fill(db, keys, 6)
    raw(db, f"UPDATE audit_log SET {assignment} WHERE seq = 3")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["first_bad_seq"] == 3


def test_deleted_middle_entry_reports_the_missing_seq(db, keys):
    fill(db, keys, 10)
    raw(db, "DELETE FROM audit_log WHERE seq = 7")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["first_bad_seq"] == 7


def test_deleted_first_entry_detected(db, keys):
    fill(db, keys, 5)
    raw(db, "DELETE FROM audit_log WHERE seq = 1")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["first_bad_seq"] == 1


def test_broken_link_detected(db, keys):
    fill(db, keys, 6)
    raw(db, f"UPDATE audit_log SET prev_hash = '{'f' * 64}' WHERE seq = 4")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["first_bad_seq"] == 4


def test_edit_and_recompute_with_plain_sha256_still_fails(db, keys):
    """An insider without AUDIT_KEY rewrites a row and 'repairs' every later hash with SHA-256."""
    fill(db, keys, 8)
    raw(db, "UPDATE audit_log SET details_json = :d WHERE seq = 4", d='{"i":-1}')
    prev = db.query(AuditLog).filter_by(seq=3).one().entry_hash
    for row in db.query(AuditLog).filter(AuditLog.seq >= 4).order_by(AuditLog.seq).all():
        body = audit._entry_body(
            row.seq, row.ts, row.actor_id, row.actor_role, row.action, row.resource_id,
            json.loads(row.details_json),
        )  # fmt: skip
        new_hash = hashlib.sha256(prev.encode() + body).hexdigest()
        raw(db, "UPDATE audit_log SET prev_hash=:p, entry_hash=:h WHERE seq=:s",
            p=prev, h=new_hash, s=row.seq)  # fmt: skip
        prev = new_hash
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["first_bad_seq"] == 4


# --- checkpoints and truncation ---------------------------------------------------------------


def make_checkpoint(db, keys):
    cp = audit.create_checkpoint(db, keys=keys)
    db.commit()
    return cp


def test_checkpoint_is_signed_anchored_and_logged(db, keys):
    fill(db, keys, 5)
    cp = make_checkpoint(db, keys)
    assert cp.seq == 5
    assert db.query(AuditLog).order_by(AuditLog.seq.desc()).first().action == "AUDIT_CHECKPOINT"
    lines = keys.anchor_path.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["seq"] == 5
    result = audit.verify_chain(db, keys=keys)
    assert result["ok"] and result["checkpoints"] == 1 and result["anchors"] == 1


def test_checkpoint_on_empty_log_is_a_noop(db, keys):
    assert audit.create_checkpoint(db, keys=keys) is None


def test_chain_alone_cannot_see_tail_deletion_but_a_checkpoint_can(db, keys):
    """Documented limit: deleting the newest rows is invisible to the chain until a checkpoint
    covers them."""
    fill(db, keys, 8)
    raw(db, "DELETE FROM audit_log WHERE seq > 5")
    assert audit.verify_chain(db, keys=keys)["ok"]  # no checkpoint existed: undetectable

    db.query(AuditLog).delete()
    db.commit()
    fill(db, keys, 8)
    make_checkpoint(db, keys)  # seq 8 checkpointed (+ entry 9)
    raw(db, "DELETE FROM audit_log WHERE seq > 5")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["truncated"]


def test_truncation_detected_from_anchor_even_if_db_checkpoints_are_deleted(db, keys):
    fill(db, keys, 8)
    make_checkpoint(db, keys)
    raw(db, "DELETE FROM audit_log WHERE seq > 4")
    raw(db, "DELETE FROM audit_checkpoints")  # attacker also wipes the DB checkpoints
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and result["truncated"]


def test_forged_checkpoint_signature_is_detected(db, keys):
    fill(db, keys, 5)
    make_checkpoint(db, keys)
    raw(db, "UPDATE audit_checkpoints SET signature_b64 = 'AAAA'")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and not result["checkpoint_ok"]


def test_attacker_with_the_hmac_key_but_not_the_signing_key_is_caught_by_checkpoint(db, keys):
    """Edit a checkpointed row and recompute the *correct* HMAC chain."""
    fill(db, keys, 8)
    make_checkpoint(db, keys)
    raw(db, "UPDATE audit_log SET details_json = :d WHERE seq = 3", d='{"i":-1}')
    prev = db.query(AuditLog).filter_by(seq=2).one().entry_hash
    for row in db.query(AuditLog).filter(AuditLog.seq >= 3).order_by(AuditLog.seq).all():
        body = audit._entry_body(
            row.seq, row.ts, row.actor_id, row.actor_role, row.action, row.resource_id,
            json.loads(row.details_json),
        )  # fmt: skip
        new_hash = audit.compute_entry_hash(keys.hmac_key, prev, body)
        raw(db, "UPDATE audit_log SET prev_hash=:p, entry_hash=:h WHERE seq=:s",
            p=prev, h=new_hash, s=row.seq)  # fmt: skip
        prev = new_hash
    result = audit.verify_chain(db, keys=keys)
    assert result["first_bad_seq"] is None  # the rewritten chain is internally consistent...
    assert not result["ok"] and not result["checkpoint_ok"]  # ...but contradicts the signed head


def test_anchor_missing_from_db_is_flagged(db, keys):
    fill(db, keys, 4)
    make_checkpoint(db, keys)
    raw(db, "DELETE FROM audit_checkpoints")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and not result["checkpoint_ok"]


def test_malformed_anchor_line_is_flagged(db, keys):
    fill(db, keys, 4)
    make_checkpoint(db, keys)
    with open(keys.anchor_path, "a") as handle:
        handle.write("not json\n")
    result = audit.verify_chain(db, keys=keys)
    assert not result["ok"] and not result["checkpoint_ok"]


def test_rolled_back_checkpoint_leaves_no_anchor_line(db, keys):
    fill(db, keys, 4)
    audit.create_checkpoint(db, keys=keys)
    db.rollback()
    assert not keys.anchor_path.exists() or keys.anchor_path.read_text() == ""
    assert db.query(AuditCheckpoint).count() == 0
    assert audit.verify_chain(db, keys=keys)["ok"]


def test_auto_checkpoint_every_n_entries(db, tmp_path):
    keys = AuditKeys(
        hmac_key=b"H" * 32,
        signing_key=load_signing_key_from_file(TEST_ENV["AUDIT_SIGNING_KEY_PATH"]),
        anchor_path=tmp_path / "a.jsonl",
        checkpoint_every=10,
    )
    fill(db, keys, 35)
    result = audit.verify_chain(db, keys=keys)
    assert result["ok"] and result["checkpoints"] >= 3
    assert len(keys.anchor_path.read_text().splitlines()) == result["checkpoints"]


def test_verify_and_record_logs_the_check(db, keys):
    fill(db, keys, 3)
    result = audit.verify_and_record(db, 7, "auditor", keys=keys)
    db.commit()
    assert result["ok"]
    last = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
    assert last.action == "AUDIT_VERIFIED" and json.loads(last.details_json)["ok"] is True
    assert audit.verify_chain(db, keys=keys)["ok"]


# --- concurrency ------------------------------------------------------------------------------


def test_concurrent_appends_get_unique_contiguous_sequence_numbers(db, keys):
    threads, per_thread = 8, 10
    errors: list[Exception] = []

    def worker(n: int):
        session = SessionLocal()
        try:
            for i in range(per_thread):
                audit.append(
                    session, n, "doctor", "LOGIN_SUCCESS", f"t{n}-{i}", {"i": i}, keys=keys
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the main thread
            errors.append(exc)
        finally:
            session.close()

    pool = [threading.Thread(target=worker, args=(n,)) for n in range(threads)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()

    assert not errors, errors
    db.expire_all()
    assert sorted(r.seq for r in db.query(AuditLog).all()) == list(
        range(1, threads * per_thread + 1)
    )
    assert audit.verify_chain(db, keys=keys)["ok"]

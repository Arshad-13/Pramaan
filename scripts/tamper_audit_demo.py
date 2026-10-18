"""Audit-log tamper demo: attack the log the way an insider with database access would.

Usage:
    python scripts/tamper_audit_demo.py --mode edit
    python scripts/tamper_audit_demo.py --mode recompute
    python scripts/tamper_audit_demo.py --mode truncate [--count 3]

Modes:
  edit       change one row's details directly in SQLite              -> chain fails at that seq
  recompute  edit a row AND recompute the hashes after it with plain
             SHA-256 (the attacker does not know AUDIT_KEY)           -> still fails (HMAC)
  truncate   delete the newest rows                                    -> caught by the signed
             checkpoint / anchor file (needs a checkpoint covering them)

By default the attack runs on a COPY of the database (`<db>.demo`), so your real data is safe.
Use --in-place to attack the real database (for the live demo in the UI). --seed N appends N demo
entries and a checkpoint first, so the demo works on an empty database too.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core import audit  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import Base  # noqa: E402


def _db_path(url: str) -> Path:
    database = make_url(url).database
    if not database:
        raise SystemExit("This demo needs a file-based SQLite database.")
    path = Path(database)
    return path if path.is_absolute() else (ROOT / path).resolve()


def _copy_db(src: Path, dst: Path) -> None:
    """Consistent copy (works while WAL is active) using SQLite's backup API."""
    dst.unlink(missing_ok=True)
    source, target = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _show(title: str, result: dict) -> None:
    status = "PASS (chain intact)" if result["ok"] else "FAIL (tampering detected)"
    print(f"\n== {title}: {status}")
    print(
        f"   checked={result['checked']} first_bad_seq={result['first_bad_seq']} "
        f"checkpoint_ok={result['checkpoint_ok']} truncated={result['truncated']}"
    )
    for problem in result["problems"]:
        print(f"   - {problem}")


def _attack_edit(conn: sqlite3.Connection, seq: int) -> None:
    conn.execute(
        "UPDATE audit_log SET details_json = ? WHERE seq = ?",
        (json.dumps({"tampered": True}, separators=(",", ":")), seq),
    )
    print(f"Attacker edited details of entry {seq} directly in SQLite.")


def _attack_recompute(conn: sqlite3.Connection, seq: int) -> None:
    """Edit a row, then 'repair' the chain from there using plain SHA-256."""
    _attack_edit(conn, seq)
    rows = conn.execute(
        "SELECT seq, ts, actor_id, actor_role, action, resource_id, details_json, prev_hash "
        "FROM audit_log WHERE seq >= ? ORDER BY seq",
        (seq,),
    ).fetchall()
    prev = conn.execute("SELECT entry_hash FROM audit_log WHERE seq = ?", (seq - 1,)).fetchone()
    prev_hash = prev[0] if prev else audit.GENESIS_HASH
    for row in rows:
        body = json.dumps(
            {"seq": row[0], "ts": str(row[1]), "action": row[4], "details": row[6]}, sort_keys=True
        ).encode()
        new_hash = hashlib.sha256(prev_hash.encode() + body).hexdigest()  # attacker has no HMAC key
        conn.execute(
            "UPDATE audit_log SET prev_hash = ?, entry_hash = ? WHERE seq = ?",
            (prev_hash, new_hash, row[0]),
        )
        prev_hash = new_hash
    print(f"Attacker edited entry {seq} and recomputed every later hash with plain SHA-256.")


def _attack_truncate(conn: sqlite3.Connection, count: int) -> None:
    last = conn.execute("SELECT MAX(seq) FROM audit_log").fetchone()[0]
    conn.execute("DELETE FROM audit_log WHERE seq > ?", (last - count,))
    print(f"Attacker deleted the newest {count} entries (seq {last - count + 1}..{last}).")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--mode", choices=["edit", "recompute", "truncate"], required=True)
    parser.add_argument("--seq", type=int, help="entry to edit (default: middle of the log)")
    parser.add_argument("--count", type=int, default=3, help="rows to delete in truncate mode")
    parser.add_argument("--seed", type=int, default=0, help="append N demo entries first")
    parser.add_argument("--in-place", action="store_true", help="attack the real database")
    args = parser.parse_args()

    settings = get_settings()
    real = _db_path(settings.database_url)
    target = real if args.in_place else real.with_suffix(real.suffix + ".demo")
    if args.in_place:
        print(f"WARNING: attacking the REAL database {real}")
    elif real.exists():
        _copy_db(real, target)
    url = f"sqlite:///{target.as_posix()}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    keys = audit.default_keys()
    if not args.in_place:
        # The copy gets its own anchor file too, so demo checkpoints never pollute the real one.
        demo_anchor = keys.anchor_path.with_name(keys.anchor_path.stem + ".demo.jsonl")
        demo_anchor.unlink(missing_ok=True)
        if keys.anchor_path.is_file():
            shutil.copyfile(keys.anchor_path, demo_anchor)
        keys = replace(keys, anchor_path=demo_anchor)
    if args.seed:
        with session_factory() as db:
            for i in range(args.seed):
                audit.append(db, None, "admin", "LOGIN_SUCCESS", None, {"demo": i}, keys=keys)
            audit.create_checkpoint(db, keys=keys)  # covers the seeded entries (and is anchored)
            db.commit()

    with session_factory() as db:
        before = audit.verify_chain(db, keys=keys)
        total = before["last_seq"]
    _show("BEFORE attack", before)
    if total < 3:
        raise SystemExit("Need at least 3 entries. Re-run with --seed 20.")

    raw = sqlite3.connect(target)
    try:
        if args.mode == "edit":
            _attack_edit(raw, args.seq or total // 2)
        elif args.mode == "recompute":
            _attack_recompute(raw, args.seq or total // 2)
        else:
            _attack_truncate(raw, args.count)
        raw.commit()
    finally:
        raw.close()

    with session_factory() as db:
        after = audit.verify_chain(db, keys=keys)
    _show("AFTER attack", after)
    if not args.in_place:
        print(f"\n(Attack ran on a copy: {target}. Your real database was not touched.)")
    return 0 if not after["ok"] else 1  # the demo succeeds when tampering IS detected


if __name__ == "__main__":
    sys.exit(main())

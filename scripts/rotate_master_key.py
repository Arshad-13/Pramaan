"""Rotate the master key (KEK) that wraps every prescription's data key (Phase 9).

Usage : python scripts/rotate_master_key.py [--dry-run] [--no-env-update]
Steps : 1. make a new random master key and save it to secrets/master_key.next (so it survives
           even if the next steps are interrupted);
        2. re-wrap every data key and patient-PIN secret under it, in ONE database transaction;
        3. prove every payload and PDF is still readable with the new key (else roll back);
        4. commit, then write MASTER_KEY and MASTER_KEY_VERSION into .env (a copy of the old .env
           is kept as .env.bak).
Run it with the API STOPPED and a backup of the database and storage/ folder. --dry-run does steps
2-3 and rolls back, to show it would work.
If something fails after step 4 begins, the new key is in secrets/master_key.next and the version
to use is printed: put them in .env by hand.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services.rotation import RotationError, rotate  # noqa: E402


def _set_env(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: f"{key}={value}", text, count=1)
    return text.rstrip("\n") + f"\n{key}={value}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-env-update", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    old_version = settings.master_key_version
    new_version = old_version + 1
    new_kek = os.urandom(32)
    new_b64 = base64.b64encode(new_kek).decode("ascii")

    next_file = ROOT / "secrets" / "master_key.next"
    if not args.dry_run:
        next_file.parent.mkdir(parents=True, exist_ok=True)
        next_file.write_text(new_b64, encoding="ascii")

    init_db()
    with SessionLocal() as db:
        try:
            count = rotate(
                db,
                old_kek=settings.master_key_bytes,
                new_kek=new_kek,
                old_version=old_version,
                new_version=new_version,
            )
        except RotationError as exc:
            db.rollback()
            print(f"Rotation failed, nothing changed: {exc}")
            return 1
        if args.dry_run:
            db.rollback()
            print(
                f"Dry run: {count} prescriptions can be re-wrapped and stay readable. Rolled back."
            )
            return 0
        db.commit()
    print(f"Re-wrapped {count} prescriptions (key version {old_version} -> {new_version}).")

    env_file = ROOT / ".env"
    if args.no_env_update or not env_file.is_file():
        print(
            f"Set MASTER_KEY to the contents of {next_file} and MASTER_KEY_VERSION={new_version}."
        )
        return 0
    original = env_file.read_text(encoding="utf-8")
    (ROOT / ".env.bak").write_text(original, encoding="utf-8")
    updated = _set_env(original, "MASTER_KEY", new_b64)
    updated = _set_env(updated, "MASTER_KEY_VERSION", str(new_version))
    env_file.write_text(updated, encoding="utf-8")
    print(".env updated (old copy saved as .env.bak). Start the API again.")
    print(
        "Keep .env.bak and secrets/master_key.next until you have checked the app, then delete them."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

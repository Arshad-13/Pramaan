"""Generate local secrets: writes `.env` and `secrets/audit_signing.pem`.

Purpose: give each developer their own fresh keys; nothing is ever committed.
Usage  : python scripts/gen_keys.py [--force] [--print]
Outputs: `.env` (copied from .env.example with real values) and `secrets/audit_signing.pem`.

Secret values are NOT printed unless you pass --print (so they do not land in terminal
scrollback or CI logs by accident).
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"
PEM_FILE = ROOT / "secrets" / "audit_signing.pem"


def _b64_32() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _set(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if not pattern.search(text):
        raise SystemExit(f".env.example is missing {key}")
    return pattern.sub(lambda _m: f"{key}={value}", text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing .env and key")
    parser.add_argument("--print", dest="show", action="store_true", help="print secrets")
    args = parser.parse_args()

    if (ENV_FILE.exists() or PEM_FILE.exists()) and not args.force:
        print("A .env or audit key already exists. Re-run with --force to replace them.")
        print("(Replacing keys makes existing encrypted data and audit entries unreadable.)")
        return 1

    secret_key = secrets.token_urlsafe(48)
    master_key = _b64_32()
    audit_key = _b64_32()

    PEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    private_key = ec.generate_private_key(ec.SECP256R1())
    PEM_FILE.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    try:
        PEM_FILE.chmod(0o600)  # best effort; limited effect on Windows
    except OSError:
        pass

    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    text = _set(text, "SECRET_KEY", secret_key)
    text = _set(text, "MASTER_KEY", master_key)
    text = _set(text, "AUDIT_KEY", audit_key)
    ENV_FILE.write_text(text, encoding="utf-8")

    print(f"Wrote {ENV_FILE.relative_to(ROOT)} and {PEM_FILE.relative_to(ROOT)} (git-ignored).")
    if args.show:
        print(f"SECRET_KEY={secret_key}\nMASTER_KEY={master_key}\nAUDIT_KEY={audit_key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

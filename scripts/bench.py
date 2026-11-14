"""Measure how long the main operations take, on a throw-away seeded copy of the app.

Usage : python scripts/bench.py [--runs 20] [--write docs/performance.md]

Everything runs in a temporary directory (never your real database) and in-process through the
FastAPI test client, so the numbers include the full application stack (validation, database,
cryptography, PDF and image work) but not a network. Treat them as "how heavy is each step" on
this machine, not as a capacity claim: the demo is a single-process SQLite app.
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def percentile(sorted_ms: list[float], fraction: float) -> float:
    index = min(len(sorted_ms) - 1, max(0, round(fraction * (len(sorted_ms) - 1))))
    return sorted_ms[index]


def measure(label: str, runs: int, action: Callable[[int], object]) -> tuple[str, list[float]]:
    action(-1)  # one warm-up call: imports, caches, JIT-like first-use costs
    samples: list[float] = []
    for i in range(runs):
        start = time.perf_counter()
        action(i)
        samples.append((time.perf_counter() - start) * 1000)
    print(f"  {label:<42} median {statistics.median(samples):7.1f} ms", flush=True)
    return label, sorted(samples)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20, help="timed runs per operation")
    parser.add_argument("--write", type=Path, help="also write a Markdown table to this file")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="pramaan-bench-"))
    (workdir / "storage").mkdir()
    os.environ.update(
        DATABASE_URL=f"sqlite:///{(workdir / 'bench.db').as_posix()}",
        STORAGE_DIR=str(workdir / "storage"),
        ANCHOR_FILE=str(workdir / "storage" / "anchors.jsonl"),
        RATE_LIMIT_ENABLED="false",
        COOKIE_SECURE="false",
    )

    import seed_demo
    from fastapi.testclient import TestClient

    from app.db import init_db
    from app.main import create_app

    init_db()
    app = create_app()
    print("Seeding a throw-away demo world...", flush=True)
    with TestClient(app) as client:
        world = seed_demo.seed(client)

        def bearer(account: tuple[str, str]) -> dict[str, str]:
            return seed_demo._bearer(client, *account)  # noqa: SLF001

        shah = bearer(world.doctors[0])
        meera = bearer(world.pharmacists[0])
        auditor = bearer(world.auditor)
        patient_id = client.get(
            "/api/patients/lookup", headers=shah, params={"email": world.patients[0][0]}
        ).json()["public_id"]
        ready_qr = world.qr["ready"]
        ready_pdf = world.pdf["ready"]

        def sign_in(_: int) -> None:
            assert (
                client.post(
                    "/api/auth/login",
                    json={"email": world.pharmacists[0][0], "password": world.pharmacists[0][1]},
                ).status_code
                == 200
            )

        def issue(i: int) -> None:
            # Different doses so the anomaly check sees ordinary, varied prescribing.
            response = client.post(
                "/api/prescriptions",
                headers=shah,
                json={
                    "patient_id": patient_id,
                    "medicines": [
                        {
                            "name": "Amoxicillin",
                            "dose_mg": 250 + (i % 3) * 250,
                            "frequency": "TDS",
                            "duration_days": 5,
                        }
                    ],
                    "notes": "",
                    "validity_days": 30,
                    "max_fills": 1,
                    "signing_password": world.signing_password,
                    "require_pin": True,
                },
            )
            assert response.status_code == 201, response.text

        def verify_qr(_: int) -> None:
            response = client.post("/api/verify/qr", headers=meera, json={"qr_string": ready_qr})
            assert (
                response.status_code == 200 and response.json()["result"] == "VALID"
            ), response.text

        def verify_pdf(_: int) -> None:
            response = client.post(
                "/api/verify/upload",
                headers=meera,
                files={"file": ("ready.pdf", ready_pdf, "application/pdf")},
            )
            assert (
                response.status_code == 200 and response.json()["result"] == "VALID"
            ), response.text

        def audit_verify(_: int) -> None:
            assert client.get("/api/admin/audit/verify", headers=auditor).status_code == 200

        print(f"Timing {args.runs} runs each (after one warm-up):", flush=True)
        results = [
            measure("Sign in (argon2id password check)", args.runs, sign_in),
            measure("Issue a prescription (sign + PDF + risk)", args.runs, issue),
            measure("Verify a QR code", args.runs, verify_qr),
            measure("Verify an uploaded PDF (page check)", args.runs, verify_pdf),
            measure("Verify the whole audit chain", args.runs, audit_verify),
        ]
        entries = client.get("/api/admin/audit?limit=1", headers=auditor).json()["total"]

    rows = ["| Operation | Median | 95th percentile | Slowest |", "|---|---:|---:|---:|"]
    for label, samples in results:
        rows.append(
            f"| {label} | {statistics.median(samples):.0f} ms | {percentile(samples, 0.95):.0f} ms | {samples[-1]:.0f} ms |"
        )
    table = "\n".join(rows)
    print("\n" + table)

    if args.write:
        args.write.write_text(
            "# Performance\n\n"
            "Generated by `python scripts/bench.py`. Each operation ran "
            f"{args.runs} times after one warm-up, in-process on a throw-away database "
            f"holding {entries} audit entries. Python {platform.python_version()} on "
            f"{platform.system()} {platform.release()}.\n\n"
            f"{table}\n\n"
            "These show how heavy each step is on one machine. They are not a capacity claim: the "
            "demo is one process on SQLite, and a network adds its own time. The slow steps are slow "
            "on purpose or by nature: argon2id is deliberately costly to make password guessing "
            "expensive, and verifying the audit chain re-computes every entry.\n",
            encoding="utf-8",
        )
        print(f"\nWrote {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

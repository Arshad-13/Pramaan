"""Serve a throw-away, freshly seeded copy of Pramaan for the Playwright end-to-end test.

Usage : python scripts/e2e_server.py [--port 8002]
It never touches your real database: everything lives in `.e2e/` (git-ignored). The built frontend
(`frontend/dist`) is served by the API itself, so one process is the whole app. Rate limits are
off here because the test signs in as many roles in a few seconds.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
E2E = ROOT / ".e2e"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()

    shutil.rmtree(E2E, ignore_errors=True)
    (E2E / "storage").mkdir(parents=True)
    # Environment first: settings are read once, when the app module is imported.
    os.environ.update(
        DATABASE_URL=f"sqlite:///{(E2E / 'e2e.db').as_posix()}",
        STORAGE_DIR=str(E2E / "storage"),
        ANCHOR_FILE=str(E2E / "storage" / "anchors.jsonl"),
        RATE_LIMIT_ENABLED="false",
        COOKIE_SECURE="false",
    )

    import seed_demo
    import uvicorn
    from fastapi.testclient import TestClient

    from app.db import init_db
    from app.main import create_app

    init_db()
    app = create_app()
    with TestClient(app) as client:
        world = seed_demo.seed(client)
    seed_demo.write_samples(world, E2E / "samples")
    print(
        f"Seeded. Sample files in {E2E / 'samples'}. Serving on http://localhost:{args.port}",
        flush=True,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""FastAPI application entry point.

Purpose: build the app, run fail-closed startup checks, expose /api routes, and (in
production) serve the built React app from `frontend/dist` on the same origin.
Run   : `uvicorn app.main:app`
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import ConfigError, get_settings
from app.db import init_db

logger = logging.getLogger("pramaan")

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info("Pramaan started; database ready.")
    yield


api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict[str, str]:
    """Liveness only. Deliberately returns no version, path or config details."""
    return {"status": "ok"}


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA with a fallback to index.html (client-side routing)."""
    index = dist / "index.html"
    if not index.is_file():
        return
    dist_root = dist.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (dist / full_path).resolve()
        # Serve real files (favicon etc.) but never anything outside dist.
        if full_path and candidate.is_file() and dist_root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


def create_app(frontend_dist: Path = FRONTEND_DIST) -> FastAPI:
    try:
        settings = get_settings()
    except ConfigError as exc:
        # Fail closed with a clear message instead of a traceback full of context.
        sys.stderr.write(f"\nPramaan refuses to start: {exc}\n\n")
        raise SystemExit(1) from None

    app = FastAPI(
        title="Pramaan",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )
    app.include_router(api)
    _mount_frontend(app, frontend_dist)
    return app


app = create_app()

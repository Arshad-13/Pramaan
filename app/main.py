"""FastAPI application entry point.

Purpose: build the app, run fail-closed startup checks, expose /api routes, and (in
production) serve the built React app from `frontend/dist` on the same origin.
Run   : `uvicorn app.main:app`
"""

from __future__ import annotations

import logging
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import ConfigError, get_settings
from app.db import get_engine, init_db
from app.errors import ServiceError
from app.routers import admin, auth, keys, prescriptions, verify

logger = logging.getLogger("pramaan")

# Scripts only from our own origin; styles allow inline because the UI sets style attributes.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
    "worker-src 'self' blob:; media-src 'self' blob:; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
access_logger = logging.getLogger("pramaan.access")


def _failed_readiness_checks() -> list[str]:
    """Names of the things this process needs that are not working right now."""
    failed: list[str] = []
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:  # any failure at all means "not ready"; the detail is not returned
        failed.append("database")
    if not Path(get_settings().audit_signing_key_path).is_file():
        failed.append("audit signing key")
    return failed


def _request_id(request: Request) -> str:
    """Reuse a caller's id only if it is short and plain (it ends up in logs); else make one."""
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _SAFE_REQUEST_ID.fullmatch(supplied) else uuid.uuid4().hex


def _configure_access_log() -> None:
    """One line per request on stderr, once (create_app may be called more than once in tests)."""
    if access_logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    logger.info("Pramaan started; database ready.")
    yield


def build_api_router() -> APIRouter:
    """A fresh /api router per app instance (so repeated create_app() calls never share state)."""
    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict[str, str]:
        """Liveness only. Deliberately returns no version, path or config details."""
        return {"status": "ok"}

    @api.get("/ready")
    def ready() -> JSONResponse:
        """Readiness: can this process actually serve? Says ok or degraded and nothing more; the
        failing check is logged server-side, never returned."""
        failed = _failed_readiness_checks()
        for name in failed:
            logger.error("readiness check failed: %s", name)
        status = {"status": "degraded" if failed else "ok"}
        return JSONResponse(status, status_code=503 if failed else 200)

    api.include_router(auth.router)
    api.include_router(admin.router)
    api.include_router(keys.router)
    api.include_router(prescriptions.router)
    api.include_router(verify.router)
    return api


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
    app.include_router(build_api_router())

    _configure_access_log()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        request_id = _request_id(request)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        if request.url.path.startswith("/api/"):
            # Method, path (never the query string: it can hold an email), status, time, id.
            access_logger.info(
                "%s %s %d %.0fms rid=%s",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                request_id,
            )
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # never keep records in a shared cache
        if settings.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        headers = dict(exc.headers)
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        body = {"detail": exc.message, **exc.extra}
        return JSONResponse(body, status_code=exc.status_code, headers=headers or None)

    _mount_frontend(app, frontend_dist)
    return app


app = create_app()

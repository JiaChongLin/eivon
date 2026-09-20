"""Eivon application factory. No business integration is required to start."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from eivon import __version__
from eivon.core.extensions import ExtensionRegistry

from .api import artifacts as artifacts_api
from .api import auth, resources, runs, system
from .api import evaluations as evaluations_api
from .api import knowledge as knowledge_api
from .artifacts import Artifacts
from .db import Database
from .errors import ServiceError
from .evaluations import Evaluations
from .knowledge import Knowledge
from .resources import Resources
from .runs import Runs
from .security import Security
from .settings import Settings
from .worker import RunWorker

logger = logging.getLogger("eivon")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database = Database(settings)
    database.initialize()
    security = Security(database, settings)
    if settings.extension_runner not in {"trusted", "process"}:
        raise ValueError("EIVON_EXTENSION_RUNNER must be trusted or process")
    extensions = ExtensionRegistry(mode=settings.extension_runner)
    extensions.load(settings.extensions)
    resources_service = Resources(database)
    artifacts = Artifacts(database, settings)
    knowledge = Knowledge(database)
    run_service = Runs(database, resources_service)
    evaluations = Evaluations(database, run_service)
    worker = RunWorker(database, run_service, settings, security, artifacts, extensions, knowledge)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if settings.inline_worker:
            task = asyncio.create_task(worker.loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            database.engine.dispose()

    app = FastAPI(title="Eivon API", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.state.security = security
    app.state.resources = resources_service
    app.state.extensions = extensions
    app.state.artifacts = artifacts
    app.state.runs = run_service
    app.state.worker = worker
    app.state.knowledge = knowledge
    app.state.evaluations = evaluations

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        request.state.request_id = secrets.token_hex(12)
        content_length = request.headers.get("content-length", "0")
        try:
            if int(content_length) > settings.max_upload_bytes + 100_000:
                return JSONResponse(
                    {
                        "error": {
                            "code": "request_too_large",
                            "message": "Request body is too large",
                            "request_id": request.state.request_id,
                        }
                    },
                    status_code=413,
                )
        except ValueError:
            return JSONResponse(
                {"error": {"code": "invalid_length", "message": "Invalid Content-Length"}},
                status_code=400,
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's input field may contain passwords; never include it in errors.
        issues = [{"loc": e["loc"], "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": issues,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error(
            "request_failed request_id=%s exception_type=%s",
            getattr(request.state, "request_id", "-"),
            type(exc).__name__,
        )
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An internal error occurred",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            status_code=500,
        )

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready", include_in_schema=False)
    def ready():
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "initialized": security.initialized()}

    app.include_router(auth.router, prefix="/api/v1", tags=["identity"])
    app.include_router(resources.router, prefix="/api/v1", tags=["resources"])
    app.include_router(runs.router, prefix="/api/v1", tags=["runs"])
    app.include_router(system.router, prefix="/api/v1", tags=["system"])
    app.include_router(artifacts_api.router, prefix="/api/v1", tags=["artifacts"])
    app.include_router(knowledge_api.router, prefix="/api/v1", tags=["knowledge"])
    app.include_router(evaluations_api.router, prefix="/api/v1", tags=["evaluations"])
    console_dir = settings.console_dir or Path(__file__).resolve().parents[3] / "console" / "dist"
    if console_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=console_dir / "assets"), name="console-assets")

        @app.get("/{path:path}", include_in_schema=False)
        def console(path: str):
            if path.startswith(("api/", "health/")):
                raise ServiceError("not_found", "Not found", 404)
            candidate = console_dir / path
            if path and candidate.is_file() and console_dir in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(console_dir / "index.html")

    return app

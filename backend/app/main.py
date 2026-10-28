"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import __version__
from .api.routes import router
from .config import Settings, get_settings
from .db import Database
from .services.experiments import ExperimentService
from .services.live import GridFeed, LiveService
from .services.modes import ModeManager
from .services.simulation import Conflict, InvalidInput, NotFound, SimulationService
from .services.system_monitor import SystemMonitor


class JsonFormatter(logging.Formatter):
    """One JSON object per line — easy to grep locally and to ingest in cloud log viewers."""

    RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                   "logger": record.name, "msg": record.getMessage()}
        payload.update({k: v for k, v in vars(record).items() if k not in self.RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, start_background: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    log = logging.getLogger("carbon_debt.app")

    db = Database(settings.database_url)
    db.create_all()
    sim = SimulationService(db, settings)
    sim.ensure_initialised()
    experiments = ExperimentService(db)

    # Live mode has its own database so live records never mix with simulated ones.
    live_db = Database(settings.live_database_url)
    live_db.create_all()
    live = LiveService(live_db, settings, SystemMonitor(settings.process_poll_seconds), GridFeed(live_db, settings))
    live.ensure_initialised()
    modes = ModeManager(sim, live)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_background:
            sim.start_background()
            live.start_background()
            if modes.get() == "live":
                with live.db.session() as s:
                    resume = live.clock(s).autoplay
                if resume:  # monitoring was on when the backend stopped
                    live.set_autoplay(True)
        log.info("backend started", extra={"environment": settings.environment, "database": db.url.split(":", 1)[0]})
        yield
        sim.stop_background()
        live.stop_background()

    app = FastAPI(
        title="Carbon Debt Computing API",
        version=__version__,
        description="Deadline-aware carbon debt controller: ledger, scheduler, repayment credits, experiments.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        debug=False,
    )
    app.state.settings = settings
    app.state.sim = sim
    app.state.live = live
    app.state.modes = modes
    app.state.experiments = experiments

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api") and not (request.method == "GET" and response.status_code < 400):
            log.info("request", extra={"request_id": request_id, "method": request.method, "path": request.url.path,
                                       "status": response.status_code, "ms": elapsed})
        return response

    @app.exception_handler(NotFound)
    @app.exception_handler(LookupError)
    async def not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValidationError)
    async def invalid(_: Request, exc: ValidationError) -> JSONResponse:
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(InvalidInput)
    async def invalid_input(_: Request, exc: InvalidInput) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    app.include_router(router)

    @app.get("/health", include_in_schema=False)
    def root_health() -> dict[str, str]:
        return {"status": "ok"}

    if settings.static_dir and Path(settings.static_dir, "index.html").exists():
        static = Path(settings.static_dir)
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html")

    return app
# Run with:  uvicorn app.main:create_app --factory

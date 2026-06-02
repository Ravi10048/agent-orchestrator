"""FastAPI entrypoint (LLD 09). `lifespan` wires the whole runtime; `create_app` assembles
the app (CORS, error handlers, REST routers, /ws/monitor). Replaces the scaffold stub.

Concurrency model: CRUD/DB handlers are sync `def` → FastAPI runs them in a worker
threadpool (concurrent, never block the event loop); runtime/LLM/WebSocket handlers are
`async`. Runs execute as background asyncio tasks, so POST /runs returns immediately. Scale
path: more uvicorn workers + Postgres (one env var). See README "Production next-steps".
"""
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.channels import list_channels, make_dispatcher, register_channel
from app.channels.telegram import TelegramChannel
from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging
from app.runtime.run_service import RunService
from app.runtime.scheduler import SchedulerService
from app.seed import run_seed
from app.ws.hub import MonitorHub
from app.ws.monitor import monitor_ws_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub = rs = sched = None
    try:
        # startup wiring is INSIDE the try so a failure partway still triggers cleanup below
        init_db()
        with SessionLocal() as db:
            run_seed(db)  # tools → (agents → templates, once LLD 11 lands) — idempotent

        hub = MonitorHub()
        app.state.hub = hub
        rs = RunService(SessionLocal, hub=hub, max_run_steps=settings.MAX_RUN_STEPS,
                        default_max_visits=settings.DEFAULT_MAX_VISITS, run_timeout_s=settings.RUN_TIMEOUT_S)
        app.state.run_service = rs
        sched = SchedulerService(rs, SessionLocal, default_tz=settings.SCHEDULER_TIMEZONE,
                                 default_grace=settings.SCHEDULER_MISFIRE_GRACE)
        app.state.scheduler = sched

        if settings.TELEGRAM_BOT_TOKEN:  # channel registered only if configured
            ch = TelegramChannel(settings.TELEGRAM_BOT_TOKEN, dispatcher=make_dispatcher(SessionLocal),
                                 poll_timeout=settings.TELEGRAM_POLL_TIMEOUT)
            register_channel(ch)
            await ch.start()

        sched.start()
        sched.load_all_schedules()  # rebuild jobs from DB
        yield
    finally:
        for ch in list_channels():
            with contextlib.suppress(Exception):
                await ch.stop()
        if sched is not None:
            with contextlib.suppress(Exception):
                await sched.shutdown()
        if rs is not None:
            with contextlib.suppress(Exception):
                await rs.shutdown()
        if hub is not None:
            with contextlib.suppress(Exception):
                await hub.close()


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)  # FastAPI's built-in JSON path is fast
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    install_exception_handlers(app)
    app.include_router(api_router)
    app.add_api_websocket_route("/ws/monitor", monitor_ws_endpoint)

    @app.get("/health", tags=["meta"])  # root health for container/ops probes (also at /api/health)
    def _root_health():
        return {"ok": True}

    return app


app = create_app()


if __name__ == "__main__":
    # Convenience for local dev: `python -m app.main`. The canonical run path is the uvicorn
    # CLI against the ASGI app (Dockerfile CMD / `make dev`), which gives --workers/--reload.
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)

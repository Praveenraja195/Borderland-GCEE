import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    ace_spade,
    admin,
    admin_data,
    admin_games,
    admin_scheduler,
    auth,
    demo,
    jack_heart,
    king_diamond,
    leaderboard,
    mindmaze,
    rounds,
    selection,
    sessions,
    teams,
    tiebreak,
)
from app.core.config import settings, validate_production_settings
from app.core.exceptions import register_exception_handlers
from app.db.session import async_session_maker
from app.services import session_service
from app.ws import scoreboard
from app.workers.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("round1.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fix §3.4: fail fast in production with a weak secret
    validate_production_settings()

    # Fix §3.3: only start the scheduler if this process is designated to
    # run it (set RUN_SCHEDULER=true in exactly one worker, or run the
    # standalone python -m app.workers.scheduler process instead).
    if settings.run_scheduler:
        start_scheduler()
        logger.info("Scheduler started in this process (RUN_SCHEDULER=true)")
    else:
        logger.info(
            "Scheduler NOT started in this process (RUN_SCHEDULER not set). "
            "Ensure the standalone scheduler worker is running."
        )

    try:
        async with async_session_maker() as db:
            recovered = await session_service.recover_scheduler_jobs(db)
            if recovered:
                logger.info("Recovered %d orphaned scheduler job(s) on startup", recovered)
    except Exception as exc:
        logger.warning("Could not recover scheduler jobs on startup: %s", exc)
    yield
    if settings.run_scheduler:
        shutdown_scheduler()


# The interactive API docs are a development aid; on a public event server
# they only advertise the surface area, so they are off outside development.
_IS_DEV = settings.environment == "development"

app = FastAPI(
    title="Round 1 Backend",
    description="FastAPI backend for the Round 1 card-game event schema.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _IS_DEV else None,
    redoc_url="/redoc" if _IS_DEV else None,
    openapi_url="/openapi.json" if _IS_DEV else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False if settings.cors_origin_list == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(teams.router, prefix=API_PREFIX)
app.include_router(tiebreak.router, prefix=API_PREFIX)
app.include_router(rounds.router, prefix=API_PREFIX)
app.include_router(selection.router, prefix=API_PREFIX)
app.include_router(sessions.router, prefix=API_PREFIX)
app.include_router(mindmaze.router, prefix=API_PREFIX)
app.include_router(ace_spade.router, prefix=API_PREFIX)
app.include_router(king_diamond.router, prefix=API_PREFIX)
app.include_router(jack_heart.router, prefix=API_PREFIX)
app.include_router(leaderboard.router, prefix=API_PREFIX)
app.include_router(leaderboard.rooms_router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(admin_games.router, prefix=API_PREFIX)
# Spreadsheet in / spreadsheet out: bulk team registration import and the
# Round 2 qualifier export. See app/api/v1/admin_data.py.
app.include_router(admin_data.router, prefix=API_PREFIX)
app.include_router(admin_scheduler.router, prefix=API_PREFIX)
# Demo (practice) rounds — a Redis-only parallel play surface that never
# writes to the DB. See app/services/demo_service.py.
app.include_router(demo.router, prefix=API_PREFIX)

app.include_router(scoreboard.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


import time
from datetime import datetime, timezone

@app.get("/api/v1/health", tags=["meta"])
async def get_health():
    """Liveness for the container health check: the DB and Redis must answer."""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text as _text

    import redis.asyncio as _redis

    from app.db.session import async_session_maker

    problems: dict[str, str] = {}
    try:
        async with async_session_maker() as db:
            await db.execute(_text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        problems["database"] = str(exc)[:200]
    try:
        client = _redis.from_url(settings.redis_url)
        try:
            await client.ping()
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        problems["redis"] = str(exc)[:200]
    if problems:
        return JSONResponse({"status": "degraded", **problems}, status_code=503)
    return {"status": "ok"}


@app.get("/api/v1/time", tags=["meta"])
async def get_server_time():
    now = time.time()
    return {
        "server_time_ms": int(now * 1000),
        "server_time_iso": datetime.now(timezone.utc).isoformat(),
    }


from pathlib import Path
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


if FRONTEND_DIR.exists():
    if (FRONTEND_DIR / "shared").exists():
        app.mount("/shared", NoCacheStaticFiles(directory=FRONTEND_DIR / "shared"), name="shared")
    if (FRONTEND_DIR / "admin-app").exists():
        app.mount("/admin-app", NoCacheStaticFiles(directory=FRONTEND_DIR / "admin-app", html=True), name="admin-app")
    if (FRONTEND_DIR / "team-app").exists():
        app.mount("/team-app", NoCacheStaticFiles(directory=FRONTEND_DIR / "team-app", html=True), name="team-app")

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/", include_in_schema=False)
    async def serve_admin():
        return RedirectResponse(url="/admin-app/")

    @app.get("/team", include_in_schema=False)
    @app.get("/team/", include_in_schema=False)
    async def serve_team():
        return RedirectResponse(url="/team-app/")

    @app.get("/", include_in_schema=False)
    async def serve_root():
        return RedirectResponse(url="/team-app/")

    # Fix §4 (low): scope the catch-all to only what's needed rather than
    # serving the entire frontend/ directory at /.
    app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend_root")

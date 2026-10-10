import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import database_lifecycle, vault
from app.core.db import DatabaseLocked
from app.routers import (
    analysis_router, cases, documents, entities, scoring, export, settings_router, vault_router, sample_router,
    statements,
)
from app.services import queue_processor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("redthread")

# The packaged app's webview origin (Tauri on Windows/macOS/Linux) and the
# Vite dev/preview servers. Nothing else may talk to this backend: without
# this, any web page open in a browser could read the case files from
# 127.0.0.1 while the app is running.
ALLOWED_ORIGINS = [
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
UNLOCKED_PATHS = ("/api/vault", "/api/health")
AUTO_LOCK_CHECK_SECONDS = 30


async def _auto_lock_loop() -> None:
    while True:
        await asyncio.sleep(AUTO_LOCK_CHECK_SECONDS)
        try:
            minutes = vault.auto_lock_minutes() if vault.is_enabled() else 0
            if (minutes and vault.is_unlocked() and not queue_processor.is_busy()
                    and vault.idle_seconds() > minutes * 60):
                database_lifecycle.lock()
                logger.info("Auto-locked after %d idle minutes", minutes)
        except Exception:  # noqa: BLE001 - the timer must never die
            logger.exception("Auto-lock check failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if vault.is_enabled():
        logger.info("Encryption is on: starting locked")
    else:
        database_lifecycle.open_database()
    queue_processor.start_worker()
    auto_lock = asyncio.get_event_loop().create_task(_auto_lock_loop())
    yield
    auto_lock.cancel()


app = FastAPI(title="The Red Thread", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    # Browsers always send Origin on cross-site requests, including form
    # POSTs that CORS alone wouldn't block, so reject unknown origins here.
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    # Defeats DNS-rebinding: a hostile site's requests carry its own Host.
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "Host not allowed"}, status_code=403)

    path = request.url.path
    if path.startswith("/api/") and not path.startswith(UNLOCKED_PATHS):
        if vault.is_locked():
            return JSONResponse({"detail": "locked"}, status_code=423)
        vault.touch()
    return await call_next(request)


# Added after the guard so it wraps it: 403/423 responses still carry CORS
# headers and reach the frontend as readable errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DatabaseLocked)
async def database_locked_handler(request: Request, exc: DatabaseLocked):
    return JSONResponse({"detail": "locked"}, status_code=423)


app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(entities.router)
app.include_router(entities.watchlist_router)
app.include_router(scoring.router)
app.include_router(export.router)
app.include_router(settings_router.router)
app.include_router(vault_router.router)
app.include_router(sample_router.router)
app.include_router(analysis_router.router)
app.include_router(statements.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}

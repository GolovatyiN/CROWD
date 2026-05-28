import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from .database import SessionLocal, get_db
from .routes import anchor_plans, auth, dashboard, donors, placements, stop_list, users

log = logging.getLogger("crowd.heartbeat")

# Neon free tier suspends compute after 5 minutes of inactivity, and waking
# it up costs 1-3 seconds on the first request. We ping every 4 minutes to
# keep it warm — much cheaper than the per-user cold start.
NEON_HEARTBEAT_INTERVAL = 240  # seconds


async def neon_heartbeat() -> None:
    while True:
        try:
            await asyncio.sleep(NEON_HEARTBEAT_INTERVAL)
            await asyncio.to_thread(_ping_db)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 — we want to keep looping no matter what
            log.warning("heartbeat ping failed: %s", exc)


def _ping_db() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(neon_heartbeat())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Crowd", version="0.1.0", lifespan=lifespan)

# Compress all JSON / HTML / CSS / JS payloads. Cheap and big win on slow networks.
app.add_middleware(GZipMiddleware, minimum_size=512)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(donors.router)
app.include_router(anchor_plans.router)
app.include_router(placements.router)
app.include_router(stop_list.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Health endpoint that also touches Postgres so Neon stays warm."""
    db.execute(text("SELECT 1"))
    return {"ok": True}


# --- Static frontend ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


class CachedStaticFiles(StaticFiles):
    """Mostly-immutable assets — JS modules, CSS, fonts. Cache aggressively."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            # 1 day in browser, 1 day on shared cache; static assets rarely change.
            response.headers["Cache-Control"] = "public, max-age=86400, must-revalidate"
        return response


if FRONTEND_DIR.exists():
    app.mount("/static", CachedStaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root_index():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(
                str(index),
                # Always revalidate the entrypoint so users see new builds immediately.
                headers={"Cache-Control": "no-cache"},
            )
        return JSONResponse({"detail": "frontend not built"}, status_code=404)

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        candidate = FRONTEND_DIR / path
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index), headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "not found"}, status_code=404)

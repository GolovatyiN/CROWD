import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from .database import SessionLocal, engine, get_db
from .routes import admin, allocation, anchor_plans, audit, auth, client_portal, clients, dashboard, donors, email_accounts, link_monitor, notifications, placements, stop_list, users

# Identifies this exact process instance so we can cache-bust the entrypoint
# bundle. Changes on every deploy / restart.
BUILD_ID = str(int(time.time()))

log = logging.getLogger("crowd.heartbeat")

# Keep a pooled DB connection warm. TCP keepalives (see database.py) stop the
# private-network proxy from reaping idle connections, but a periodic real
# query is belt-and-suspenders — it also wakes the DB if the platform ever
# suspends it. 120s is comfortably below any idle-reap window.
DB_HEARTBEAT_INTERVAL = 120  # seconds


async def neon_heartbeat() -> None:
    consecutive_failures = 0
    while True:
        try:
            await asyncio.sleep(DB_HEARTBEAT_INTERVAL)
            await asyncio.to_thread(_ping_db)
            consecutive_failures = 0
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            # Back off if the DB has been refusing connections — no point
            # hammering Neon if we're out of quota.
            if consecutive_failures < 3:
                log.warning("heartbeat ping failed: %s", exc)
            elif consecutive_failures == 3:
                log.warning("heartbeat failing repeatedly, backing off to 10 min")
            await asyncio.sleep(min(consecutive_failures * 60, 600))


def _ping_db() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.link_worker import run_link_worker
    tasks = [
        asyncio.create_task(neon_heartbeat()),
        asyncio.create_task(run_link_worker()),  # ready-link verification queue
    ]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
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
app.include_router(audit.router)
app.include_router(email_accounts.router)
app.include_router(admin.router)
app.include_router(clients.router)
app.include_router(client_portal.router)
app.include_router(link_monitor.router)
app.include_router(notifications.router)
app.include_router(allocation.router)


@app.get("/api/health")
def health():
    """Liveness probe — must succeed even if the database is down.

    Railway uses this to decide whether a deploy succeeded. If we couple it
    to DB connectivity, a temporary DB outage (Neon quota, restart, network
    blip) blocks every future deploy too — including the deploy that would
    fix the issue. Keep the liveness check pure.
    """
    return {"ok": True}


@app.get("/api/health/db")
def health_db(db: Session = Depends(get_db)):
    """Optional deep check — pokes Postgres and reports round-trip timing plus
    pool status. Use this for monitoring / perf debugging, not for the deploy
    gate. Exposes no secrets (just timings and pool counts)."""
    try:
        t0 = time.perf_counter()
        db.execute(text("SELECT 1"))
        first_ms = round((time.perf_counter() - t0) * 1000, 1)
        # Second query reuses the now-checked-out connection — isolates pure
        # query latency from any connect / pre-ping cost on the first hit.
        t1 = time.perf_counter()
        db.execute(text("SELECT 1"))
        second_ms = round((time.perf_counter() - t1) * 1000, 1)
        return {
            "ok": True,
            "db": "up",
            "query_ms": {"first": first_ms, "second": second_ms},
            "pool": engine.pool.status(),
        }
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "db": "down", "error": str(e)[:200]}, status_code=503)


@app.get("/api/health/schema")
def health_schema(db: Session = Depends(get_db)):
    """Non-secret schema snapshot: current alembic revision + table names. Lets us
    confirm migrations landed on prod without logging in. Exposes no data."""
    from sqlalchemy import inspect as sa_inspect
    try:
        version = None
        try:
            version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "alembic": version, "tables": sorted(sa_inspect(engine).get_table_names())}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=503)


# --- Static frontend ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


class CachedStaticFiles(StaticFiles):
    """Always revalidate with the server — Starlette ships Last-Modified, so the
    server returns 304 Not Modified for unchanged files. Bandwidth-cheap, and
    avoids the "user is stuck on yesterday's JS after a deploy" trap.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-cache"
        return response


def _render_index() -> HTMLResponse:
    """Read the SPA shell and rewrite every relative import to include a
    `?v=BUILD_ID` query string. That forces browsers to re-fetch JS/CSS on
    every deploy without giving up the Last-Modified 304 round-trip for
    unchanged static files.
    """
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "frontend not built"}, status_code=404)
    html = index.read_text(encoding="utf-8")
    # Append ?v=BUILD_ID to <script src=...> and <link href=...> for /static/ assets.
    def _stamp(match):
        attr, url = match.group(1), match.group(2)
        sep = "&" if "?" in url else "?"
        return f'{attr}="{url}{sep}v={BUILD_ID}"'
    html = re.sub(r'(src|href)="(/static/[^"#?]+(?:\?[^"]*)?)"', _stamp, html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


if FRONTEND_DIR.exists():
    app.mount("/static", CachedStaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root_index():
        return _render_index()

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        candidate = FRONTEND_DIR / path
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        return _render_index()

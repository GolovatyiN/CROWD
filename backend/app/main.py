from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from .database import get_db
from .routes import anchor_plans, auth, dashboard, donors, placements, stop_list, users

app = FastAPI(title="Crowd", version="0.1.0")

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

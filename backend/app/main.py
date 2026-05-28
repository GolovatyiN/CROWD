from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .routes import anchor_plans, auth, dashboard, donors, placements, stop_list, users

app = FastAPI(title="Crowd", version="0.1.0")

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
def health():
    return {"ok": True}


# --- Static frontend ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root_index():
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"detail": "frontend not built"}, status_code=404)

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        # Let the API 404 itself for unknown /api routes
        candidate = FRONTEND_DIR / path
        if candidate.exists() and candidate.is_file():
            return FileResponse(str(candidate))
        index = FRONTEND_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"detail": "not found"}, status_code=404)

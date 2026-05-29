FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for psycopg2 and pandas wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# Copy backend code and the frontend (FastAPI serves it as static).
COPY backend /app/backend
COPY frontend /app/frontend

WORKDIR /app/backend

EXPOSE 8000

# Railway / Render inject $PORT; default to 8000 for local.
# Migrations and seed are best-effort: if the database is temporarily
# unreachable (e.g. provider quota exceeded), still start the web process so
# the deploy can succeed. Once DB connectivity is restored the next deploy
# will run them. Uvicorn itself must always run — that's what the platform
# health-checks.
CMD ["sh", "-c", "(alembic upgrade head || echo 'WARNING: alembic upgrade failed, continuing') && (python -m app.seed || echo 'WARNING: seed failed, continuing') && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

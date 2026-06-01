from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from .config import settings


def _normalize_url(url: str) -> str:
    """Neon, Heroku & co. hand back `postgres://...` — SQLAlchemy 2.x wants
    the explicit driver prefix `postgresql+psycopg2://`.
    """
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = _normalize_url(settings.database_url)

if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine_kwargs = {"connect_args": connect_args}
else:
    # Pooling tuned to keep connections warm and avoid frequent reconnects —
    # establishing a fresh Postgres connection (TCP + TLS + auth) is the most
    # likely cause of multi-second first-request latency.
    #   pool_pre_ping  — cheaply validate a connection on checkout; drops dead
    #                    ones (e.g. after a Neon suspend) without erroring.
    #   pool_recycle   — was 300s, which forced a reconnect every 5 minutes.
    #                    Raised to 30 min so warm connections are reused for
    #                    much longer; pre_ping still catches any that died.
    engine_kwargs = {
        "pool_size": 10,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Used only for local dev / first-run convenience. Production uses Alembic."""
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

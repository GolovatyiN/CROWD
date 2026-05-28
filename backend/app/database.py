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
    # Tuned for serverless Postgres (Neon) — small pool, recycle before idle disconnect.
    engine_kwargs = {
        "pool_size": 5,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_recycle": 300,
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

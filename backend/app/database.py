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
    # establishing a fresh Postgres connection (TCP + TLS + SCRAM auth) is the
    # single biggest source of latency here: a cold one costs ~3s, a warm-ish
    # reconnect ~0.6s, while a query on a live connection is ~1ms.
    #
    # Railway's private network (postgres.railway.internal) silently drops idle
    # TCP connections, so without keepalives every pooled connection dies
    # between requests and pre_ping has to dial a brand-new one each time — that
    # was making a single indexed SELECT take ~0.6s. TCP keepalives keep the
    # socket alive through the overlay so the SAME connection is reused warm.
    #   keepalives*     — probe every 10s after 30s idle; keeps the connection
    #                     registered in the proxy so it isn't reaped.
    #   pool_pre_ping   — still validate on checkout; cheap (~1ms) on a warm
    #                     connection, and silently replaces any that did die.
    #   pool_recycle    — recycle after 30 min (well under most server limits).
    #   connect_timeout — fail fast instead of hanging if the DB is unreachable.
    connect_args = {
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
    engine_kwargs = {
        "pool_size": 10,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "connect_args": connect_args,
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

"""Disk retention — keep append-only history from silently refilling the volume.

The runaway tables are *history*: link_check_results grows by one row every time
a placement's ready-link is re-verified, and notifications / import_logs /
audit_logs accumulate over time. The current verification STATE lives in
link_checks (one row per placement), so trimming link_check_results never loses
"where a link stands now" — only old snapshots.

Two rules for the check history, whichever removes more:
  * age   — drop rows older than ``link_check_results_retention_days``;
  * count — keep at most ``link_check_results_keep_per_placement`` newest per placement.

Everything deletes in bounded batches so we never hold a long lock or bloat the
WAL on a large table. Runs daily from a background task; also exposed to admins
as a manual "prune now" + a storage report.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import AuditLog, ImportLog, LinkCheckResult, Notification, utcnow

log = logging.getLogger("crowd.maintenance")

# Tables surfaced in the storage report (row counts everywhere; byte sizes on
# Postgres). Order = rough "worth watching" priority.
_REPORT_TABLES = [
    "link_check_results", "link_checks", "stop_list_entries", "placements",
    "notifications", "audit_logs", "import_logs", "anchor_plan_items", "donors",
]


def _prune_older_than(db: Session, model, ts_col, cutoff, batch: int) -> int:
    """Delete rows with ``ts_col < cutoff`` in batches. Portable (SQLite + PG):
    a LIMIT on DELETE isn't standard, so select a batch of ids then delete them."""
    total = 0
    while True:
        ids = db.execute(select(model.id).where(ts_col < cutoff).limit(batch)).scalars().all()
        if not ids:
            break
        db.execute(delete(model).where(model.id.in_(ids)))
        db.commit()
        total += len(ids)
        if len(ids) < batch:
            break
    return total


def _cap_per_placement(db: Session, keep: int, batch: int) -> int:
    """Keep only the ``keep`` most-recent check results per placement; delete the
    rest in batches. row_number() + ``DELETE ... WHERE id IN (SELECT … LIMIT)``
    works on both SQLite (>=3.25) and Postgres."""
    if not keep or keep <= 0:
        return 0
    sql = text(
        "DELETE FROM link_check_results WHERE id IN ("
        "  SELECT id FROM ("
        "    SELECT id, row_number() OVER ("
        "      PARTITION BY placement_id ORDER BY checked_at DESC, id DESC"
        "    ) AS rn FROM link_check_results"
        "  ) s WHERE s.rn > :keep LIMIT :batch"
        ")"
    )
    total = 0
    while True:
        res = db.execute(sql, {"keep": keep, "batch": batch})
        db.commit()
        n = res.rowcount or 0
        total += n
        if n < batch:
            break
    return total


def run_retention(db: Session | None = None) -> dict:
    """Run every retention rule once. Returns per-table deleted counts (a value
    of -1 means that table's prune errored and was skipped — the rest still run)."""
    own = db is None
    if own:
        db = SessionLocal()
    now = utcnow()
    batch = max(100, settings.retention_delete_batch)
    deleted: dict[str, int] = {}

    # link_check_results: age rule, then per-placement cap.
    time_tables = [
        (LinkCheckResult, LinkCheckResult.checked_at, settings.link_check_results_retention_days, "link_check_results"),
        (Notification, Notification.created_at, settings.notifications_retention_days, "notifications"),
        (ImportLog, ImportLog.created_at, settings.import_logs_retention_days, "import_logs"),
        (AuditLog, AuditLog.created_at, settings.audit_logs_retention_days, "audit_logs"),
    ]
    try:
        for model, ts_col, days, name in time_tables:
            if not days or days <= 0:
                continue  # rule disabled
            cutoff = now - timedelta(days=days)
            try:
                deleted[name] = _prune_older_than(db, model, ts_col, cutoff, batch)
            except Exception as e:  # noqa: BLE001 — one bad table shouldn't abort the rest
                log.warning("retention: prune %s failed: %s", name, e)
                db.rollback()
                deleted[name] = -1

        try:
            capped = _cap_per_placement(db, settings.link_check_results_keep_per_placement, batch)
            deleted["link_check_results_capped"] = capped
        except Exception as e:  # noqa: BLE001
            log.warning("retention: per-placement cap failed: %s", e)
            db.rollback()
            deleted["link_check_results_capped"] = -1
    finally:
        if own:
            db.close()

    log.info("retention pass: %s", deleted)
    return deleted


def storage_report(db: Session) -> dict:
    """Row counts for the big tables (+ byte sizes and total DB size on Postgres),
    so an admin can see what's using the volume before/after a prune."""
    counts: dict[str, int | None] = {}
    for t in _REPORT_TABLES:
        try:
            counts[t] = db.execute(text(f"SELECT count(*) FROM {t}")).scalar()  # table names are constants
        except Exception:  # noqa: BLE001
            counts[t] = None

    dialect = db.bind.dialect.name if db.bind else ""
    table_bytes: dict[str, int] = {}
    db_bytes = None
    if dialect == "postgresql":
        try:
            rows = db.execute(text(
                "SELECT c.relname, pg_total_relation_size(c.oid) AS bytes "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' "
                "ORDER BY bytes DESC"
            )).all()
            table_bytes = {r[0]: int(r[1]) for r in rows}
            db_bytes = int(db.execute(text("SELECT pg_database_size(current_database())")).scalar() or 0)
        except Exception as e:  # noqa: BLE001
            log.warning("storage_report: pg sizes failed: %s", e)

    return {
        "dialect": dialect,
        "counts": counts,
        "table_bytes": table_bytes,
        "db_bytes": db_bytes,
        "retention": {
            "enabled": settings.retention_enabled,
            "run_hours": settings.retention_run_hours,
            "link_check_results_retention_days": settings.link_check_results_retention_days,
            "link_check_results_keep_per_placement": settings.link_check_results_keep_per_placement,
            "notifications_retention_days": settings.notifications_retention_days,
            "import_logs_retention_days": settings.import_logs_retention_days,
            "audit_logs_retention_days": settings.audit_logs_retention_days,
        },
    }


async def run_retention_worker() -> None:
    """Background task: run retention once, then every ``retention_run_hours``."""
    await asyncio.sleep(max(0, settings.retention_startup_delay_sec))
    while True:
        try:
            if settings.retention_enabled:
                await asyncio.to_thread(run_retention)
        except asyncio.CancelledError:
            log.info("retention worker stopped")
            return
        except Exception as e:  # noqa: BLE001
            log.warning("retention worker pass failed: %s", e)
        await asyncio.sleep(max(3600, settings.retention_run_hours * 3600))

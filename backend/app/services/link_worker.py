"""Background worker that drains the link_checks queue.

Runs as an asyncio task in the app lifespan (same pattern as the DB heartbeat).
Each pass claims a batch of due checks (locking them), then verifies them with a
concurrency cap and a per-donor-domain politeness delay. Transient failures are
retried with exponential backoff up to a cap, then flagged manual. check_placement
is synchronous (blocking httpx), so it's offloaded to a thread.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from sqlalchemy import func, or_

from ..config import settings
from ..database import SessionLocal
from ..models import LinkCheck, Placement, utcnow
from . import link_checker as lch
from .url_match import domain_of

log = logging.getLogger("crowd.linkworker")

LOCK_TTL_MIN = 10  # a claimed-but-unfinished check is retryable after this

# Per-domain politeness: next allowed start time (monotonic) per donor domain.
_domain_next: dict[str, float] = {}
_domain_lock = asyncio.Lock()


def claim_due_batch(limit: int) -> list[dict]:
    """Atomically claim up to `limit` due checks: lock them + mark 'checking'.
    Returns lightweight dicts so callers don't hold ORM objects across threads."""
    db = SessionLocal()
    try:
        now = utcnow()
        lock_cutoff = now - timedelta(minutes=LOCK_TTL_MIN)
        rows = (
            db.query(LinkCheck)
            .filter(
                LinkCheck.next_check_at.isnot(None),
                LinkCheck.next_check_at <= now,
                or_(LinkCheck.locked_at.is_(None), LinkCheck.locked_at < lock_cutoff),
            )
            .order_by(LinkCheck.priority.desc(), LinkCheck.next_check_at.asc())
            .limit(limit).all()
        )
        claimed: list[dict] = []
        for lc in rows:
            lc.locked_at = now
            lc.status = lch.CHECKING
            pl = db.get(Placement, lc.placement_id)
            claimed.append({
                "placement_id": lc.placement_id,
                "domain": domain_of(pl.result_url) if (pl and pl.result_url) else "",
            })
        db.commit()
        return claimed
    finally:
        db.close()


def _check_one(placement_id: int) -> str | None:
    """Verify one placement in its own session. Applies transient backoff."""
    db = SessionLocal()
    try:
        pl = db.get(Placement, placement_id)
        lc = db.query(LinkCheck).filter(LinkCheck.placement_id == placement_id).first()
        if not pl:
            if lc:
                db.delete(lc)
                db.commit()
            return None
        lch.check_placement(db, pl, recheck_hours=settings.link_check_interval_hours)
        lc = db.query(LinkCheck).filter(LinkCheck.placement_id == placement_id).first()
        status = lc.status if lc else None
        if lc and lc.status in lch.TRANSIENT:
            if (lc.attempts or 0) >= settings.link_check_max_attempts:
                lc.status = lch.MANUAL_REQUIRED
                status = lc.status
            else:
                lc.next_check_at = utcnow() + timedelta(minutes=min(2 ** (lc.attempts or 1), 60))
        db.commit()
        return status
    except Exception as e:  # noqa: BLE001
        log.warning("link check failed for placement %s: %s", placement_id, e)
        db.rollback()
        try:  # release the lock so it retries next pass
            lc = db.query(LinkCheck).filter(LinkCheck.placement_id == placement_id).first()
            if lc:
                lc.locked_at = None
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return None
    finally:
        db.close()


def run_due_checks(limit: int | None = None) -> dict:
    """Synchronous single pass (used by the admin 'run now' endpoint / background task)."""
    limit = limit or settings.link_check_batch
    batch = claim_due_batch(limit)
    counts: dict[str, int] = {}
    for item in batch:
        st = _check_one(item["placement_id"])
        if st:
            counts[st] = counts.get(st, 0) + 1
    return {"processed": len(batch), "by_status": counts}


async def _process_async(item: dict, sem: asyncio.Semaphore) -> None:
    async with sem:
        dom = item.get("domain") or ""
        if dom:
            # Stagger same-domain requests by the politeness delay; other domains
            # aren't blocked (the lock is held only to reserve a time slot).
            async with _domain_lock:
                now = time.monotonic()
                start_at = max(now, _domain_next.get(dom, 0.0))
                _domain_next[dom] = start_at + settings.link_check_domain_delay_sec
            wait = start_at - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
        await asyncio.to_thread(_check_one, item["placement_id"])


async def run_link_worker() -> None:
    log.info("link worker: interval=%sh conc=%s poll=%ss",
             settings.link_check_interval_hours, settings.link_check_concurrency, settings.link_check_poll_sec)
    while True:
        try:
            await asyncio.sleep(settings.link_check_poll_sec)
            if not settings.link_check_enabled:
                continue
            batch = await asyncio.to_thread(claim_due_batch, settings.link_check_batch)
            if not batch:
                continue
            sem = asyncio.Semaphore(max(1, settings.link_check_concurrency))
            await asyncio.gather(*[_process_async(it, sem) for it in batch])
        except asyncio.CancelledError:
            log.info("link worker stopped")
            return
        except Exception as e:  # noqa: BLE001
            log.warning("link worker pass failed: %s", e)
            await asyncio.sleep(10)


def queue_status(db) -> dict:
    rows = db.query(LinkCheck.status, func.count(LinkCheck.id)).group_by(LinkCheck.status).all()
    now = utcnow()
    due = db.query(func.count(LinkCheck.id)).filter(
        LinkCheck.next_check_at.isnot(None), LinkCheck.next_check_at <= now
    ).scalar() or 0
    return {
        "by_status": {s: c for s, c in rows},
        "total": sum(c for _s, c in rows),
        "due_now": due,
        "enabled": settings.link_check_enabled,
        "interval_hours": settings.link_check_interval_hours,
    }

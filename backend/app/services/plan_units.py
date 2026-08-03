"""Aggregate anchor-plan units ("Формат 2": анкор + количество).

A *bucket* item (``required_count > 1``) represents N planned placements of the
same anchor/target without materialising N identical rows. Work is created by
lazily *spawning* child unit-items (``parent_item_id`` set, ``required_count=1``)
in batches; each child then flows through the normal task pipeline (auto-match →
assign → take → mark-placed). Counters on the bucket track progress:

    remaining = required_count - reserved_count - used_count

    reserved_count  units spawned and in-flight (not yet placed, not released)
    used_count      units successfully placed

Concurrency: :func:`spawn_units`, :func:`consume_unit` and :func:`release_unit`
lock the bucket row (``SELECT ... FOR UPDATE`` on PostgreSQL; a no-op on SQLite,
which is single-writer anyway) so two employees/managers can't reserve the same
remaining slot twice.

Standalone Format-1 items (``required_count == 1``, no parent) are untouched by
this module except that placing one sets ``used_count = 1`` so plan-level
aggregation (``SUM(used_count)`` over top-level items) stays uniform.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ..models import AnchorPlanItem

# Bucket lifecycle statuses (Формат 2). Standalone items keep the classic
# new/donor_selected/assigned/in_progress/placed/problem flow.
STATUS_AVAILABLE = "available"          # доступно
STATUS_PARTIAL = "partially_used"       # частично использовано
STATUS_EXHAUSTED = "exhausted"          # исчерпано (всё зарезервировано/в работе)
STATUS_COMPLETED = "completed"          # выполнено (всё размещено)
STATUS_PAUSED = "paused"                # приостановлено (ручная остановка)
STATUS_ARCHIVED = "archived"            # архивировано
STATUS_IMPORT_ERROR = "import_error"    # ошибка импорта

_HOLD_STATUSES = {STATUS_PAUSED, STATUS_ARCHIVED, STATUS_IMPORT_ERROR}


def is_bucket(item: AnchorPlanItem) -> bool:
    """A bucket is a quantity item that spawns children (required_count > 1)."""
    return (item.required_count or 1) > 1


def is_child(item: AnchorPlanItem) -> bool:
    return item.parent_item_id is not None


def remaining(item: AnchorPlanItem) -> int:
    req = item.required_count or 1
    return max(0, req - (item.reserved_count or 0) - (item.used_count or 0))


def derive_status(item: AnchorPlanItem) -> str:
    """Bucket status from its counters. Manual holds (paused/archived/import_error)
    are preserved — a manager's pause must survive a placement update."""
    if item.status in _HOLD_STATUSES:
        return item.status
    req = item.required_count or 1
    used = item.used_count or 0
    res = item.reserved_count or 0
    if used >= req:
        return STATUS_COMPLETED
    if used + res >= req:
        return STATUS_EXHAUSTED
    if used + res > 0:
        return STATUS_PARTIAL
    return STATUS_AVAILABLE


def _lock(db: Session, item_id: int) -> Optional[AnchorPlanItem]:
    """Re-fetch a row with a write lock (FOR UPDATE on PG, no-op on SQLite)."""
    return (
        db.query(AnchorPlanItem)
        .filter(AnchorPlanItem.id == item_id)
        .with_for_update()
        .first()
    )


def spawn_units(
    db: Session,
    bucket: AnchorPlanItem,
    count: int,
    *,
    do_auto_match: bool = True,
) -> list[AnchorPlanItem]:
    """Reserve up to ``count`` units from a bucket and create child unit-items.

    Returns the created children (may be fewer than ``count`` if the bucket ran
    out of remaining slots). Each child copies the bucket's targeting fields and
    enters the normal task flow. When ``do_auto_match`` is set, a distinct donor
    is picked per child right away (best-effort — children without an available
    donor stay ``new`` and can be matched later). Does NOT commit.
    """
    if count <= 0:
        return []
    # Lazy import avoids a circular dependency (matcher imports models only).
    from .matcher import find_best_donor

    locked = _lock(db, bucket.id)
    if locked is None:
        return []
    slots = min(int(count), remaining(locked))
    if slots <= 0:
        return []

    children: list[AnchorPlanItem] = []
    chosen_donor_ids: set[int] = set()
    for _ in range(slots):
        child = AnchorPlanItem(
            anchor_plan_id=locked.anchor_plan_id,
            parent_item_id=locked.id,
            target_url=locked.target_url,
            target_domain=locked.target_domain,
            anchor_text=locked.anchor_text,
            anchor_type=locked.anchor_type,
            geo=locked.geo,
            language=locked.language,
            required_link_type=locked.required_link_type,
            requirements=locked.requirements,
            priority=locked.priority,
            kind=locked.kind,
            client_project_id=locked.client_project_id,
            required_count=1,
            status="new",
        )
        if do_auto_match:
            donor = find_best_donor(db, child, exclude_donor_ids=chosen_donor_ids)
            if donor is not None:
                child.selected_donor_id = donor.id
                child.status = "donor_selected"
                chosen_donor_ids.add(donor.id)
        db.add(child)
        children.append(child)

    locked.reserved_count = (locked.reserved_count or 0) + slots
    locked.status = derive_status(locked)
    db.flush()
    return children


def consume_unit(db: Session, item: AnchorPlanItem) -> None:
    """A unit was successfully placed. For a bucket child: reserved-- , used++
    on the parent. For a standalone item: mark its own used_count=1 (uniform
    aggregation). Idempotency is the caller's responsibility (guard on prior
    status). Does NOT commit."""
    if item.parent_item_id:
        parent = _lock(db, item.parent_item_id)
        if parent is not None:
            parent.reserved_count = max(0, (parent.reserved_count or 0) - 1)
            parent.used_count = (parent.used_count or 0) + 1
            parent.status = derive_status(parent)
    else:
        item.used_count = 1


def release_unit(db: Session, item: AnchorPlanItem) -> None:
    """A unit's attempt failed / was cancelled — return its reservation to the
    bucket's remaining pool (reserved--). The child row itself stays as a
    problem/cancelled record but no longer holds a slot. No-op for standalone
    items. Does NOT commit."""
    if item.parent_item_id:
        parent = _lock(db, item.parent_item_id)
        if parent is not None:
            parent.reserved_count = max(0, (parent.reserved_count or 0) - 1)
            parent.status = derive_status(parent)


def revert_unit(db: Session, item: AnchorPlanItem, prev_status: str) -> None:
    """Item left a counted state (moved to problem/cancelled). Undo whatever it
    contributed: a previously ``placed`` unit gives back a used slot; an
    in-flight unit gives back its reservation. Does NOT commit."""
    if prev_status == "placed":
        if item.parent_item_id:
            parent = _lock(db, item.parent_item_id)
            if parent is not None:
                parent.used_count = max(0, (parent.used_count or 0) - 1)
                parent.status = derive_status(parent)
        else:
            item.used_count = 0
    else:
        release_unit(db, item)


def bucket_progress(item: AnchorPlanItem) -> dict:
    """Progress payload for a bucket (or any item, uniformly)."""
    req = item.required_count or 1
    used = item.used_count or 0
    res = item.reserved_count or 0
    return {
        "required": req,
        "reserved": res,
        "used": used,
        "remaining": max(0, req - res - used),
        "percent": round(used * 100 / req, 1) if req else 0.0,
        "status": item.status,
    }

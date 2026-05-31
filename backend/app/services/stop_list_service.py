"""Stop-list write side: triggered when a placement is marked placed."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    Placement,
    StopListEntry,
)
from .matcher import extract_domain


def register_placement(
    db: Session,
    placement: Placement,
) -> StopListEntry | None:
    """Idempotently add a stop-list entry for a successful placement.

    The dedup key is the ANCHOR (target_url + anchor_text) + donor_url, so the
    same donor can legitimately appear once per anchor — including different
    anchors that share a target_url.
    """
    if not placement.target_url or not placement.donor_url:
        return None
    existing = db.query(StopListEntry).filter(
        StopListEntry.target_url == placement.target_url,
        StopListEntry.anchor_text == (placement.anchor_text or ""),
        StopListEntry.donor_url == placement.donor_url,
    ).first()
    if existing:
        return existing

    plan_name = ""
    if placement.anchor_plan_item_id:
        item = db.get(AnchorPlanItem, placement.anchor_plan_item_id)
        if item:
            plan = db.get(AnchorPlan, item.anchor_plan_id)
            if plan:
                plan_name = plan.plan_name

    entry = StopListEntry(
        target_url=placement.target_url,
        target_domain=placement.target_domain or extract_domain(placement.target_url),
        donor_id=placement.donor_id,
        donor_url=placement.donor_url,
        anchor_plan_item_id=placement.anchor_plan_item_id,
        placed_by=placement.employee_id,
        placed_at=placement.placed_at or datetime.utcnow(),
        result_url=placement.result_url,
        anchor_text=placement.anchor_text,
        account_username=placement.account_username,
        login_email=placement.login_email,
        source_anchor_plan=plan_name,
        comment=placement.comment,
    )
    db.add(entry)
    db.flush()
    return entry

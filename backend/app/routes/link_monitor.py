"""Link-monitor: aggregate view over link_checks joined with placements.

Internal only (require_staff). Powers the control/analytics page: survival %,
status breakdown, and a filtered list of every checked placement.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import require_staff
from ..database import get_db
from ..models import LinkCheck, Placement, User
from ..services import link_checker as lch
from ..services.matcher import extract_domain
from ..utils import iso_utc

router = APIRouter(prefix="/link-monitor", tags=["link-monitor"])


def _filtered(q, kind, status, is_dofollow, client_project_id, employee_id, search, date_from, date_to):
    if kind in ("internal", "client"):
        q = q.filter(LinkCheck.kind == kind)
    if status:
        q = q.filter(LinkCheck.status == status)
    if is_dofollow is not None:
        q = q.filter(LinkCheck.is_dofollow.is_(is_dofollow))
    if client_project_id is not None:
        q = q.filter(Placement.client_project_id == client_project_id)
    if employee_id is not None:
        q = q.filter(Placement.employee_id == employee_id)
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(or_(func.lower(Placement.target_url).like(like), func.lower(Placement.donor_url).like(like)))
    if date_from:
        try:
            q = q.filter(Placement.placed_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(Placement.placed_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    return q


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
    kind: Optional[str] = None,
    status: Optional[str] = None,
    is_dofollow: Optional[bool] = None,
    client_project_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    base = db.query(LinkCheck).join(Placement, LinkCheck.placement_id == Placement.id)
    base = _filtered(base, kind, status, is_dofollow, client_project_id, employee_id, search, date_from, date_to)
    rows = base.with_entities(LinkCheck.status, func.count(LinkCheck.id)).group_by(LinkCheck.status).all()
    by = {s: c for s, c in rows}
    total = sum(by.values())
    waiting = by.get(lch.PENDING, 0) + by.get(lch.CHECKING, 0)
    checked = total - waiting
    found = by.get(lch.FOUND, 0)
    last = base.with_entities(func.max(LinkCheck.last_checked_at)).scalar()
    return {
        "total": total,
        "by_status": by,
        "checked": checked,
        "found": found,
        "removed": by.get(lch.NOT_FOUND, 0),
        "wrong_url": by.get(lch.WRONG_URL, 0),
        "anchor_changed": by.get(lch.WRONG_ANCHOR, 0) + by.get(lch.ANCHOR_CHANGED, 0),
        "unavailable": by.get(lch.PAGE_UNAVAILABLE, 0),
        "redirect": by.get(lch.REDIRECT, 0),
        "waiting": waiting,
        "temporary_error": by.get(lch.TEMPORARY_ERROR, 0) + by.get(lch.CHECK_ERROR, 0),
        "manual": by.get(lch.MANUAL_REQUIRED, 0),
        "survival_pct": round(found / checked * 100, 1) if checked else 0.0,
        "last_checked_at": iso_utc(last),
    }


@router.get("/items")
def items(
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
    kind: Optional[str] = None,
    status: Optional[str] = None,
    is_dofollow: Optional[bool] = None,
    client_project_id: Optional[int] = None,
    employee_id: Optional[int] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    base = db.query(LinkCheck, Placement).join(Placement, LinkCheck.placement_id == Placement.id)
    base = _filtered(base, kind, status, is_dofollow, client_project_id, employee_id, search, date_from, date_to)
    total = base.count()
    rows = base.order_by(LinkCheck.last_checked_at.desc()).offset(offset).limit(min(limit, 500)).all()
    out = []
    for lc_row, pl in rows:
        out.append({
            "placement_id": pl.id,
            "target_url": pl.target_url,
            "donor_domain": extract_domain(pl.donor_url),
            "anchor_text": pl.anchor_text,
            "found_anchor": lc_row.found_anchor,
            "result_url": pl.result_url,
            "status": lc_row.status,
            "is_dofollow": lc_row.is_dofollow,
            "http_status": lc_row.http_status,
            "kind": lc_row.kind,
            "employee_id": pl.employee_id,
            "last_checked_at": iso_utc(lc_row.last_checked_at),
            "next_check_at": iso_utc(lc_row.next_check_at),
        })
    return {"total": total, "items": out}

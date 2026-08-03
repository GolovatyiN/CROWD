"""Work distribution: internal/client ratio + daily/monthly targets + auto-assign.

Employee setting overrides the global one. Auto-assign pulls matched-but-unassigned
items (donor already picked, so all geo/language/stop-list/donor-availability
constraints are already satisfied) split by the ratio, filling any shortfall from
the other direction and reporting the deviation.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AllocationSetting, AnchorPlanItem, Placement

DEFAULT = {"internal_pct": 50, "client_pct": 50, "daily_target": 0, "monthly_target": 0}


def get_effective(db: Session, user_id: Optional[int]) -> dict:
    """Employee override if present, else global, else built-in default."""
    if user_id:
        emp = (db.query(AllocationSetting)
               .filter(AllocationSetting.scope == "employee", AllocationSetting.user_id == user_id).first())
        if emp:
            return {"internal_pct": emp.internal_pct, "client_pct": emp.client_pct,
                    "daily_target": emp.daily_target, "monthly_target": emp.monthly_target, "source": "employee"}
    glob = db.query(AllocationSetting).filter(AllocationSetting.scope == "global").first()
    if glob:
        return {"internal_pct": glob.internal_pct, "client_pct": glob.client_pct,
                "daily_target": glob.daily_target, "monthly_target": glob.monthly_target, "source": "global"}
    return {**DEFAULT, "source": "default"}


def upsert(db: Session, *, scope: str, user_id: Optional[int], internal_pct: int,
           client_pct: int, daily_target: int, monthly_target: int, updated_by: Optional[int]) -> AllocationSetting:
    q = db.query(AllocationSetting).filter(AllocationSetting.scope == scope)
    q = q.filter(AllocationSetting.user_id == user_id) if scope == "employee" else q.filter(AllocationSetting.user_id.is_(None))
    row = q.first()
    if not row:
        row = AllocationSetting(scope=scope, user_id=user_id if scope == "employee" else None)
        db.add(row)
    row.internal_pct = max(0, min(100, internal_pct))
    row.client_pct = max(0, min(100, client_pct))
    row.daily_target = max(0, daily_target)
    row.monthly_target = max(0, monthly_target)
    row.updated_by = updated_by
    db.flush()
    return row


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day)
    return start, start + timedelta(days=1)


def _done_counts(db: Session, user_id: int, start: datetime, end: datetime) -> tuple[int, int]:
    rows = (db.query(Placement.kind, func.count(Placement.id))
            .filter(Placement.employee_id == user_id, Placement.status.in_(["placed", "done"]),
                    Placement.placed_at >= start, Placement.placed_at < end)
            .group_by(Placement.kind).all())
    d = {k: c for k, c in rows}
    return d.get("internal", 0), d.get("client", 0)


def plan_vs_fact(db: Session, user_id: int, day: date) -> dict:
    eff = get_effective(db, user_id)
    start, end = _day_bounds(day)
    di, dc = _done_counts(db, user_id, start, end)
    target = eff["daily_target"]
    pi = round(target * eff["internal_pct"] / 100) if target else 0
    pc = target - pi if target else 0
    total = di + dc
    deviation = None
    if total:
        actual_internal_pct = round(di / total * 100)
        deviation = actual_internal_pct - eff["internal_pct"]  # +ve = skewed toward internal
    return {
        "user_id": user_id, "date": str(day), **eff,
        "planned_internal": pi, "planned_client": pc, "planned_total": target,
        "done_internal": di, "done_client": dc, "done_total": total,
        "deviation_pct": deviation,
    }


def _take(db: Session, kind: str, n: int, offset: int = 0) -> list[AnchorPlanItem]:
    if n <= 0:
        return []
    return (db.query(AnchorPlanItem)
            .filter(AnchorPlanItem.assigned_to.is_(None),
                    AnchorPlanItem.selected_donor_id.isnot(None),
                    AnchorPlanItem.kind == kind,
                    AnchorPlanItem.status.in_(["new", "donor_selected"]))
            .order_by(AnchorPlanItem.id.asc()).offset(offset).limit(n).all())


def auto_assign(db: Session, user_id: int, count: Optional[int] = None) -> dict:
    """Assign up to `count` matched items to the user, split by the ratio,
    filling shortfall from the other direction; records the deviation."""
    eff = get_effective(db, user_id)
    count = count or eff["daily_target"]
    if not count or count <= 0:
        return {"assigned": 0, "internal": 0, "client": 0, "note": "Не задан объём (count или дневной план)"}

    want_int = round(count * eff["internal_pct"] / 100)
    want_cli = count - want_int
    internal = _take(db, "internal", want_int)
    client = _take(db, "client", want_cli)
    # Top up from the other direction if one side is short of items.
    shortfall = count - len(internal) - len(client)
    if shortfall > 0:
        client += _take(db, "client", shortfall, offset=len(client))
    shortfall = count - len(internal) - len(client)
    if shortfall > 0:
        internal += _take(db, "internal", shortfall, offset=len(internal))

    assigned = internal + client
    for it in assigned:
        it.assigned_to = user_id
        it.status = "assigned"
    db.flush()
    got_int, got_cli = len(internal), len(client)
    return {
        "assigned": len(assigned), "internal": got_int, "client": got_cli,
        "target_internal": want_int, "target_client": want_cli,
        "shortfall": count - len(assigned),
        "deviation": got_int - want_int,  # +ve = more internal than the ratio wanted
    }

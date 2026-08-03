from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..auth import INTERNAL_ROLES, get_current_user, require_admin
from ..database import get_db
from ..utils import iso_utc
from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Client,
    ClientProject,
    Donor,
    Placement,
    StopListEntry,
    User,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    kind: Optional[str] = None,
    client_id: Optional[int] = None,
):
    """Heavy endpoint — consolidate into a small number of aggregated queries.

    Prior version fired ~30 small SELECTs (one per stat, one per day for the
    sparkline, one per employee). Over a transatlantic link that's seconds of
    overhead. Now: one CASE-WHEN aggregate per table.

    ``kind`` scopes the whole board to one contour — ``internal`` (наши) or
    ``client`` (клиентские). ``None``/empty = everything combined. Shared
    resources (donors, stop-list) stay global regardless — they're not split
    by contour. A per-client breakdown is always returned so the client side
    can be read at a glance.
    """
    kind_f = kind if kind in ("internal", "client") else None
    # A specific client narrows the board to that one client (implies the
    # client contour). Placements carry client_id directly; plan items reach
    # the client through their client_project_id → ClientProject.client_id.
    client_f = client_id if client_id else None
    if client_f:
        kind_f = "client"
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=7)
    prev_week_start = today_start - timedelta(days=14)
    month_start = datetime(now.year, now.month, 1)
    series_start = today_start - timedelta(days=13)

    # ---- Donors aggregate ----
    donor_row = db.query(
        func.count(Donor.id).label("total"),
        func.sum(case((Donor.is_active.is_(True), 1), else_=0)).label("active"),
    ).one()
    donors_total = donor_row.total or 0
    donors_active = donor_row.active or 0

    # ---- Plan items aggregate ----
    item_q = db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
    if kind_f:
        item_q = item_q.filter(AnchorPlanItem.kind == kind_f)
    if client_f:
        item_q = item_q.join(ClientProject, AnchorPlanItem.client_project_id == ClientProject.id).filter(ClientProject.client_id == client_f)
    item_rows = item_q.group_by(AnchorPlanItem.status).all()
    by_status = {s: c for s, c in item_rows}
    items_total = sum(by_status.values())

    # ---- Placements aggregate: counts for today / yesterday / week / prev week / month / all ----
    placed = Placement.status == "placed"
    placement_base = db.query(

        func.count(Placement.id).label("total"),
        func.sum(case((placed & (Placement.placed_at >= today_start), 1), else_=0)).label("today"),
        func.sum(case(
            (placed & (Placement.placed_at >= yesterday_start) & (Placement.placed_at < today_start), 1),
            else_=0,
        )).label("yesterday"),
        func.sum(case((placed & (Placement.placed_at >= week_start), 1), else_=0)).label("week"),
        func.sum(case(
            (placed & (Placement.placed_at >= prev_week_start) & (Placement.placed_at < week_start), 1),
            else_=0,
        )).label("prev_week"),
        func.sum(case((placed & (Placement.placed_at >= month_start), 1), else_=0)).label("month"),
    )
    if kind_f:
        placement_base = placement_base.filter(Placement.kind == kind_f)
    if client_f:
        placement_base = placement_base.filter(Placement.client_id == client_f)
    placement_row = placement_base.one()
    placements_total = placement_row.total or 0
    placements_today = placement_row.today or 0
    placements_yesterday = placement_row.yesterday or 0
    placements_week = placement_row.week or 0
    placements_prev_week = placement_row.prev_week or 0
    placements_month = placement_row.month or 0

    # ---- 14-day series: one query, grouped by day ----
    day_col = func.date(Placement.placed_at)
    series_q = (
        db.query(day_col.label("d"), func.count(Placement.id))
        .filter(Placement.status == "placed", Placement.placed_at >= series_start)
    )
    if kind_f:
        series_q = series_q.filter(Placement.kind == kind_f)
    if client_f:
        series_q = series_q.filter(Placement.client_id == client_f)
    series_rows = series_q.group_by(day_col).all()
    series_counts = {str(r[0]): r[1] for r in series_rows}
    series = []
    for i in range(13, -1, -1):
        day = today_start - timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        series.append({"date": key, "count": series_counts.get(key, 0)})

    # ---- Top employees (single grouped query, join user names) ----
    top_q = (
        db.query(User.id, User.email, User.full_name, func.count(Placement.id).label("cnt"))
        .join(Placement, Placement.employee_id == User.id)
        .filter(Placement.status == "placed")
    )
    if kind_f:
        top_q = top_q.filter(Placement.kind == kind_f)
    if client_f:
        top_q = top_q.filter(Placement.client_id == client_f)
    top_rows = (
        top_q.group_by(User.id, User.email, User.full_name)
        .order_by(func.count(Placement.id).desc())
        .limit(5)
        .all()
    )
    top_employees = [
        {"user_id": r.id, "name": (r.full_name or r.email), "email": r.email, "count": r.cnt}
        for r in top_rows
    ]

    # ---- Recent activity (placements joined with user) ----
    recent_base = (
        db.query(Placement, User.full_name, User.email)
        .outerjoin(User, User.id == Placement.employee_id)
        .filter(Placement.status == "placed")
    )
    if kind_f:
        recent_base = recent_base.filter(Placement.kind == kind_f)
    if client_f:
        recent_base = recent_base.filter(Placement.client_id == client_f)
    recent_q = recent_base.order_by(Placement.placed_at.desc()).limit(8).all()
    recent_activity = [
        {
            "id": p.id,
            "target_url": p.target_url,
            "donor_url": p.donor_url,
            "result_url": p.result_url,
            "employee_name": (full_name or email or "—"),
            "placed_at": iso_utc(p.placed_at),
        }
        for p, full_name, email in recent_q
    ]

    # ---- Problem items (single query joined with plan names) ----
    problem_base = (
        db.query(AnchorPlanItem, AnchorPlan.plan_name)
        .outerjoin(AnchorPlan, AnchorPlan.id == AnchorPlanItem.anchor_plan_id)
        .filter(AnchorPlanItem.status == "problem")
    )
    if kind_f:
        problem_base = problem_base.filter(AnchorPlanItem.kind == kind_f)
    if client_f:
        problem_base = problem_base.join(ClientProject, AnchorPlanItem.client_project_id == ClientProject.id).filter(ClientProject.client_id == client_f)
    problem_q = problem_base.order_by(AnchorPlanItem.updated_at.desc()).limit(8).all()
    problems = [
        {
            "id": it.id,
            "anchor_plan_id": it.anchor_plan_id,
            "plan_name": plan_name or "",
            "target_url": it.target_url,
            "target_domain": it.target_domain,
            "comment": it.comment,
            "updated_at": iso_utc(it.updated_at),
        }
        for it, plan_name in problem_q
    ]

    # ---- Per-employee progress: single grouped query with CASE-WHEN ----
    done_when = AnchorPlanItem.status.in_(["placed", "done"])
    in_progress_when = AnchorPlanItem.status.in_(["assigned", "in_progress", "donor_selected"])
    problem_when = AnchorPlanItem.status.in_(["problem", "rejected"])
    emp_q = (
        db.query(
            User.id,
            User.full_name,
            User.email,
            func.count(AnchorPlanItem.id).label("total"),
            func.sum(case((done_when, 1), else_=0)).label("done"),
            func.sum(case((in_progress_when, 1), else_=0)).label("in_progress"),
            func.sum(case((problem_when, 1), else_=0)).label("problems"),
        )
        .join(AnchorPlanItem, AnchorPlanItem.assigned_to == User.id)
        # "employee" was never a real role — internal staff are user/teamlead/
        # manager/admin. Filtering on the phantom role left this panel empty.
        .filter(User.is_active.is_(True), User.role.in_(INTERNAL_ROLES))
    )
    if kind_f:
        emp_q = emp_q.filter(AnchorPlanItem.kind == kind_f)
    if client_f:
        emp_q = emp_q.join(ClientProject, AnchorPlanItem.client_project_id == ClientProject.id).filter(ClientProject.client_id == client_f)
    emp_rows = (
        emp_q.group_by(User.id, User.full_name, User.email)
        .order_by(func.count(AnchorPlanItem.id).desc())
        .all()
    )
    employees_progress = [
        {
            "user_id": r.id,
            "name": (r.full_name or r.email),
            "email": r.email,
            "total": r.total or 0,
            "done": r.done or 0,
            "in_progress": r.in_progress or 0,
            "problems": r.problems or 0,
        }
        for r in emp_rows
    ]

    # ---- Always-on contour split (independent of the `kind` scope) so the UI
    # toggle can show both totals side by side without a second request. ----
    split_rows = (
        db.query(Placement.kind, func.count(Placement.id))
        .filter(Placement.status == "placed")
        .group_by(Placement.kind)
        .all()
    )
    split = {k: c for k, c in split_rows}
    placements_internal = split.get("internal", 0)
    placements_client = sum(c for k, c in split.items() if k and k != "internal")

    # ---- Per-client breakdown (client contour only — internal has no client). ----
    client_rows = (
        db.query(Client.id, Client.name, func.count(Placement.id).label("cnt"))
        .join(Placement, Placement.client_id == Client.id)
        .filter(Placement.status == "placed")
        .group_by(Client.id, Client.name)
        .order_by(func.count(Placement.id).desc())
        .limit(10)
        .all()
    )
    by_client = [
        {"client_id": r.id, "name": r.name or f"Клиент #{r.id}", "count": r.cnt}
        for r in client_rows
    ]

    return {
        "kind": kind_f or "all",
        "client_id": client_f,
        "placements_internal": placements_internal,
        "placements_client": placements_client,
        "by_client": by_client,
        "donors_total": donors_total,
        "donors_active": donors_active,
        "items_total": items_total,
        "placements_total": placements_total,
        "placements_today": placements_today,
        "placements_yesterday": placements_yesterday,
        "placements_month": placements_month,
        "placements_week": placements_week,
        "placements_prev_week": placements_prev_week,
        "tasks_pending": by_status.get("new", 0) + by_status.get("donor_selected", 0) + by_status.get("assigned", 0),
        "tasks_in_progress": by_status.get("in_progress", 0),
        "tasks_done": by_status.get("placed", 0) + by_status.get("done", 0),
        "tasks_problem": by_status.get("problem", 0) + by_status.get("rejected", 0),
        "top_employees": top_employees,
        "series": series,
        "stop_list_total": db.query(func.count(StopListEntry.id)).scalar() or 0,
        "recent_activity": recent_activity,
        "problems": problems,
        "employees_progress": employees_progress,
    }

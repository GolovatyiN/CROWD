from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..utils import iso_utc
from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    Placement,
    StopListEntry,
    User,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Heavy endpoint — consolidate into a small number of aggregated queries.

    Prior version fired ~30 small SELECTs (one per stat, one per day for the
    sparkline, one per employee). Over a transatlantic link that's seconds of
    overhead. Now: one CASE-WHEN aggregate per table.
    """
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
    item_rows = (
        db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .group_by(AnchorPlanItem.status)
        .all()
    )
    by_status = {s: c for s, c in item_rows}
    items_total = sum(by_status.values())

    # ---- Placements aggregate: counts for today / yesterday / week / prev week / month / all ----
    placed = Placement.status == "placed"
    placement_row = db.query(
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
    ).one()
    placements_total = placement_row.total or 0
    placements_today = placement_row.today or 0
    placements_yesterday = placement_row.yesterday or 0
    placements_week = placement_row.week or 0
    placements_prev_week = placement_row.prev_week or 0
    placements_month = placement_row.month or 0

    # ---- 14-day series: one query, grouped by day ----
    day_col = func.date(Placement.placed_at)
    series_rows = (
        db.query(day_col.label("d"), func.count(Placement.id))
        .filter(Placement.status == "placed", Placement.placed_at >= series_start)
        .group_by(day_col)
        .all()
    )
    series_counts = {str(r[0]): r[1] for r in series_rows}
    series = []
    for i in range(13, -1, -1):
        day = today_start - timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        series.append({"date": key, "count": series_counts.get(key, 0)})

    # ---- Top employees (single grouped query, join user names) ----
    top_rows = (
        db.query(User.id, User.email, User.full_name, func.count(Placement.id).label("cnt"))
        .join(Placement, Placement.employee_id == User.id)
        .filter(Placement.status == "placed")
        .group_by(User.id, User.email, User.full_name)
        .order_by(func.count(Placement.id).desc())
        .limit(5)
        .all()
    )
    top_employees = [
        {"user_id": r.id, "name": (r.full_name or r.email), "email": r.email, "count": r.cnt}
        for r in top_rows
    ]

    # ---- Recent activity (placements joined with user) ----
    recent_q = (
        db.query(Placement, User.full_name, User.email)
        .outerjoin(User, User.id == Placement.employee_id)
        .filter(Placement.status == "placed")
        .order_by(Placement.placed_at.desc())
        .limit(8)
        .all()
    )
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
    problem_q = (
        db.query(AnchorPlanItem, AnchorPlan.plan_name)
        .outerjoin(AnchorPlan, AnchorPlan.id == AnchorPlanItem.anchor_plan_id)
        .filter(AnchorPlanItem.status == "problem")
        .order_by(AnchorPlanItem.updated_at.desc())
        .limit(8)
        .all()
    )
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
    emp_rows = (
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
        .filter(User.is_active.is_(True), User.role == "employee")
        .group_by(User.id, User.full_name, User.email)
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

    return {
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

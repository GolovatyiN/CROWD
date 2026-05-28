from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
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
def stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=7)
    prev_week_start = today_start - timedelta(days=14)
    month_start = datetime(now.year, now.month, 1)

    donors_total = db.query(func.count(Donor.id)).scalar() or 0
    donors_active = db.query(func.count(Donor.id)).filter(Donor.is_active.is_(True)).scalar() or 0
    items_total = db.query(func.count(AnchorPlanItem.id)).scalar() or 0
    placements_total = db.query(func.count(Placement.id)).scalar() or 0

    placements_today = (
        db.query(func.count(Placement.id))
        .filter(Placement.placed_at >= today_start, Placement.status == "placed")
        .scalar() or 0
    )
    placements_yesterday = (
        db.query(func.count(Placement.id))
        .filter(
            Placement.placed_at >= yesterday_start,
            Placement.placed_at < today_start,
            Placement.status == "placed",
        ).scalar() or 0
    )
    placements_month = (
        db.query(func.count(Placement.id))
        .filter(Placement.placed_at >= month_start, Placement.status == "placed")
        .scalar() or 0
    )
    placements_week = (
        db.query(func.count(Placement.id))
        .filter(Placement.placed_at >= week_start, Placement.status == "placed")
        .scalar() or 0
    )
    placements_prev_week = (
        db.query(func.count(Placement.id))
        .filter(
            Placement.placed_at >= prev_week_start,
            Placement.placed_at < week_start,
            Placement.status == "placed",
        ).scalar() or 0
    )

    status_rows = (
        db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .group_by(AnchorPlanItem.status)
        .all()
    )
    by_status = {s: c for s, c in status_rows}

    top_employees_rows = (
        db.query(Placement.employee_id, func.count(Placement.id))
        .filter(Placement.status == "placed")
        .group_by(Placement.employee_id)
        .order_by(func.count(Placement.id).desc())
        .limit(5)
        .all()
    )
    top_employees = []
    for emp_id, cnt in top_employees_rows:
        if not emp_id:
            continue
        u = db.get(User, emp_id)
        top_employees.append({
            "user_id": emp_id,
            "name": (u.full_name or u.email) if u else "?",
            "email": u.email if u else "",
            "count": cnt,
        })

    series = []
    for i in range(13, -1, -1):
        day_start = today_start - timedelta(days=i)
        day_end = day_start + timedelta(days=1)
        c = (
            db.query(func.count(Placement.id))
            .filter(Placement.placed_at >= day_start, Placement.placed_at < day_end, Placement.status == "placed")
            .scalar() or 0
        )
        series.append({"date": day_start.strftime("%Y-%m-%d"), "count": c})

    # Recent activity
    recent_placed = (
        db.query(Placement)
        .filter(Placement.status == "placed")
        .order_by(Placement.placed_at.desc())
        .limit(8)
        .all()
    )
    recent_activity = []
    for p in recent_placed:
        emp = db.get(User, p.employee_id) if p.employee_id else None
        recent_activity.append({
            "id": p.id,
            "target_url": p.target_url,
            "donor_url": p.donor_url,
            "result_url": p.result_url,
            "employee_name": (emp.full_name or emp.email) if emp else "—",
            "placed_at": p.placed_at.isoformat() if p.placed_at else None,
        })

    # Problems feed (anchor plan items with status problem)
    problem_items = (
        db.query(AnchorPlanItem)
        .filter(AnchorPlanItem.status == "problem")
        .order_by(AnchorPlanItem.updated_at.desc())
        .limit(8)
        .all()
    )
    problems = []
    for it in problem_items:
        plan = db.get(AnchorPlan, it.anchor_plan_id)
        problems.append({
            "id": it.id,
            "anchor_plan_id": it.anchor_plan_id,
            "plan_name": plan.plan_name if plan else "",
            "target_url": it.target_url,
            "target_domain": it.target_domain,
            "comment": it.comment,
            "updated_at": it.updated_at.isoformat() if it.updated_at else None,
        })

    # Per-employee progress
    employees = db.query(User).filter(User.is_active.is_(True), User.role == "employee").all()
    employees_progress = []
    for u in employees:
        total = (
            db.query(func.count(AnchorPlanItem.id))
            .filter(AnchorPlanItem.assigned_to == u.id)
            .scalar() or 0
        )
        done = (
            db.query(func.count(AnchorPlanItem.id))
            .filter(AnchorPlanItem.assigned_to == u.id, AnchorPlanItem.status.in_(["placed", "done"]))
            .scalar() or 0
        )
        in_progress = (
            db.query(func.count(AnchorPlanItem.id))
            .filter(AnchorPlanItem.assigned_to == u.id, AnchorPlanItem.status.in_(["assigned", "in_progress", "donor_selected"]))
            .scalar() or 0
        )
        problems_count = (
            db.query(func.count(AnchorPlanItem.id))
            .filter(AnchorPlanItem.assigned_to == u.id, AnchorPlanItem.status.in_(["problem", "rejected"]))
            .scalar() or 0
        )
        if total or in_progress or problems_count:
            employees_progress.append({
                "user_id": u.id,
                "name": u.full_name or u.email,
                "email": u.email,
                "total": total,
                "done": done,
                "in_progress": in_progress,
                "problems": problems_count,
            })
    employees_progress.sort(key=lambda e: e["total"], reverse=True)

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

"""Work-distribution settings, plan/fact, and auto-assign. Manager+ only."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_manager
from ..database import get_db
from ..models import AllocationSetting, User
from ..services import allocation as alloc
from ..services import audit
from ..utils import iso_utc

router = APIRouter(prefix="/allocation", tags=["allocation"])


def _row(r: AllocationSetting) -> dict:
    return {
        "id": r.id, "scope": r.scope, "user_id": r.user_id,
        "internal_pct": r.internal_pct, "client_pct": r.client_pct,
        "daily_target": r.daily_target, "monthly_target": r.monthly_target,
        "updated_at": iso_utc(r.updated_at),
    }


@router.get("")
def get_allocation(db: Session = Depends(get_db), _: User = Depends(require_manager)):
    rows = db.query(AllocationSetting).all()
    glob = next((r for r in rows if r.scope == "global"), None)
    return {
        "global": _row(glob) if glob else {**alloc.DEFAULT, "scope": "global", "user_id": None},
        "employees": [_row(r) for r in rows if r.scope == "employee"],
    }


@router.put("")
def put_allocation(payload: dict = Body(...), db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    scope = payload.get("scope", "global")
    if scope not in ("global", "employee"):
        raise HTTPException(status_code=400, detail="scope должен быть global или employee")
    user_id = payload.get("user_id") if scope == "employee" else None
    if scope == "employee" and not user_id:
        raise HTTPException(status_code=400, detail="Для employee нужен user_id")
    try:
        ip = int(payload.get("internal_pct", 50))
    except (TypeError, ValueError):
        ip = 50
    cp = 100 - ip
    row = alloc.upsert(
        db, scope=scope, user_id=user_id, internal_pct=ip, client_pct=cp,
        daily_target=int(payload.get("daily_target", 0) or 0),
        monthly_target=int(payload.get("monthly_target", 0) or 0),
        updated_by=actor.id,
    )
    audit.log(db, actor, "allocation.update", target_type="allocation",
              target_label=f"{scope}:{user_id or 'global'}", internal_pct=ip)
    db.commit()
    return _row(row)


@router.get("/plan")
def get_plan(user_id: int, day: Optional[str] = None, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    try:
        d = date.fromisoformat(day) if day else date.today()
    except ValueError:
        d = date.today()
    return alloc.plan_vs_fact(db, user_id, d)


@router.post("/auto-assign")
def post_auto_assign(payload: dict = Body(...), db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="Укажите сотрудника (user_id)")
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    count = payload.get("count")
    result = alloc.auto_assign(db, user_id, int(count) if count else None)
    audit.log(db, actor, "allocation.auto_assign", target_type="user", target_id=user_id,
              target_label=f"user#{user_id}", assigned=result.get("assigned", 0))
    db.commit()
    return result

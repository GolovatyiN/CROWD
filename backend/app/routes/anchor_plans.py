from typing import Optional
import io

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import AnchorPlan, AnchorPlanItem, Donor, User
from ..schemas import (
    AnchorPlanItemOut,
    AnchorPlanItemUpdate,
    AnchorPlanOut,
    AssignRequest,
    AutoMatchResult,
    ImportPreview,
)
from ..services.importer import import_anchor_plan, plan_items_to_csv
from ..services.matcher import auto_match_plan, find_best_donor, quality_score, _blocked_donor_urls_for_target, _candidates_query, link_type_compatible

router = APIRouter(prefix="/anchor-plans", tags=["anchor_plans"])


def _plan_with_stats(db: Session, plan: AnchorPlan) -> dict:
    rows = (
        db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .filter(AnchorPlanItem.anchor_plan_id == plan.id)
        .group_by(AnchorPlanItem.status)
        .all()
    )
    by_status = {s: c for s, c in rows}
    total = sum(by_status.values())
    completed = by_status.get("placed", 0) + by_status.get("done", 0)
    problem = by_status.get("problem", 0) + by_status.get("rejected", 0)
    pending = total - completed - problem
    return {
        "id": plan.id,
        "plan_name": plan.plan_name,
        "uploaded_file_name": plan.uploaded_file_name,
        "status": plan.status,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        "total_rows": total,
        "completed_rows": completed,
        "pending_rows": pending,
        "problem_rows": problem,
    }


PLAN_SORT_FIELDS = {
    "plan_name": AnchorPlan.plan_name,
    "created_at": AnchorPlan.created_at,
    "id": AnchorPlan.id,
}


@router.get("", response_model=list[AnchorPlanOut])
def list_plans(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    sort: str = "created_at",
    order: str = "desc",
):
    sort_col = PLAN_SORT_FIELDS.get(sort.lower(), AnchorPlan.created_at)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    plans = db.query(AnchorPlan).order_by(direction).all()
    # Sort numerical aggregate fields in Python after fetching (small list)
    enriched = [_plan_with_stats(db, p) for p in plans]
    numeric_keys = {"total_rows", "completed_rows", "pending_rows", "problem_rows"}
    if sort in numeric_keys:
        enriched.sort(key=lambda x: x[sort], reverse=order.lower() == "desc")
    return enriched


@router.get("/{plan_id}", response_model=AnchorPlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Не найдено")
    return _plan_with_stats(db, plan)


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(plan)
    db.commit()
    return {"ok": True}


ITEM_SORT_FIELDS = {
    "id": AnchorPlanItem.id,
    "target_url": AnchorPlanItem.target_url,
    "target_domain": AnchorPlanItem.target_domain,
    "anchor_text": AnchorPlanItem.anchor_text,
    "geo": AnchorPlanItem.geo,
    "language": AnchorPlanItem.language,
    "required_link_type": AnchorPlanItem.required_link_type,
    "status": AnchorPlanItem.status,
    "assigned_to": AnchorPlanItem.assigned_to,
    "selected_donor_id": AnchorPlanItem.selected_donor_id,
    "created_at": AnchorPlanItem.created_at,
    "updated_at": AnchorPlanItem.updated_at,
}


@router.get("/{plan_id}/items", response_model=list[AnchorPlanItemOut])
def list_items(
    plan_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    q: Optional[str] = None,
    status: Optional[str] = None,
    geo: Optional[str] = None,
    language: Optional[str] = None,
    assigned_to: Optional[int] = None,
    sort: str = "id",
    order: str = "asc",
    limit: int = 500,
    offset: int = 0,
):
    query = db.query(AnchorPlanItem).filter(AnchorPlanItem.anchor_plan_id == plan_id)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(
            func.lower(AnchorPlanItem.target_url).like(like),
            func.lower(AnchorPlanItem.target_domain).like(like),
            func.lower(AnchorPlanItem.anchor_text).like(like),
        ))
    if status:
        query = query.filter(AnchorPlanItem.status == status)
    if geo:
        query = query.filter(func.lower(AnchorPlanItem.geo) == geo.lower())
    if language:
        query = query.filter(func.lower(AnchorPlanItem.language) == language.lower())
    if assigned_to is not None:
        query = query.filter(AnchorPlanItem.assigned_to == assigned_to)
    sort_col = ITEM_SORT_FIELDS.get(sort.lower(), AnchorPlanItem.id)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    return query.order_by(direction, AnchorPlanItem.id.asc()).offset(offset).limit(limit).all()


@router.patch("/items/{item_id}", response_model=AnchorPlanItemOut)
def update_item(
    item_id: int,
    payload: AnchorPlanItemUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    item = db.get(AnchorPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.post("/import", response_model=ImportPreview)
async def import_plan(
    file: UploadFile = File(...),
    plan_name: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    content = await file.read()
    try:
        result = import_anchor_plan(db, content, file.filename or "plan", plan_name, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return result


@router.post("/{plan_id}/auto-match", response_model=AutoMatchResult)
def auto_match(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    result = auto_match_plan(db, plan_id)
    db.commit()
    return result


@router.post("/items/{item_id}/match-now")
def match_one_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = db.get(AnchorPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    donor = find_best_donor(db, item)
    if not donor:
        item.status = "problem"
        item.comment = "Подходящий донор не найден"
        db.commit()
        raise HTTPException(status_code=404, detail="Подходящий донор не найден")
    item.selected_donor_id = donor.id
    if item.status in ("new", "problem"):
        item.status = "donor_selected"
    db.commit()
    return {"donor_id": donor.id, "donor_url": donor.donor_url}


@router.get("/items/{item_id}/candidates")
def list_candidates(
    item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    limit: int = 30,
):
    """Return top candidate donors for a single plan item, applying the matcher's rules."""
    item = db.get(AnchorPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    blocked = _blocked_donor_urls_for_target(db, item.target_url)
    donors = db.execute(_candidates_query(db, item)).scalars().all()
    eligible = []
    for d in donors:
        if d.donor_url in blocked:
            continue
        if not link_type_compatible(item.required_link_type, d.link_type):
            continue
        eligible.append(d)
    eligible.sort(key=quality_score, reverse=True)
    eligible = eligible[:limit]
    return [{
        "id": d.id,
        "donor_url": d.donor_url,
        "domain": d.domain,
        "tr": d.tr,
        "organic_traffic": d.organic_traffic,
        "ref_domains": d.ref_domains,
        "backlinks": d.backlinks,
        "geo": d.geo,
        "language": d.language,
        "link_type": d.link_type,
        "score": round(quality_score(d), 1),
    } for d in eligible]


@router.post("/items/{item_id}/set-donor")
def set_donor(
    item_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    item = db.get(AnchorPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    donor_id = payload.get("donor_id")
    if not donor_id:
        raise HTTPException(status_code=400, detail="donor_id обязателен")
    donor = db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="Донор не найден")
    item.selected_donor_id = donor.id
    if item.status in ("new", "problem"):
        item.status = "donor_selected"
    db.commit()
    return {"donor_id": donor.id, "donor_url": donor.donor_url}


@router.post("/{plan_id}/assign")
def assign_items(
    plan_id: int,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, payload.assigned_to)
    if not user:
        raise HTTPException(status_code=400, detail="Сотрудник не найден")
    items = (
        db.query(AnchorPlanItem)
        .filter(AnchorPlanItem.anchor_plan_id == plan_id, AnchorPlanItem.id.in_(payload.item_ids))
        .all()
    )
    for it in items:
        it.assigned_to = payload.assigned_to
        if it.status in ("new", "donor_selected"):
            it.status = "assigned"
    db.commit()
    return {"updated": len(items)}


@router.get("/{plan_id}/export")
def export_plan(plan_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    items = db.query(AnchorPlanItem).filter(AnchorPlanItem.anchor_plan_id == plan_id).all()
    csv_data = plan_items_to_csv(items)
    return StreamingResponse(
        io.BytesIO(csv_data.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="plan_{plan_id}.csv"'},
    )

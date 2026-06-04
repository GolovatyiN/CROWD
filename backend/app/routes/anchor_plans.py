from typing import Optional
import io

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, update as sa_update
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import AnchorPlan, AnchorPlanItem, Donor, Placement, StopListEntry, User
from ..schemas import (
    AnchorPlanItemOut,
    AnchorPlanItemUpdate,
    AnchorPlanOut,
    AssignRequest,
    AutoMatchResult,
    ImportPreview,
)
from ..services import audit
from ..utils import iso_utc
from ..services.importer import import_anchor_plan, plan_items_to_csv
from ..services.matcher import auto_match_plan, find_best_donor, quality_score, _blocked_donor_urls_for_target, _candidates_query, link_type_compatible

router = APIRouter(prefix="/anchor-plans", tags=["anchor_plans"])


def _stats_from_status_counts(by_status: dict[str, int]) -> dict[str, int]:
    total = sum(by_status.values())
    completed = by_status.get("placed", 0) + by_status.get("done", 0)
    problem = by_status.get("problem", 0) + by_status.get("rejected", 0)
    pending = total - completed - problem
    return {"total_rows": total, "completed_rows": completed,
            "pending_rows": pending, "problem_rows": problem}


def _plan_payload(plan: AnchorPlan, stats: dict[str, int]) -> dict:
    return {
        "id": plan.id,
        "plan_name": plan.plan_name,
        "uploaded_file_name": plan.uploaded_file_name,
        "status": plan.status,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        **stats,
    }


def _plan_with_stats(db: Session, plan: AnchorPlan) -> dict:
    """Stats for a single plan (used by the detail endpoint)."""
    rows = (
        db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .filter(AnchorPlanItem.anchor_plan_id == plan.id)
        .group_by(AnchorPlanItem.status)
        .all()
    )
    return _plan_payload(plan, _stats_from_status_counts({s: c for s, c in rows}))


PLAN_SORT_FIELDS = {
    "plan_name": AnchorPlan.plan_name,
    "created_at": AnchorPlan.created_at,
    "id": AnchorPlan.id,
}


@router.get("", response_model=list[AnchorPlanOut])
def list_plans(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    sort: str = "created_at",
    order: str = "desc",
):
    sort_col = PLAN_SORT_FIELDS.get(sort.lower(), AnchorPlan.created_at)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    plans = db.query(AnchorPlan).order_by(direction).all()

    # Stats for ALL plans in one grouped query instead of one query per plan
    # (was N+1). Build {plan_id: {status: count}} then derive the rollups.
    counts_by_plan: dict[int, dict[str, int]] = {}
    for plan_id, status, cnt in (
        db.query(AnchorPlanItem.anchor_plan_id, AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .group_by(AnchorPlanItem.anchor_plan_id, AnchorPlanItem.status)
        .all()
    ):
        counts_by_plan.setdefault(plan_id, {})[status] = cnt

    enriched = [
        _plan_payload(p, _stats_from_status_counts(counts_by_plan.get(p.id, {})))
        for p in plans
    ]
    numeric_keys = {"total_rows", "completed_rows", "pending_rows", "problem_rows"}
    if sort in numeric_keys:
        enriched.sort(key=lambda x: x[sort], reverse=order.lower() == "desc")
    return enriched


@router.get("/{plan_id}", response_model=AnchorPlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Не найдено")
    return _plan_with_stats(db, plan)


@router.patch("/{plan_id}", response_model=AnchorPlanOut)
def update_plan(plan_id: int, payload: dict = Body(...), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Rename a plan (and optionally change its status). Plans can be many, so
    a clear, editable name matters."""
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    name = payload.get("plan_name")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise HTTPException(status_code=400, detail="Название не может быть пустым")
        plan.plan_name = name[:255]
    if payload.get("status"):
        plan.status = str(payload["status"])[:32]
    db.commit()
    return _plan_with_stats(db, plan)


@router.delete("/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Delete a plan and its rows fast and safely.

    Two problems the naive `db.delete(plan)` hit on a real plan:
      1. FK violation — placements / stop-list rows reference the plan's items
         (anchor_plan_item_id has no ON DELETE rule), so deleting items errors.
      2. Slowness — ORM cascade loads & deletes 1900+ items one-by-one.

    Fix: detach history (NULL the back-reference, keep the rows — the stop-list
    is a permanent 'donor used' record and placements are work history), then
    bulk-delete the items and the plan in a handful of statements.
    """
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Не найдено")

    item_ids = [r[0] for r in db.query(AnchorPlanItem.id).filter(AnchorPlanItem.anchor_plan_id == plan_id).all()]
    if item_ids:
        # Preserve history but drop the dangling FK so the items can be removed.
        db.execute(
            sa_update(Placement).where(Placement.anchor_plan_item_id.in_(item_ids))
            .values(anchor_plan_item_id=None)
        )
        db.execute(
            sa_update(StopListEntry).where(StopListEntry.anchor_plan_item_id.in_(item_ids))
            .values(anchor_plan_item_id=None)
        )
        db.query(AnchorPlanItem).filter(AnchorPlanItem.anchor_plan_id == plan_id).delete(synchronize_session=False)

    audit.log(
        db, actor, "plan.delete",
        target_id=plan_id, target_label=plan.plan_name or f"План #{plan_id}",
        строк=len(item_ids),
    )
    db.query(AnchorPlan).filter(AnchorPlan.id == plan_id).delete(synchronize_session=False)
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


@router.get("/{plan_id}/items")
def list_items(
    plan_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
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
    items = query.order_by(direction, AnchorPlanItem.id.asc()).offset(offset).limit(limit).all()

    # Pre-load all related donors and users in two queries instead of per-row N+1.
    donor_ids = {it.selected_donor_id for it in items if it.selected_donor_id}
    user_ids = {it.assigned_to for it in items if it.assigned_to}
    donors_by_id = {}
    users_by_id = {}
    if donor_ids:
        for d in db.query(Donor).filter(Donor.id.in_(donor_ids)).all():
            donors_by_id[d.id] = d
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            users_by_id[u.id] = u

    out = []
    for it in items:
        donor = donors_by_id.get(it.selected_donor_id) if it.selected_donor_id else None
        user = users_by_id.get(it.assigned_to) if it.assigned_to else None
        out.append({
            "id": it.id,
            "anchor_plan_id": it.anchor_plan_id,
            "target_domain": it.target_domain,
            "target_url": it.target_url,
            "anchor_text": it.anchor_text,
            "geo": it.geo,
            "language": it.language,
            "required_link_type": it.required_link_type,
            "requirements": it.requirements,
            "assigned_to": it.assigned_to,
            "selected_donor_id": it.selected_donor_id,
            "status": it.status,
            "result_url": it.result_url,
            "comment": it.comment,
            "created_at": iso_utc(it.created_at),
            "updated_at": iso_utc(it.updated_at),
            "donor": {
                "id": donor.id,
                "donor_url": donor.donor_url,
                "domain": donor.domain,
                "geo": donor.geo,
                "language": donor.language,
                "link_type": donor.link_type,
                "tr": donor.tr,
                "organic_traffic": donor.organic_traffic,
            } if donor else None,
            "assignee": {
                "id": user.id,
                "name": user.full_name or user.email,
                "email": user.email,
            } if user else None,
        })
    return out


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
    audit.log(
        db, user, "plan.import",
        target_id=getattr(result, "plan_id", None),
        target_label=plan_name or file.filename or "план",
        строк=getattr(result, "rows_inserted", 0),
    )
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


@router.post("/{plan_id}/rematch-all", response_model=AutoMatchResult)
def rematch_all(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Force-reset donors on every non-finalised row and pick again.

    Useful after changing the GEO/language data of the plan or the matching
    rules — without this you'd have to delete the plan and re-import.
    """
    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    # Drop current donor selections on everything that's not yet placed.
    db.query(AnchorPlanItem).filter(
        AnchorPlanItem.anchor_plan_id == plan_id,
        ~AnchorPlanItem.status.in_(["placed", "done", "rejected"]),
    ).update({
        AnchorPlanItem.selected_donor_id: None,
    }, synchronize_session=False)
    db.flush()
    result = auto_match_plan(db, plan_id)
    db.commit()
    return result


@router.post("/{plan_id}/reinfer-geo")
def reinfer_geo(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Re-fill empty geo/language columns on the plan from the URL's TLD.

    Lets the user fix a plan that was imported from a domains-only file —
    .es / .com.br / .co.in get a sensible GEO without re-uploading.
    """
    from ..services.geo import country_from_url, language_from_url, normalize_country, normalize_language

    plan = db.get(AnchorPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="План не найден")
    items = db.query(AnchorPlanItem).filter(AnchorPlanItem.anchor_plan_id == plan_id).all()
    geo_filled = 0
    lang_filled = 0
    for it in items:
        url_source = it.target_url or it.target_domain
        # Normalise whatever is already there first.
        if it.geo:
            norm = normalize_country(it.geo)
            if norm and norm != it.geo:
                it.geo = norm
        if it.language:
            norm = normalize_language(it.language)
            if norm and norm != it.language:
                it.language = norm
        if not it.geo and url_source:
            inferred = country_from_url(url_source)
            if inferred:
                it.geo = inferred
                geo_filled += 1
        if not it.language and url_source:
            inferred = language_from_url(url_source)
            if inferred:
                it.language = inferred
                lang_filled += 1
    db.commit()
    return {"geo_filled": geo_filled, "language_filled": lang_filled, "items_total": len(items)}


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
    _: User = Depends(require_admin),
    limit: int = 30,
):
    """Return top candidate donors for a single plan item, applying the matcher's rules."""
    item = db.get(AnchorPlanItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Не найдено")
    blocked = _blocked_donor_urls_for_target(db, item.target_url, item.anchor_text or "")
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
def export_plan(plan_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    items = db.query(AnchorPlanItem).filter(AnchorPlanItem.anchor_plan_id == plan_id).all()
    csv_data = plan_items_to_csv(items)
    return StreamingResponse(
        io.BytesIO(csv_data.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="plan_{plan_id}.csv"'},
    )

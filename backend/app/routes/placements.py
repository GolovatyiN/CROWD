from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import (
    AnchorPlan,
    AnchorPlanItem,
    Donor,
    DonorAccount,
    Placement,
    StopListEntry,
    User,
)
from ..schemas import (
    DonorAccountOut,
    MarkPlacedRequest,
    MarkProblemRequest,
    PlacementOut,
)
from ..services.matcher import extract_domain, suggest_account
from ..services.stop_list_service import register_placement

router = APIRouter(tags=["placements"])


def _ensure_placement_for_item(db: Session, item: AnchorPlanItem, user: User) -> Placement:
    """Get-or-create the working Placement record for an assigned item.

    Idempotent: if a Placement already exists for this item, return it (refreshed).
    """
    placement = (
        db.query(Placement)
        .filter(Placement.anchor_plan_item_id == item.id)
        .order_by(Placement.id.desc())
        .first()
    )
    if placement:
        return placement
    donor = db.get(Donor, item.selected_donor_id) if item.selected_donor_id else None
    placement = Placement(
        anchor_plan_item_id=item.id,
        target_url=item.target_url,
        target_domain=item.target_domain or extract_domain(item.target_url),
        donor_id=donor.id if donor else None,
        donor_url=donor.donor_url if donor else "",
        anchor_text=item.anchor_text,
        employee_id=item.assigned_to or user.id,
        status="in_progress",
    )
    db.add(placement)
    db.flush()
    return placement


@router.get("/placements", response_model=list[PlacementOut])
def list_placements(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    status: Optional[str] = None,
    employee_id: Optional[int] = None,
    limit: int = 500,
    offset: int = 0,
):
    q = db.query(Placement)
    if status:
        q = q.filter(Placement.status == status)
    if employee_id is not None:
        q = q.filter(Placement.employee_id == employee_id)
    return q.order_by(Placement.created_at.desc()).offset(offset).limit(limit).all()


# ---------- My tasks (employee view) ----------

MY_TASKS_SORT_FIELDS = {
    "id": AnchorPlanItem.id,
    "target_url": AnchorPlanItem.target_url,
    "target_domain": AnchorPlanItem.target_domain,
    "anchor_text": AnchorPlanItem.anchor_text,
    "geo": AnchorPlanItem.geo,
    "language": AnchorPlanItem.language,
    "status": AnchorPlanItem.status,
    "updated_at": AnchorPlanItem.updated_at,
}


@router.get("/my-tasks")
def my_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status: Optional[str] = None,
    sort: str = "updated_at",
    order: str = "desc",
):
    """Returns items assigned to the current user, joined with donor + existing placement."""
    q = db.query(AnchorPlanItem).filter(AnchorPlanItem.assigned_to == user.id)
    if status:
        q = q.filter(AnchorPlanItem.status == status)
    sort_col = MY_TASKS_SORT_FIELDS.get(sort.lower(), AnchorPlanItem.updated_at)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    items = q.order_by(direction, AnchorPlanItem.id.desc()).all()

    out = []
    for it in items:
        donor = db.get(Donor, it.selected_donor_id) if it.selected_donor_id else None
        placement = (
            db.query(Placement)
            .filter(Placement.anchor_plan_item_id == it.id)
            .order_by(Placement.id.desc())
            .first()
        )
        suggested = None
        if donor and not placement:
            acc = suggest_account(db, donor.id)
            if acc:
                suggested = {
                    "id": acc.id,
                    "login_email": acc.login_email,
                    "account_username": acc.account_username,
                }
        out.append({
            "item_id": it.id,
            "anchor_plan_id": it.anchor_plan_id,
            "target_domain": it.target_domain,
            "target_url": it.target_url,
            "anchor_text": it.anchor_text,
            "geo": it.geo,
            "language": it.language,
            "required_link_type": it.required_link_type,
            "requirements": it.requirements,
            "status": it.status,
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
            "placement": {
                "id": placement.id,
                "result_url": placement.result_url,
                "login_email": placement.login_email,
                "login_password": placement.login_password,
                "account_username": placement.account_username,
                "status": placement.status,
                "comment": placement.comment,
                "placed_at": placement.placed_at.isoformat() if placement.placed_at else None,
            } if placement else None,
            "suggested_account": suggested,
        })
    return out


@router.post("/my-tasks/{item_id}/take")
def take_task(item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.get(AnchorPlanItem, item_id)
    if not item or item.assigned_to != user.id:
        raise HTTPException(status_code=404, detail="Не найдено")
    placement = _ensure_placement_for_item(db, item, user)
    if item.status in ("assigned", "donor_selected", "new"):
        item.status = "in_progress"
    db.commit()
    db.refresh(placement)
    return PlacementOut.model_validate(placement)


@router.post("/placements/{placement_id}/mark-placed")
def mark_placed(
    placement_id: int,
    payload: MarkPlacedRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    placement = db.get(Placement, placement_id)
    if not placement:
        raise HTTPException(status_code=404, detail="Не найдено")
    if user.role != "admin" and placement.employee_id != user.id:
        raise HTTPException(status_code=403, detail="Это не ваша задача")
    if not payload.result_url.strip():
        raise HTTPException(status_code=400, detail="Укажите ссылку на результат размещения")

    # Block duplicate placements at the business-rule level — per ANCHOR
    # (target_url + anchor_text). The same donor is allowed for other anchors.
    exists = (
        db.query(StopListEntry)
        .filter(
            StopListEntry.target_url == placement.target_url,
            StopListEntry.anchor_text == (placement.anchor_text or ""),
            StopListEntry.donor_url == placement.donor_url,
        )
        .first()
    )
    if exists and exists.anchor_plan_item_id != placement.anchor_plan_item_id:
        raise HTTPException(
            status_code=409,
            detail="Этот анкор уже размещался на этом доноре (есть в стоп-листе)",
        )

    placement.result_url = payload.result_url.strip()
    placement.login_email = payload.login_email
    placement.login_password = payload.login_password
    placement.account_username = payload.account_username
    if payload.comment:
        placement.comment = payload.comment
    placement.status = "placed"
    placement.placed_at = datetime.utcnow()

    # Upsert donor account by (donor_id, account_username) if username provided.
    if placement.donor_id and payload.account_username:
        acc = (
            db.query(DonorAccount)
            .filter(
                DonorAccount.donor_id == placement.donor_id,
                DonorAccount.account_username == payload.account_username,
            )
            .first()
        )
        if not acc:
            acc = DonorAccount(
                donor_id=placement.donor_id,
                login_email=payload.login_email,
                login_password=payload.login_password,
                account_username=payload.account_username,
                created_by=user.id,
            )
            db.add(acc)
            db.flush()
        else:
            if payload.login_email:
                acc.login_email = payload.login_email
            if payload.login_password:
                acc.login_password = payload.login_password
        placement.donor_account_id = acc.id

    # Update plan item
    if placement.anchor_plan_item_id:
        item = db.get(AnchorPlanItem, placement.anchor_plan_item_id)
        if item:
            item.status = "placed"
            item.result_url = placement.result_url

    register_placement(db, placement)
    db.commit()
    db.refresh(placement)
    return PlacementOut.model_validate(placement)


@router.post("/placements/{placement_id}/mark-problem")
def mark_problem(
    placement_id: int,
    payload: MarkProblemRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    placement = db.get(Placement, placement_id)
    if not placement:
        raise HTTPException(status_code=404, detail="Не найдено")
    if user.role != "admin" and placement.employee_id != user.id:
        raise HTTPException(status_code=403, detail="Это не ваша задача")
    placement.status = "problem"
    placement.comment = payload.comment
    if placement.anchor_plan_item_id:
        item = db.get(AnchorPlanItem, placement.anchor_plan_item_id)
        if item:
            item.status = "problem"
            item.comment = payload.comment
    db.commit()
    return {"ok": True}

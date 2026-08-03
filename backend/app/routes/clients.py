"""Clients and client projects (Phase 2 of the internal/client split).

Managed by admins (managers get access in Phase 3). Deleting is a soft archive
(status='archived') so linked plans/placements keep their history.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import require_manager
from ..database import get_db
from ..models import (
    AnchorPlanItem,
    Client,
    ClientProject,
    ClientProjectMember,
    Placement,
    User,
)
from ..schemas import (
    ClientCreate,
    ClientOut,
    ClientProjectCreate,
    ClientProjectOut,
    ClientProjectUpdate,
    ClientUpdate,
)
from ..services import audit

router = APIRouter(tags=["clients"])


# ---------- helpers ----------

def _client_out(c: Client, projects_count: int, ptotal: int, pdone: int) -> dict:
    return {
        "id": c.id, "name": c.name, "contact_info": c.contact_info,
        "status": c.status, "comment": c.comment, "manager_id": c.manager_id,
        "created_at": c.created_at, "updated_at": c.updated_at,
        "projects_count": projects_count,
        "placements_total": ptotal, "placements_done": pdone,
    }


def _client_stats(db: Session, client_ids: list[int]) -> tuple[dict, dict, dict]:
    """Bulk stats for a set of clients: projects count + placement totals/done."""
    if not client_ids:
        return {}, {}, {}
    proj = dict(
        db.query(ClientProject.client_id, func.count(ClientProject.id))
        .filter(ClientProject.client_id.in_(client_ids))
        .group_by(ClientProject.client_id).all()
    )
    total = dict(
        db.query(Placement.client_id, func.count(Placement.id))
        .filter(Placement.client_id.in_(client_ids))
        .group_by(Placement.client_id).all()
    )
    done = dict(
        db.query(Placement.client_id, func.count(Placement.id))
        .filter(Placement.client_id.in_(client_ids), Placement.status.in_(["placed", "done"]))
        .group_by(Placement.client_id).all()
    )
    return proj, total, done


def _project_out(p: ClientProject, stats: dict[str, int], member_ids: list[int]) -> dict:
    total = sum(stats.values())
    completed = stats.get("placed", 0) + stats.get("done", 0)
    problem = stats.get("problem", 0) + stats.get("rejected", 0)
    return {
        "id": p.id, "client_id": p.client_id, "name": p.name,
        "promoted_domain": p.promoted_domain, "geo": p.geo, "language": p.language,
        "donor_requirements": p.donor_requirements, "planned_count": p.planned_count,
        "period_start": p.period_start, "period_end": p.period_end,
        "status": p.status, "manager_id": p.manager_id,
        "created_at": p.created_at, "updated_at": p.updated_at,
        "total_rows": total, "completed_rows": completed, "problem_rows": problem,
        "member_ids": member_ids,
    }


def _project_item_stats(db: Session, project_id: int) -> dict[str, int]:
    rows = (
        db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .filter(AnchorPlanItem.client_project_id == project_id)
        .group_by(AnchorPlanItem.status).all()
    )
    return {s: c for s, c in rows}


def _project_member_ids(db: Session, project_id: int) -> list[int]:
    return [
        uid for (uid,) in db.query(ClientProjectMember.user_id)
        .filter(ClientProjectMember.client_project_id == project_id).all()
    ]


# ---------- clients ----------

@router.get("/clients", response_model=list[ClientOut])
def list_clients(
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
    q: Optional[str] = None,
    status: Optional[str] = None,
):
    query = db.query(Client)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(func.lower(Client.name).like(like), func.lower(Client.contact_info).like(like)))
    if status:
        query = query.filter(Client.status == status)
    clients = query.order_by(Client.created_at.desc()).all()
    ids = [c.id for c in clients]
    proj, total, done = _client_stats(db, ids)
    return [_client_out(c, proj.get(c.id, 0), total.get(c.id, 0), done.get(c.id, 0)) for c in clients]


@router.post("/clients", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Укажите название клиента")
    c = Client(
        name=payload.name.strip(), contact_info=payload.contact_info,
        status=payload.status or "active", comment=payload.comment, manager_id=payload.manager_id,
    )
    db.add(c)
    db.flush()
    audit.log(db, actor, "client.create", target_id=c.id, target_label=c.name, target_type="client")
    db.commit()
    return _client_out(c, 0, 0, 0)


@router.get("/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    proj, total, done = _client_stats(db, [c.id])
    return _client_out(c, proj.get(c.id, 0), total.get(c.id, 0), done.get(c.id, 0))


@router.patch("/clients/{client_id}", response_model=ClientOut)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    audit.log(db, actor, "client.update", target_id=c.id, target_label=c.name, target_type="client")
    db.commit()
    proj, total, done = _client_stats(db, [c.id])
    return _client_out(c, proj.get(c.id, 0), total.get(c.id, 0), done.get(c.id, 0))


@router.delete("/clients/{client_id}")
def archive_client(client_id: int, db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    """Soft-archive (status='archived') — preserves linked plans/placements."""
    c = db.get(Client, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    c.status = "archived"
    audit.log(db, actor, "client.archive", target_id=c.id, target_label=c.name, target_type="client")
    db.commit()
    return {"ok": True}


# ---------- client projects ----------

@router.get("/client-projects", response_model=list[ClientProjectOut])
def list_client_projects(
    db: Session = Depends(get_db),
    _: User = Depends(require_manager),
    client_id: Optional[int] = None,
    status: Optional[str] = None,
):
    query = db.query(ClientProject)
    if client_id is not None:
        query = query.filter(ClientProject.client_id == client_id)
    if status:
        query = query.filter(ClientProject.status == status)
    projects = query.order_by(ClientProject.created_at.desc()).all()
    return [_project_out(p, _project_item_stats(db, p.id), _project_member_ids(db, p.id)) for p in projects]


@router.post("/client-projects", response_model=ClientProjectOut)
def create_client_project(payload: ClientProjectCreate, db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    client = db.get(Client, payload.client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Клиент не найден")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Укажите название проекта")
    p = ClientProject(**payload.model_dump())
    db.add(p)
    db.flush()
    audit.log(db, actor, "client_project.create", target_id=p.id, target_label=p.name,
              target_type="client_project", client_id=client.id)
    db.commit()
    return _project_out(p, {}, [])


@router.get("/client-projects/{project_id}", response_model=ClientProjectOut)
def get_client_project(project_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    p = db.get(ClientProject, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return _project_out(p, _project_item_stats(db, p.id), _project_member_ids(db, p.id))


@router.patch("/client-projects/{project_id}", response_model=ClientProjectOut)
def update_client_project(project_id: int, payload: ClientProjectUpdate, db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    p = db.get(ClientProject, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Проект не найден")
    data = payload.model_dump(exclude_unset=True)
    member_ids = data.pop("member_ids", None)
    for k, v in data.items():
        setattr(p, k, v)
    if member_ids is not None:
        # Replace the member set.
        db.query(ClientProjectMember).filter(ClientProjectMember.client_project_id == p.id).delete(synchronize_session=False)
        for uid in dict.fromkeys(member_ids):  # dedup, keep order
            db.add(ClientProjectMember(client_project_id=p.id, user_id=uid))
    audit.log(db, actor, "client_project.update", target_id=p.id, target_label=p.name, target_type="client_project")
    db.commit()
    return _project_out(p, _project_item_stats(db, p.id), _project_member_ids(db, p.id))


@router.delete("/client-projects/{project_id}")
def archive_client_project(project_id: int, db: Session = Depends(get_db), actor: User = Depends(require_manager)):
    p = db.get(ClientProject, project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Проект не найден")
    p.status = "archived"
    audit.log(db, actor, "client_project.archive", target_id=p.id, target_label=p.name, target_type="client_project")
    db.commit()
    return {"ok": True}

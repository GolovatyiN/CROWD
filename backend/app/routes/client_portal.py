"""Client portal — read-only, hard-scoped to the caller's own client.

SECURITY: every endpoint requires role='client' (require_client) AND filters by
`user.client_id` directly in SQL. Responses are hand-built dicts with an explicit
whitelist of fields — NO donor base, NO stop-list, NO login credentials, NO
internal comments, NO other clients, NO internal projects. A client cannot reach
another client's data even by guessing ids (ownership is re-checked per request).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_client
from ..database import get_db
from ..models import AnchorPlanItem, ClientProject, Placement, User
from ..services.matcher import extract_domain
from ..utils import iso_utc

router = APIRouter(prefix="/client", tags=["client-portal"])


def _own_project_or_404(db: Session, user: User, project_id: int) -> ClientProject:
    """Fetch a project ONLY if it belongs to the caller's client."""
    p = db.get(ClientProject, project_id)
    if not p or p.client_id != user.client_id:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return p


def _project_rollup(db: Session, project_id: int) -> dict:
    rows = dict(
        db.query(AnchorPlanItem.status, func.count(AnchorPlanItem.id))
        .filter(AnchorPlanItem.client_project_id == project_id)
        .group_by(AnchorPlanItem.status).all()
    )
    total = sum(rows.values())
    done = rows.get("placed", 0) + rows.get("done", 0)
    problem = rows.get("problem", 0) + rows.get("rejected", 0)
    return {"total_rows": total, "completed_rows": done, "problem_rows": problem}


def _project_public(p: ClientProject, rollup: dict) -> dict:
    return {
        "id": p.id, "name": p.name, "promoted_domain": p.promoted_domain,
        "geo": p.geo, "language": p.language, "planned_count": p.planned_count,
        "period_start": iso_utc(p.period_start), "period_end": iso_utc(p.period_end),
        "status": p.status, **rollup,
    }


@router.get("/summary")
def client_summary(db: Session = Depends(get_db), user: User = Depends(require_client)):
    projects = db.query(func.count(ClientProject.id)).filter(ClientProject.client_id == user.client_id).scalar() or 0
    total = db.query(func.count(Placement.id)).filter(Placement.client_id == user.client_id).scalar() or 0
    done = db.query(func.count(Placement.id)).filter(
        Placement.client_id == user.client_id, Placement.status.in_(["placed", "done"])
    ).scalar() or 0
    return {"projects": projects, "placements_total": total, "placements_done": done}


@router.get("/projects")
def client_projects(db: Session = Depends(get_db), user: User = Depends(require_client)):
    projs = (
        db.query(ClientProject)
        .filter(ClientProject.client_id == user.client_id)
        .order_by(ClientProject.created_at.desc()).all()
    )
    return [_project_public(p, _project_rollup(db, p.id)) for p in projs]


@router.get("/projects/{project_id}")
def client_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(require_client)):
    p = _own_project_or_404(db, user, project_id)
    return _project_public(p, _project_rollup(db, p.id))


@router.get("/projects/{project_id}/placements")
def client_project_placements(project_id: int, db: Session = Depends(get_db), user: User = Depends(require_client)):
    _own_project_or_404(db, user, project_id)
    # Double filter (project + client) — defence in depth. Only finished links.
    pls = (
        db.query(Placement)
        .filter(
            Placement.client_project_id == project_id,
            Placement.client_id == user.client_id,
            Placement.status.in_(["placed", "done"]),
        )
        .order_by(Placement.placed_at.desc()).all()
    )
    return [
        {
            "id": pl.id,
            "target_url": pl.target_url,
            "anchor_text": pl.anchor_text,
            "donor_domain": extract_domain(pl.donor_url),
            "result_url": pl.result_url,
            "status": pl.status,
            "placed_at": iso_utc(pl.placed_at),
        }
        for pl in pls
    ]

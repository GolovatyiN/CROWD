from datetime import datetime
from typing import Optional
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_super_admin
from ..database import get_db
from ..models import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
    action: Optional[str] = None,
    actor_id: Optional[int] = None,
    target_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_id is not None:
        q = q.filter(AuditLog.actor_id == actor_id)
    if target_id is not None:
        q = q.filter(AuditLog.target_id == target_id)
    if date_from:
        try: q = q.filter(AuditLog.created_at >= datetime.fromisoformat(date_from))
        except ValueError: pass
    if date_to:
        try: q = q.filter(AuditLog.created_at <= datetime.fromisoformat(date_to))
        except ValueError: pass

    total = q.with_entities(__import__("sqlalchemy").func.count(AuditLog.id)).scalar() or 0
    rows = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(min(limit, 500)).all()
    return {
        "total": total,
        "items": [{
            "id": r.id,
            "actor_id": r.actor_id,
            "actor_email": r.actor_email,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "target_label": r.target_label,
            "details": _parse_details(r.details),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
    }


def _parse_details(s: str) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {"raw": s[:200]}

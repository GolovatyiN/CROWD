"""In-app notifications API — each user sees only their own."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_staff
from ..database import get_db
from ..models import Notification, User
from ..utils import iso_utc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(require_staff),
    only_unread: bool = False,
    limit: int = 50,
):
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if only_unread:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.created_at.desc()).limit(min(limit, 200)).all()
    unread = db.query(func.count(Notification.id)).filter(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    ).scalar() or 0
    return {
        "unread": unread,
        "items": [
            {
                "id": n.id, "type": n.type, "severity": n.severity,
                "entity_type": n.entity_type, "entity_id": n.entity_id,
                "title": n.title, "body": n.body, "is_read": n.is_read,
                "created_at": iso_utc(n.created_at),
            }
            for n in rows
        ],
    }


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Не найдено")
    n.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    ).update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"ok": True}

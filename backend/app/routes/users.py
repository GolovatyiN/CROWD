from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..auth import ADMIN_ROLES, ALL_ROLES, get_current_user, hash_password, require_admin, require_super_admin
from ..database import get_db
from ..models import AuditLog, User
from ..schemas import UserCreate, UserOut, UserUpdate
from ..services import audit

router = APIRouter(prefix="/users", tags=["users"])


USER_SORT_FIELDS = {
    "id": User.id,
    "email": User.email,
    "full_name": User.full_name,
    "role": User.role,
    "is_active": User.is_active,
    "created_at": User.created_at,
}


def _count_super_admins(db: Session) -> int:
    return db.query(func.count(User.id)).filter(
        User.role == "super_admin", User.is_active.is_(True)
    ).scalar() or 0


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
    q: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort: str = "id",
    order: str = "asc",
):
    """Admins (and Super-Admins) can see the user roster — needed for the
    assignment dropdown. Everything that mutates a user still requires
    Super-Admin.
    """
    query = db.query(User)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(
            func.lower(User.email).like(like),
            func.lower(User.full_name).like(like),
        ))
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active.is_(is_active))
    sort_col = USER_SORT_FIELDS.get(sort.lower(), User.id)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    return query.order_by(direction).all()


@router.post("", response_model=UserOut)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    if payload.role not in ALL_ROLES:
        raise HTTPException(status_code=400, detail=f"Неизвестная роль: {payload.role}")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Сотрудник с таким email уже существует")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role or "user",
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit.log(db, actor, "user.create", target=user, role=user.role)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    changes: dict = {}

    if payload.full_name is not None and payload.full_name != user.full_name:
        changes["full_name"] = {"from": user.full_name, "to": payload.full_name}
        user.full_name = payload.full_name

    if payload.role is not None and payload.role != user.role:
        if payload.role not in ALL_ROLES:
            raise HTTPException(status_code=400, detail=f"Неизвестная роль: {payload.role}")
        # Refuse to demote the last Super-Admin — would lock the org out of
        # user management.
        if user.role == "super_admin" and payload.role != "super_admin":
            if _count_super_admins(db) <= 1:
                raise HTTPException(status_code=400, detail="Нельзя понизить последнего Super Admin")
        changes["role"] = {"from": user.role, "to": payload.role}
        user.role = payload.role

    if payload.is_active is not None and payload.is_active != user.is_active:
        if user.role == "super_admin" and not payload.is_active:
            if _count_super_admins(db) <= 1:
                raise HTTPException(status_code=400, detail="Нельзя деактивировать последнего Super Admin")
        changes["is_active"] = {"from": user.is_active, "to": payload.is_active}
        user.is_active = payload.is_active

    if payload.password:
        user.password_hash = hash_password(payload.password)
        changes["password"] = "changed"

    if changes:
        action = "user.role_change" if "role" in changes else (
            "user.activate" if changes.get("is_active", {}).get("to") is True else
            "user.deactivate" if changes.get("is_active", {}).get("to") is False else
            "user.update"
        )
        audit.log(db, actor, action, target=user, changes=changes)

    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать собственный аккаунт")
    if user.role == "super_admin" and _count_super_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать последнего Super Admin")
    if user.is_active:
        user.is_active = False
        audit.log(db, actor, "user.deactivate", target=user)
        db.commit()
    return {"ok": True}

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, hash_password, require_admin
from ..database import get_db
from ..models import User
from ..schemas import UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


USER_SORT_FIELDS = {
    "id": User.id,
    "email": User.email,
    "full_name": User.full_name,
    "role": User.role,
    "is_active": User.is_active,
    "created_at": User.created_at,
}


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    sort: str = "id",
    order: str = "asc",
):
    sort_col = USER_SORT_FIELDS.get(sort.lower(), User.id)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    return db.query(User).order_by(direction).all()


@router.post("", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Сотрудник с таким email уже существует")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role or "employee",
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать собственный аккаунт")
    user.is_active = False
    db.commit()
    return {"ok": True}

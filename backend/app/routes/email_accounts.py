from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_admin
from ..database import get_db
from ..models import EmailAccount, Placement, User
from ..schemas import EmailAccountCreate, EmailAccountOut, EmailAccountUpdate

router = APIRouter(prefix="/email-accounts", tags=["email_accounts"])


SORT_FIELDS = {
    "id": EmailAccount.id,
    "email": EmailAccount.email,
    "label": EmailAccount.label,
    "is_active": EmailAccount.is_active,
    "assigned_to": EmailAccount.assigned_to,
    "created_at": EmailAccount.created_at,
}


def _to_out(acc: EmailAccount, usage_map: dict[str, int], names: dict[int, str]) -> dict:
    data = EmailAccountOut.model_validate(acc).model_dump(mode="json")
    data["usage_count"] = usage_map.get(acc.email, 0)
    data["assignee_name"] = names.get(acc.assigned_to) if acc.assigned_to else None
    return data


@router.get("")
def list_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    assigned_to: Optional[int] = None,
    sort: str = "id",
    order: str = "asc",
):
    """Admins see every account. Regular users see only what's been issued to
    them plus the shared pool (assigned_to IS NULL) — that's what they can use
    when placing.
    """
    query = db.query(EmailAccount)

    is_admin = user.role in ("admin", "super_admin")
    if not is_admin:
        query = query.filter(or_(
            EmailAccount.assigned_to == user.id,
            EmailAccount.assigned_to.is_(None),
        ))
    elif assigned_to is not None:
        query = query.filter(EmailAccount.assigned_to == assigned_to)

    if q:
        like = f"%{q.lower()}%"
        query = query.filter(or_(
            func.lower(EmailAccount.email).like(like),
            func.lower(EmailAccount.label).like(like),
        ))
    if is_active is not None:
        query = query.filter(EmailAccount.is_active.is_(is_active))

    sort_col = SORT_FIELDS.get(sort.lower(), EmailAccount.id)
    direction = sort_col.desc() if order.lower() == "desc" else sort_col.asc()
    accounts = query.order_by(direction).all()

    usage_rows = db.execute(
        select(Placement.login_email, func.count(Placement.id))
        .where(Placement.login_email != "")
        .group_by(Placement.login_email)
    ).all()
    usage_map = {email: cnt for email, cnt in usage_rows}

    # Resolve assignee names in one query.
    assignee_ids = {a.assigned_to for a in accounts if a.assigned_to}
    names: dict[int, str] = {}
    if assignee_ids:
        for u in db.query(User).filter(User.id.in_(assignee_ids)).all():
            names[u.id] = u.full_name or u.email

    return [_to_out(a, usage_map, names) for a in accounts]


def _name_for(db: Session, user_id: Optional[int]) -> dict[int, str]:
    if not user_id:
        return {}
    u = db.get(User, user_id)
    return {user_id: (u.full_name or u.email)} if u else {}


@router.post("", response_model=EmailAccountOut)
def create_account(
    payload: EmailAccountCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    if not payload.email.strip():
        raise HTTPException(status_code=400, detail="Email обязателен")
    if db.query(EmailAccount).filter(EmailAccount.email.ilike(payload.email)).first():
        raise HTTPException(status_code=400, detail="Аккаунт с таким email уже есть")
    if payload.assigned_to and not db.get(User, payload.assigned_to):
        raise HTTPException(status_code=400, detail="Сотрудник не найден")
    acc = EmailAccount(
        email=payload.email.strip(),
        password=payload.password,
        label=payload.label,
        comment=payload.comment,
        is_active=payload.is_active,
        assigned_to=payload.assigned_to,
        created_by=actor.id,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return _to_out(acc, {}, _name_for(db, acc.assigned_to))


@router.patch("/{account_id}", response_model=EmailAccountOut)
def update_account(
    account_id: int,
    payload: EmailAccountUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    data = payload.model_dump(exclude_unset=True)
    if data.get("assigned_to") and not db.get(User, data["assigned_to"]):
        raise HTTPException(status_code=400, detail="Сотрудник не найден")
    for k, v in data.items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)
    return _to_out(acc, {}, _name_for(db, acc.assigned_to))


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    db.delete(acc)
    db.commit()
    return {"ok": True}

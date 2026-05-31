from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import EmailAccount, Placement, User
from ..schemas import EmailAccountCreate, EmailAccountOut, EmailAccountUpdate

router = APIRouter(prefix="/email-accounts", tags=["email_accounts"])


SORT_FIELDS = {
    "id": EmailAccount.id,
    "email": EmailAccount.email,
    "label": EmailAccount.label,
    "is_active": EmailAccount.is_active,
    "created_at": EmailAccount.created_at,
}


def _to_out(acc: EmailAccount, usage_map: dict[str, int]) -> dict:
    data = EmailAccountOut.model_validate(acc).model_dump(mode="json")
    data["usage_count"] = usage_map.get(acc.email, 0)
    return data


@router.get("")
def list_accounts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    q: Optional[str] = None,
    is_active: Optional[bool] = None,
    sort: str = "id",
    order: str = "asc",
):
    """All authenticated users see the shared pool — needed for the
    placement form's autocomplete. Only admins can mutate (enforced
    on the mutating endpoints).
    """
    query = db.query(EmailAccount)
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

    # how many placements used each email — handy "popularity" hint
    usage_rows = db.execute(
        select(Placement.login_email, func.count(Placement.id))
        .where(Placement.login_email != "")
        .group_by(Placement.login_email)
    ).all()
    usage_map = {email: cnt for email, cnt in usage_rows}
    return [_to_out(a, usage_map) for a in accounts]


@router.post("", response_model=EmailAccountOut)
def create_account(
    payload: EmailAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not payload.email.strip():
        raise HTTPException(status_code=400, detail="Email обязателен")
    existing = db.query(EmailAccount).filter(EmailAccount.email.ilike(payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Аккаунт с таким email уже есть")
    acc = EmailAccount(
        email=payload.email.strip(),
        password=payload.password,
        label=payload.label,
        comment=payload.comment,
        is_active=payload.is_active,
        created_by=user.id,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return _to_out(acc, {})


@router.patch("/{account_id}", response_model=EmailAccountOut)
def update_account(
    account_id: int,
    payload: EmailAccountUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)
    return _to_out(acc, {})


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    db.delete(acc)
    db.commit()
    return {"ok": True}

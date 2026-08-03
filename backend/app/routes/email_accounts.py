from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..auth import INTERNAL_ROLES, get_current_user, require_admin
from ..database import get_db
from ..models import Donor, DonorAccount, EmailAccount, Placement, User
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


def _to_out(acc: EmailAccount, usage_map: dict[str, int], names: dict[int, str],
            donors_map: dict[int, int] | None = None) -> dict:
    data = EmailAccountOut.model_validate(acc).model_dump(mode="json")
    data["usage_count"] = usage_map.get(acc.email, 0)
    data["donors_used"] = (donors_map or {}).get(acc.id, 0)   # distinct donors this mailbox served
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

    # Distinct donors each mailbox has served (via the pool ↔ donor link).
    donor_rows = db.execute(
        select(DonorAccount.email_account_id, func.count(func.distinct(DonorAccount.donor_id)))
        .where(DonorAccount.email_account_id.isnot(None))
        .group_by(DonorAccount.email_account_id)
    ).all()
    donors_map = {eaid: cnt for eaid, cnt in donor_rows}

    # Resolve assignee names in one query.
    assignee_ids = {a.assigned_to for a in accounts if a.assigned_to}
    names: dict[int, str] = {}
    if assignee_ids:
        for u in db.query(User).filter(User.id.in_(assignee_ids)).all():
            names[u.id] = u.full_name or u.email

    return [_to_out(a, usage_map, names, donors_map) for a in accounts]


@router.get("/stats/by-employee")
def stats_by_employee(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Per-employee mailbox picture: how many mailboxes are pinned to each
    person, how many are still active, how many distinct donors those mailboxes
    have served, and how many placements the person has done. Feeds the
    «По сотрудникам» view on the Accounts screen.
    """
    # Mailboxes assigned to each employee (total + active).
    mb_rows = db.execute(
        select(
            EmailAccount.assigned_to,
            func.count(EmailAccount.id),
            func.sum(case((EmailAccount.is_active.is_(True), 1), else_=0)),
        )
        .where(EmailAccount.assigned_to.isnot(None))
        .group_by(EmailAccount.assigned_to)
    ).all()
    assigned_map = {uid: (total, active or 0) for uid, total, active in mb_rows}

    # Distinct donors served through each employee's assigned mailboxes.
    donor_rows = db.execute(
        select(EmailAccount.assigned_to, func.count(func.distinct(DonorAccount.donor_id)))
        .join(DonorAccount, DonorAccount.email_account_id == EmailAccount.id)
        .where(EmailAccount.assigned_to.isnot(None))
        .group_by(EmailAccount.assigned_to)
    ).all()
    donors_map = {uid: cnt for uid, cnt in donor_rows}

    # Placements made by each employee.
    placement_rows = db.execute(
        select(Placement.employee_id, func.count(Placement.id))
        .where(Placement.status == "placed", Placement.employee_id.isnot(None))
        .group_by(Placement.employee_id)
    ).all()
    placements_map = {uid: cnt for uid, cnt in placement_rows}

    users = (
        db.query(User)
        .filter(User.role.in_(INTERNAL_ROLES))
        .order_by(User.full_name.asc())
        .all()
    )
    out = []
    for u in users:
        total, active = assigned_map.get(u.id, (0, 0))
        placed = placements_map.get(u.id, 0)
        # Skip staff with no mailboxes and no placements — noise.
        if not total and not placed:
            continue
        out.append({
            "user_id": u.id,
            "name": u.full_name or u.email,
            "email": u.email,
            "role": u.role,
            "assigned_mailboxes": total,
            "active_mailboxes": active,
            "donors_covered": donors_map.get(u.id, 0),
            "placements": placed,
        })
    out.sort(key=lambda r: (r["assigned_mailboxes"], r["placements"]), reverse=True)
    return out


@router.get("/{account_id}/donors")
def account_donors(
    account_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Which donors a given mailbox has been used on (via the pool ↔ donor link)."""
    acc = db.get(EmailAccount, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Аккаунт не найден")
    rows = (
        db.query(Donor.id, Donor.domain, DonorAccount.account_username, DonorAccount.is_active)
        .join(DonorAccount, DonorAccount.donor_id == Donor.id)
        .filter(DonorAccount.email_account_id == account_id)
        .order_by(Donor.domain.asc())
        .all()
    )
    return {
        "email": acc.email,
        "donors": [
            {"donor_id": did, "domain": domain, "account_username": username, "is_active": bool(active)}
            for did, domain, username, active in rows
        ],
    }


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

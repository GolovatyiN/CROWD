from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

# bcrypt cost 10 (~2^10 rounds) — still well above brute-force concern for an
# internal tool, but ~4x faster to verify than the passlib default of 12, which
# was adding noticeable latency to every login on a shared vCPU. `deprecated`
# marks any hash whose cost differs as upgradable, so old cost-12 hashes get
# transparently re-hashed to cost-10 on the next successful login.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=10)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def verify_and_maybe_rehash(plain: str, hashed: str) -> tuple[bool, Optional[str]]:
    """Verify a password and, if its stored hash uses an outdated cost factor,
    return a freshly computed hash so the caller can upgrade it in place.

    Returns (ok, new_hash_or_None). `new_hash` is None when the existing hash
    is already current (the common case after the first login).
    """
    try:
        return pwd_context.verify_and_update(plain, hashed)
    except Exception:
        return False, None


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется вход в систему")
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен")
    user_id = int(payload.get("sub", 0))
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user


ADMIN_ROLES = ("admin", "super_admin")
MANAGER_ROLES = ("manager", "admin", "super_admin")
# Every internal role — explicitly EXCLUDES the external 'client'. Anything an
# employee/teamlead/manager/admin may touch uses this; clients can never pass it.
INTERNAL_ROLES = ("user", "teamlead", "manager", "admin", "super_admin")
ALL_ROLES = INTERNAL_ROLES + ("client",)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Admin OR Super Admin — typical day-to-day management actions."""
    if user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только администратору")
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """Super-Admin only — user management, role changes, audit log."""
    if user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно только Super Admin")
    return user


def require_manager(user: User = Depends(get_current_user)) -> User:
    """Manager / Admin / Super-Admin — clients, projects, work distribution."""
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступно менеджеру и выше")
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    """Any INTERNAL role — hard gate that rejects external clients. Use on every
    endpoint that exposes internal data (donors, stop-list, tasks, …)."""
    if user.role not in INTERNAL_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Раздел недоступен")
    return user


def require_client(user: User = Depends(get_current_user)) -> User:
    """External client only. Must be tied to a Client (client_id). Every /client/*
    endpoint additionally filters queries by this user's client_id."""
    if user.role != "client" or not user.client_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Только для клиентского кабинета")
    return user

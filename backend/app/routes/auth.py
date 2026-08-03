from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import (
    create_access_token,
    get_current_user,
    get_or_create_demo_user,
    verify_and_maybe_rehash,
)
from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/demo-login", response_model=TokenResponse)
def demo_login(db: Session = Depends(get_db)):
    """Open-access demo: hand out a shared super-admin token with no credentials.
    Active only when settings.demo_open_access is on; otherwise 404 (as if the
    route didn't exist), so normal deployments are unaffected."""
    if not settings.demo_open_access:
        raise HTTPException(status_code=404, detail="Not found")
    user = get_or_create_demo_user(db)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    ok, new_hash = verify_and_maybe_rehash(payload.password, user.password_hash)
    if not ok:
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    # Upgrade a legacy (higher-cost) hash to the current cost on the fly.
    if new_hash:
        user.password_hash = new_hash
        db.commit()
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout():
    # Stateless JWT — client just discards the token.
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

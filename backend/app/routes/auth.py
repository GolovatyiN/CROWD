from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import create_access_token, get_current_user, verify_password
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
def logout():
    # Stateless JWT — client just discards the token.
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

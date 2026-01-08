"""
Auth endpoints: register, login, me.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, TokenResponse, UserPublic
from app.core.jwt_utils import create_access_token
from app.core.database import get_db
from app.services.user_service import UserService


router = APIRouter()


@router.post("/register", response_model=AuthResponse, status_code=201)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = UserService.create_user(
        db,
        email=payload.email,
        username=payload.username,
        password=payload.password,
    )
    token, expires_in = create_access_token(str(user.id))
    return AuthResponse(
        user=user,
        token=TokenResponse(access_token=token, expires_in=expires_in),
    )


@router.post("/login", response_model=AuthResponse)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = UserService.authenticate(db, payload.identifier, payload.password)
    UserService.mark_login(db, user)
    token, expires_in = create_access_token(str(user.id))
    return AuthResponse(
        user=user,
        token=TokenResponse(access_token=token, expires_in=expires_in),
    )


@router.get("/me", response_model=UserPublic)
def get_me(
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> UserPublic:
    user = UserService.get_by_id(db, account_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

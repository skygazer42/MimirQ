"""
Auth schemas for user registration and login.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.api.schemas.base import OrmModel


class UserPublic(OrmModel):
    id: UUID
    email: EmailStr
    username: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    identifier: str
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(BaseModel):
    user: UserPublic
    token: TokenResponse

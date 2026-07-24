"""
Auth schemas for user registration and login.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.api.schemas.base import OrmModel


class UserPublic(OrmModel):
    id: UUID
    email: EmailStr
    username: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    # bcrypt only supports up to 72 bytes for passwords.
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    identifier: str
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    # OAuth token type literal, not a credential.
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


class AuthResponse(BaseModel):
    user: UserPublic
    token: TokenResponse


class SamlExchangeRequest(BaseModel):
    provider_id: str | None = None
    saml_response: str
    relay_state: str | None = None
    acs_url: str | None = None
    bridge_mode: bool = False


class SamlBridgeConsumeRequest(BaseModel):
    code: str


class SamlExchangeResponse(AuthResponse):
    return_to: str = "/"
    bridge_code: str | None = None

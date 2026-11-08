"""
Auth schemas for user registration and login.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Header
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.dataclasses import dataclass

from app.api.schemas.base import OrmModel


@dataclass
class AuthHeaders:
    """Request header types and defaults shared by application and metrics auth."""

    authorization: Annotated[str | None, Header()] = None
    x_user_id: Annotated[str | None, Header()] = None
    x_tenant_id: Annotated[str | None, Header()] = None


class JwtIdentity(BaseModel):
    """Identity claims from an already verified JWT; external subjects remain strings."""

    user_id: str
    tenant_id: UUID | None = None

    @field_validator("user_id", mode="before")
    @classmethod
    def parse_user_id(cls, value):
        if not value:
            raise ValueError("JWT subject is required")
        user_id = str(value).strip()
        if not user_id:
            raise ValueError("JWT subject is required")
        return user_id

    @field_validator("tenant_id", mode="before")
    @classmethod
    def parse_tenant_id(cls, value):
        return UUID(str(value).strip()) if value is not None else None

    @classmethod
    def from_payload(cls, payload, tenant_claim):
        return cls(
            user_id=payload.get("sub"),
            tenant_id=payload.get(tenant_claim) if tenant_claim else None,
        )


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


class SignupRequest(RegisterRequest):
    """Ordinary signup never accepts caller-selected roles or tenant IDs."""

    model_config = ConfigDict(extra="forbid")


class AuthPolicy(BaseModel):
    initialized: bool
    registration_enabled: bool
    bootstrap_enabled: bool
    bootstrap_token_required: bool
    password_min_length: int


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

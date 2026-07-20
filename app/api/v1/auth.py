"""
Auth endpoints: register, login, me.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    SamlExchangeRequest,
    SamlExchangeResponse,
    TokenResponse,
    UserPublic,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.jwt_utils import create_access_token
from app.services.saml_service import build_saml_sp_metadata_xml, exchange_saml_response
from app.services.user_service import UserService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/register", status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def register_user(payload: RegisterRequest, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    """Bootstrap the first tenant owner and return an access token."""
    user = UserService.create_user(
        db,
        email=payload.email,
        username=payload.username,
        password=payload.password,
    )
    tenant_id = None
    if str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip():
        current_tenant = UserService.get_current_tenant_id(db, user_id=str(user.id))
        tenant_id = str(current_tenant) if current_tenant else None
    token, expires_in = create_access_token(str(user.id), tenant_id=tenant_id)
    return AuthResponse(
        user=user,
        token=TokenResponse(access_token=token, expires_in=expires_in),
    )


@router.post("/login", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def login_user(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    """Authenticate a user and issue an access token."""
    user = UserService.authenticate(db, payload.identifier, payload.password)
    UserService.mark_login(db, user)
    tenant_id = None
    if str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip():
        current_tenant = UserService.get_current_tenant_id(db, user_id=str(user.id))
        tenant_id = str(current_tenant) if current_tenant else None
    token, expires_in = create_access_token(str(user.id), tenant_id=tenant_id)
    return AuthResponse(
        user=user,
        token=TokenResponse(access_token=token, expires_in=expires_in),
    )


@router.get("/me", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_me(
    *,
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> UserPublic:
    """Return the authenticated user's public profile."""
    user = UserService.get_by_id(db, account_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/saml/exchange", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def saml_exchange(payload: SamlExchangeRequest, db: Annotated[Session, Depends(get_db)]) -> SamlExchangeResponse:
    """Exchange a SAML response for an application session."""
    return exchange_saml_response(
        db=db,
        provider_id=payload.provider_id,
        saml_response=payload.saml_response,
        relay_state=payload.relay_state,
        acs_url=payload.acs_url,
    )


@router.get("/saml/metadata", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def saml_metadata(provider_id: str | None = None) -> Response:
    """Return SAML service-provider metadata XML."""
    xml = build_saml_sp_metadata_xml(provider_id=provider_id)
    resp = Response(content=xml, media_type="application/samlmetadata+xml; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp

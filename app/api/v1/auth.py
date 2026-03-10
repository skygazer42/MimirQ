"""
Auth endpoints: register, login, me.
"""

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

router = APIRouter()


@router.post("/register", response_model=AuthResponse, status_code=201)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
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


@router.post("/login", response_model=AuthResponse)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
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


@router.get("/me", response_model=UserPublic)
def get_me(
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
) -> UserPublic:
    user = UserService.get_by_id(db, account_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/saml/exchange", response_model=SamlExchangeResponse)
def saml_exchange(payload: SamlExchangeRequest, db: Session = Depends(get_db)) -> SamlExchangeResponse:
    return exchange_saml_response(
        db=db,
        provider_id=payload.provider_id,
        saml_response=payload.saml_response,
        relay_state=payload.relay_state,
        acs_url=payload.acs_url,
    )


@router.get("/saml/metadata")
def saml_metadata(provider_id: str | None = None) -> Response:
    xml = build_saml_sp_metadata_xml(provider_id=provider_id)
    resp = Response(content=xml, media_type="application/samlmetadata+xml; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp

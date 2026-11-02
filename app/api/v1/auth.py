"""
Auth endpoints: register, login, me.
"""

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    SamlBridgeConsumeRequest,
    SamlExchangeRequest,
    SamlExchangeResponse,
    TokenResponse,
    UserPublic,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.env import is_production_env
from app.core.jwt_utils import create_access_token
from app.models.user import User
from app.services.saml_bridge_service import (
    consume_saml_bridge_session,
    issue_saml_bridge_session,
    saml_bridge_session_from_exchange,
    saml_bridge_session_to_exchange,
)
from app.services.saml_service import build_saml_sp_metadata_xml, exchange_saml_response
from app.services.user_service import (
    authenticate_user,
    create_user,
    get_current_tenant_id,
    get_default_tenant_member_count,
    get_user_by_id,
    mark_login,
)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
_BOOTSTRAP_TOKEN_HEADER = "X-Bootstrap-Token"


def _bootstrap_token_matches(provided_token: str, expected_token: str) -> bool:
    expected = expected_token.strip()
    provided = provided_token.strip()
    if not expected or not provided:
        return False
    if expected.lower().startswith("sha256:"):
        digest = expected.split(":", 1)[1].strip().lower()
        if not digest:
            return False
        provided_digest = hashlib.sha256(provided.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided, expected)


def _require_initial_registration_token(*, db: Session, bootstrap_token: str | None) -> None:
    if not is_production_env():
        return
    if get_default_tenant_member_count(db, default_tenant_id=settings.DEFAULT_TENANT_ID) != 0:
        return
    if _bootstrap_token_matches(bootstrap_token or "", settings.INITIAL_REGISTRATION_TOKEN):
        return
    raise HTTPException(status_code=403, detail="Initial registration bootstrap token required")


def _build_auth_response(db: Session, user: User) -> AuthResponse:
    tenant_id = None
    if settings.JWT_TENANT_CLAIM.strip():
        current_tenant = get_current_tenant_id(db, user_id=str(user.id))
        tenant_id = str(current_tenant) if current_tenant else None
    token, expires_in = create_access_token(str(user.id), tenant_id=tenant_id)
    return AuthResponse(
        user=user,
        token=TokenResponse(access_token=token, expires_in=expires_in),
    )


@router.post("/register", status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def register_user(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    bootstrap_token: Annotated[str | None, Header(alias=_BOOTSTRAP_TOKEN_HEADER)] = None,
) -> AuthResponse:
    """Bootstrap the first tenant owner and return an access token."""
    _require_initial_registration_token(db=db, bootstrap_token=bootstrap_token)
    user = create_user(
        db,
        email=payload.email,
        username=payload.username,
        password=payload.password,
        password_min_length=settings.PASSWORD_MIN_LENGTH,
        default_tenant_id=settings.DEFAULT_TENANT_ID,
    )
    return _build_auth_response(db, user)


@router.post("/login", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def login_user(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    """Authenticate a user and issue an access token."""
    user = authenticate_user(db, payload.identifier, payload.password)
    mark_login(db, user)
    return _build_auth_response(db, user)


@router.get("/me", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_me(
    *,
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> UserPublic:
    """Return the authenticated user's public profile."""
    user = get_user_by_id(db, account_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/saml/exchange", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def saml_exchange(payload: SamlExchangeRequest, db: Annotated[Session, Depends(get_db)]) -> SamlExchangeResponse:
    """Exchange a SAML response for an application session."""
    session = exchange_saml_response(
        db=db,
        provider_id=payload.provider_id,
        saml_response=payload.saml_response,
        relay_state=payload.relay_state,
        acs_url=payload.acs_url,
    )
    if not payload.bridge_mode:
        return session
    return session.model_copy(
        update={"bridge_code": issue_saml_bridge_session(saml_bridge_session_from_exchange(session))}
    )


@router.post("/saml/bridge/consume", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def saml_bridge_consume(payload: SamlBridgeConsumeRequest) -> SamlExchangeResponse:
    """Redeem a one-time SAML bridge code for an application session."""
    return saml_bridge_session_to_exchange(consume_saml_bridge_session(payload.code))


@router.get("/saml/metadata", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def saml_metadata(provider_id: str | None = None) -> Response:
    """Return SAML service-provider metadata XML."""
    xml = build_saml_sp_metadata_xml(provider_id=provider_id)
    resp = Response(content=xml, media_type="application/samlmetadata+xml; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp

from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.external_conversation import (
    ExternalConversationIngestRequest,
    ExternalConversationIngestResponse,
)
from app.core.database import get_db
from app.services.external_conversation_ingest import ingest_external_conversation

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/ingest",
    response_model=ExternalConversationIngestResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def ingest_conversation_history(
    request_body: ExternalConversationIngestRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ExternalConversationIngestResponse:
    """Import externally generated chat turns into the standard MimirQ history."""
    request_id = getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
    client = http_request.client
    return ingest_external_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request_body,
        request_id=str(request_id),
        ip=client.host if client else None,
        user_agent=http_request.headers.get("user-agent"),
    )

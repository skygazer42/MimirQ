from concurrent.futures import ThreadPoolExecutor
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.integrations import (
    ExternalConversationAsyncIngestResponse,
    ExternalConversationIngestRequest,
    ExternalConversationIngestResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import SessionLocal, get_db
from app.rag.core.logging import get_logger
from app.services.external_conversation_ingest import ingest_external_conversation

logger = get_logger(__name__)

_ASYNC_INGEST_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="external-conversation-ingest")


router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _wants_async_ingest(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on", "async"}


def _run_external_conversation_ingest_background(
    *,
    tenant_id: UUID,
    account_id: str,
    request_body: ExternalConversationIngestRequest,
    request_id: str,
    ip: str | None,
    user_agent: str | None,
) -> None:
    with SessionLocal() as db:
        try:
            ingest_external_conversation(
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                request=request_body,
                request_id=request_id,
                ip=ip,
                user_agent=user_agent,
            )
        except Exception:
            logger.exception(
                "Background external conversation ingest failed: source=%s source_conversation_id=%s request_id=%s",
                request_body.source,
                request_body.source_conversation_id,
                request_id,
            )


@router.post(
    "/ingest",
    response_model=ExternalConversationIngestResponse | ExternalConversationAsyncIngestResponse,
)
def ingest_conversation_history(
    request_body: ExternalConversationIngestRequest,
    http_request: Request,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ExternalConversationIngestResponse | ExternalConversationAsyncIngestResponse:
    """Import externally generated chat turns into the standard Ragvia history."""
    request_id = http_request.state.request_id
    client = http_request.client
    ip = client.host if client is not None else None
    user_agent = http_request.headers.get("user-agent")
    if _wants_async_ingest(http_request.headers.get("x-mimirq-async-ingest")):
        _ASYNC_INGEST_EXECUTOR.submit(
            _run_external_conversation_ingest_background,
            tenant_id=tenant_id,
            account_id=account_id,
            request_body=request_body.model_copy(deep=True),
            request_id=request_id,
            ip=ip,
            user_agent=user_agent,
        )
        return ExternalConversationAsyncIngestResponse(
            request_id=request_id,
            source=request_body.source,
            source_conversation_id=request_body.source_conversation_id,
        )
    return ingest_external_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        request=request_body,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent,
    )

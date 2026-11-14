from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from langgraph.types import StateSnapshot
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import (
    CheckpointDetailResponse,
    CheckpointListResponse,
    ConversationSummaryResponse,
    ConversationSummaryUpdateResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import Conversation
from app.rag.trace_schema import RagTraceListResponse
from app.services.chat_conversation_access import ensure_conversation_access
from app.services.conversation_summary_service import (
    clear_conversation_summary,
    get_conversation_summary,
    update_conversation_summary,
)
from app.services.dataset_service import ensure_member
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session
from app.services.rag_trace_service import list_rag_traces

CONVERSATION_NOT_FOUND_DETAIL = "Conversation not found"

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _ensure_conversation_access(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    conversation_id: UUID,
) -> None:
    ensure_member(db, tenant_id, account_id)
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id).first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)
    ensure_conversation_access(db, tenant_id, account_id, conversation)


def _checkpoint_payload(snapshot: StateSnapshot, *, include_values: bool) -> dict[str, Any]:
    config = snapshot.config["configurable"]
    payload = {
        "checkpoint_id": config["checkpoint_id"],
        "checkpoint_ns": config["checkpoint_ns"],
        "created_at": snapshot.created_at,
        "next": snapshot.next,
        "metadata": snapshot.metadata,
    }
    if include_values:
        payload["values"] = {name: value for name, value in snapshot.values.items() if name != "docs"}
    return jsonable_encoder(payload)


@router.get(
    "/conversations/{conversation_id}/summary",
    response_model=ConversationSummaryResponse,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_conversation_summary_endpoint(
    conversation_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_conversation_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )

    summary = get_conversation_summary(db, tenant_id=tenant_id, conversation_id=conversation_id)
    return {"available": bool(summary), "summary": summary}


@router.post(
    "/conversations/{conversation_id}/summary/update",
    response_model=ConversationSummaryUpdateResponse,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def update_conversation_summary_endpoint(
    conversation_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    if not settings.PERSISTENT_SUMMARY_MEMORY_ENABLED:
        raise HTTPException(status_code=400, detail="Persistent summary memory is disabled")

    await run_blocking_call_with_managed_session(
        lambda worker_db: _ensure_conversation_access(
            worker_db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=conversation_id,
        ),
        request_db=db,
    )

    summary = await update_conversation_summary(db, tenant_id=tenant_id, conversation_id=conversation_id)
    return {"summary": summary}


@router.delete(
    "/conversations/{conversation_id}/summary",
    status_code=204,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def delete_conversation_summary_endpoint(
    conversation_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    _ensure_conversation_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )

    clear_conversation_summary(db, tenant_id=tenant_id, conversation_id=conversation_id)


@router.get(
    "/conversations/{conversation_id}/rag-traces",
    response_model=RagTraceListResponse,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_conversation_rag_traces(
    conversation_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    window_minutes: Annotated[int, Query(ge=1, le=7 * 24 * 60)] = 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 5_000_000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List recent RAG traces for a conversation (PII-safe) so the UI can visualize
    retrieve/rerank/citations steps.
    """
    _ensure_conversation_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )

    return list_rag_traces(
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        limit=limit,
        window_minutes=window_minutes,
        max_bytes=max_bytes,
    )


@router.get(
    "/conversations/{conversation_id}/checkpoints",
    response_model=CheckpointListResponse,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_conversation_checkpoints(
    conversation_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    before: Annotated[str | None, Query()] = None,
    include_values: Annotated[bool, Query()] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List LangGraph checkpoints for this conversation (time-travel/debug)."""
    _ensure_conversation_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )

    from app.rag.pipelines.langgraph import build_rag_graph

    graph = build_rag_graph()
    thread_id = str(conversation_id)
    base_config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    before_config = (
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": before}} if before else None
    )

    snapshots = list(graph.get_state_history(base_config, before=before_config, limit=limit))
    return {
        "thread_id": thread_id,
        "items": [_checkpoint_payload(snap, include_values=include_values) for snap in reversed(snapshots)],
    }


@router.get(
    "/conversations/{conversation_id}/checkpoints/{checkpoint_id}",
    response_model=CheckpointDetailResponse,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_conversation_checkpoint(
    conversation_id: UUID,
    checkpoint_id: str,
    include_values: Annotated[bool, Query()] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get a checkpoint snapshot (docs are excluded by default)."""
    _ensure_conversation_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )

    from app.rag.pipelines.langgraph import build_rag_graph

    graph = build_rag_graph()
    thread_id = str(conversation_id)
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "", "checkpoint_id": checkpoint_id}}
    snap = graph.get_state(config)
    if snap.created_at is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    return {"thread_id": thread_id, **_checkpoint_payload(snap, include_values=include_values)}


@router.delete(
    "/conversations/{conversation_id}/checkpoints",
    status_code=204,
    responses=DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def delete_conversation_checkpoints(
    conversation_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Clear checkpoints for this conversation (does not delete messages or the conversation)."""
    _ensure_conversation_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
    )

    from app.rag.checkpointer.factory import get_checkpointer

    saver = get_checkpointer()
    saver.delete_thread(str(conversation_id))

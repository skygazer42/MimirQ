"""
Usage / cost endpoints (admin-only).

Focus: low-friction, DB-backed aggregates for chat token usage.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Float, Integer, cast, func
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.system import ChatUsageSummaryQuery
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.chat import Message
from app.services.quota_service import check_chat_assistant_token_quota
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.tenant_quota_service import (
    check_tenant_document_quota,
    check_tenant_embedding_char_quota,
    check_tenant_storage_quota,
    get_tenant_qps_quota_config,
)

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _ensure_admin(db: Session, tenant_id: UUID, account_id: str) -> None:
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.USAGE_READ,
        detail="No permission to access usage dashboards",
    )


class ChatTokenUsageRow(BaseModel):
    dataset_id: str | None = None
    assistant_messages: int
    assistant_tokens: int


class ChatTokenUsageSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    total_assistant_messages: int
    total_assistant_tokens: int
    by_dataset: list[ChatTokenUsageRow]


class ChatCostUsageRow(BaseModel):
    dataset_id: str | None = None
    assistant_messages: int
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    embedding_query_tokens: int
    embedding_query_chars: int
    retrieval_elapsed_sec_sum: float
    rerank_elapsed_sec_sum: float


class ChatCostUsageSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    total_assistant_messages: int
    total_llm_prompt_tokens: int
    total_llm_completion_tokens: int
    total_llm_total_tokens: int
    total_embedding_query_tokens: int
    total_embedding_query_chars: int
    total_retrieval_elapsed_sec: float
    total_rerank_elapsed_sec: float
    by_dataset: list[ChatCostUsageRow]


class ChatTokenQuotaStatus(BaseModel):
    enabled: bool
    mode: str
    limit: int
    used: int
    remaining: int
    exceeded: bool
    window_hours: int
    window_start: datetime
    window_end: datetime


class TenantDocumentQuotaStatus(BaseModel):
    enabled: bool
    limit: int
    used: int
    remaining: int
    exceeded: bool


class TenantStorageQuotaStatus(BaseModel):
    enabled: bool
    limit_bytes: int
    used_bytes: int
    remaining_bytes: int
    exceeded: bool


class TenantEmbeddingCharQuotaStatus(BaseModel):
    enabled: bool
    mode: str
    limit_chars: int
    used_chars: int
    remaining_chars: int
    exceeded: bool
    window_hours: int
    window_start: datetime
    window_end: datetime


class TenantQpsQuotaConfig(BaseModel):
    enabled: bool
    mode: str
    rps: float
    burst: int
    scopes: list[str]


class TenantQuotaSummary(BaseModel):
    documents: TenantDocumentQuotaStatus
    storage: TenantStorageQuotaStatus
    embedding_chars: TenantEmbeddingCharQuotaStatus
    qps: TenantQpsQuotaConfig


@router.get("/chat/tokens/quota", response_model=ChatTokenQuotaStatus)
def get_chat_token_quota_status(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatTokenQuotaStatus:
    """
    Return the current rolling assistant-token quota status for this tenant.

    Intended for admin dashboards and operational visibility.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(UTC)
    quota = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    return ChatTokenQuotaStatus(
        **quota,
        remaining=max(0, quota["limit"] - quota["used"]) if quota["enabled"] else 0,
        window_start=now - timedelta(hours=max(1, quota["window_hours"])),
        window_end=now,
    )


@router.get("/tenant/quotas", response_model=TenantQuotaSummary)
def get_tenant_quota_summary(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> TenantQuotaSummary:
    """
    Return tenant quota status (docs/storage/embedding/QPS).

    Intended for admin dashboards and operational visibility. All fields are
    PII-safe aggregates.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(UTC)

    document_quota = check_tenant_document_quota(db, tenant_id=tenant_id)
    documents = TenantDocumentQuotaStatus(
        enabled=document_quota["enabled"],
        limit=document_quota["limit"] if document_quota["enabled"] else 0,
        used=document_quota["used"] if document_quota["enabled"] else 0,
        remaining=max(0, document_quota["limit"] - document_quota["used"]) if document_quota["enabled"] else 0,
        exceeded=document_quota["exceeded"],
    )

    storage_quota = check_tenant_storage_quota(db, tenant_id=tenant_id)
    storage = TenantStorageQuotaStatus(
        enabled=storage_quota["enabled"],
        limit_bytes=storage_quota["limit_bytes"] if storage_quota["enabled"] else 0,
        used_bytes=storage_quota["used_bytes"] if storage_quota["enabled"] else 0,
        remaining_bytes=max(0, storage_quota["limit_bytes"] - storage_quota["used_bytes"])
        if storage_quota["enabled"]
        else 0,
        exceeded=storage_quota["exceeded"],
    )

    embedding_quota = check_tenant_embedding_char_quota(db, tenant_id=tenant_id)
    embedding_window_hours = max(1, embedding_quota["window_hours"])
    embedding_chars = TenantEmbeddingCharQuotaStatus(
        enabled=embedding_quota["enabled"],
        mode=embedding_quota["mode"],
        limit_chars=embedding_quota["limit_chars"] if embedding_quota["enabled"] else 0,
        used_chars=embedding_quota["used_chars"] if embedding_quota["enabled"] else 0,
        remaining_chars=max(0, embedding_quota["limit_chars"] - embedding_quota["used_chars"])
        if embedding_quota["enabled"]
        else 0,
        exceeded=embedding_quota["exceeded"],
        window_hours=embedding_window_hours,
        window_start=now - timedelta(hours=embedding_window_hours),
        window_end=now,
    )

    qps_config = get_tenant_qps_quota_config()

    return TenantQuotaSummary(
        documents=documents,
        storage=storage,
        embedding_chars=embedding_chars,
        qps=TenantQpsQuotaConfig(
            **qps_config,
            scopes=["chat", "retrieval"],
        ),
    )


@router.get("/chat/tokens/summary", response_model=ChatTokenUsageSummary)
def get_chat_token_usage_summary(
    query: Annotated[ChatUsageSummaryQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatTokenUsageSummary:
    """
    Summarize assistant token usage grouped by dataset_id (when available).

    Notes:
    - dataset_id is stored in Message.message_metadata by chat endpoints when request scope maps to a single dataset.
    - For multi-dataset chats (or legacy rows), dataset_id may be null.
    """
    _ensure_admin(db, tenant_id, account_id)

    window_start, window_end = query.resolve_window(datetime.now(UTC))

    # Postgres JSONB expression (used elsewhere in the codebase); safe in production deployments.
    dataset_expr = Message.message_metadata["dataset_id"].astext  # type: ignore[attr-defined]

    rows = (
        db.query(
            dataset_expr.label("dataset_id"),
            func.count(Message.id).label("assistant_messages"),
            func.coalesce(func.sum(Message.token_count), 0).label("assistant_tokens"),
        )
        .filter(
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
            Message.created_at >= window_start,
            Message.created_at <= window_end,
        )
        .group_by(dataset_expr)
        .order_by(func.coalesce(func.sum(Message.token_count), 0).desc())
        .all()
    )

    by_dataset = [ChatTokenUsageRow.model_validate(row._mapping) for row in rows]

    return ChatTokenUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=sum(item.assistant_messages for item in by_dataset),
        total_assistant_tokens=sum(item.assistant_tokens for item in by_dataset),
        by_dataset=by_dataset,
    )


@router.get("/chat/cost/summary", response_model=ChatCostUsageSummary)
def get_chat_cost_usage_summary(
    query: Annotated[ChatUsageSummaryQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatCostUsageSummary:
    """
    Summarize per-request cost attribution grouped by dataset_id (best-effort).

    Source of truth:
    - Cost attribution fields in `Message.message_metadata` written by chat/RAG engines.
    """
    _ensure_admin(db, tenant_id, account_id)

    window_start, window_end = query.resolve_window(datetime.now(UTC))

    dataset_expr = Message.message_metadata["dataset_id"].astext  # type: ignore[attr-defined]

    def integer_metadata(key: str) -> ColumnElement[int]:
        # `->>` returns NULL when missing; CAST(NULL AS int) is NULL; coalesce to 0.
        return func.coalesce(cast(Message.message_metadata[key].astext, Integer), 0)  # type: ignore[attr-defined]

    def float_metadata(key: str) -> ColumnElement[float]:
        return func.coalesce(cast(Message.message_metadata[key].astext, Float), 0.0)  # type: ignore[attr-defined]

    llm_prompt_tokens = integer_metadata("cost_llm_prompt_tokens")
    llm_completion_tokens = integer_metadata("cost_llm_completion_tokens")
    llm_total_tokens = integer_metadata("cost_llm_total_tokens")
    embedding_query_tokens = integer_metadata("cost_embedding_query_tokens")
    embedding_query_chars = integer_metadata("cost_embedding_query_chars")
    retrieval_elapsed_sec = float_metadata("cost_retrieval_elapsed_sec")
    rerank_elapsed_sec = float_metadata("cost_rerank_elapsed_sec")

    rows = (
        db.query(
            dataset_expr.label("dataset_id"),
            func.count(Message.id).label("assistant_messages"),
            func.coalesce(func.sum(llm_prompt_tokens), 0).label("llm_prompt_tokens"),
            func.coalesce(func.sum(llm_completion_tokens), 0).label("llm_completion_tokens"),
            func.coalesce(func.sum(llm_total_tokens), 0).label("llm_total_tokens"),
            func.coalesce(func.sum(embedding_query_tokens), 0).label("embedding_query_tokens"),
            func.coalesce(func.sum(embedding_query_chars), 0).label("embedding_query_chars"),
            func.coalesce(func.sum(retrieval_elapsed_sec), 0.0).label("retrieval_elapsed_sec_sum"),
            func.coalesce(func.sum(rerank_elapsed_sec), 0.0).label("rerank_elapsed_sec_sum"),
        )
        .filter(
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
            Message.created_at >= window_start,
            Message.created_at <= window_end,
        )
        .group_by(dataset_expr)
        .order_by(func.coalesce(func.sum(llm_total_tokens), 0).desc())
        .all()
    )

    by_dataset = [ChatCostUsageRow.model_validate(row._mapping) for row in rows]
    total_retrieval_elapsed_sec = 0.0
    total_rerank_elapsed_sec = 0.0
    for item in by_dataset:
        total_retrieval_elapsed_sec += item.retrieval_elapsed_sec_sum
        total_rerank_elapsed_sec += item.rerank_elapsed_sec_sum

    return ChatCostUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=sum(item.assistant_messages for item in by_dataset),
        total_llm_prompt_tokens=sum(item.llm_prompt_tokens for item in by_dataset),
        total_llm_completion_tokens=sum(item.llm_completion_tokens for item in by_dataset),
        total_llm_total_tokens=sum(item.llm_total_tokens for item in by_dataset),
        total_embedding_query_tokens=sum(item.embedding_query_tokens for item in by_dataset),
        total_embedding_query_chars=sum(item.embedding_query_chars for item in by_dataset),
        total_retrieval_elapsed_sec=total_retrieval_elapsed_sec,
        total_rerank_elapsed_sec=total_rerank_elapsed_sec,
        by_dataset=by_dataset,
    )

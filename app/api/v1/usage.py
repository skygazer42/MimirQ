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

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
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

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

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


@router.get("/chat/tokens/quota", response_model=ChatTokenQuotaStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
    meta = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    return ChatTokenQuotaStatus(
        **meta,
        remaining=max(0, meta["limit"] - meta["used"]) if meta["enabled"] else 0,
        window_start=now - timedelta(hours=max(1, meta["window_hours"])),
        window_end=now,
    )


@router.get("/tenant/quotas", response_model=TenantQuotaSummary, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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

    doc_meta = check_tenant_document_quota(db, tenant_id=tenant_id)
    documents = TenantDocumentQuotaStatus(
        enabled=doc_meta["enabled"],
        limit=doc_meta["limit"] if doc_meta["enabled"] else 0,
        used=doc_meta["used"] if doc_meta["enabled"] else 0,
        remaining=max(0, doc_meta["limit"] - doc_meta["used"]) if doc_meta["enabled"] else 0,
        exceeded=doc_meta["exceeded"],
    )

    storage_meta = check_tenant_storage_quota(db, tenant_id=tenant_id)
    storage = TenantStorageQuotaStatus(
        enabled=storage_meta["enabled"],
        limit_bytes=storage_meta["limit_bytes"] if storage_meta["enabled"] else 0,
        used_bytes=storage_meta["used_bytes"] if storage_meta["enabled"] else 0,
        remaining_bytes=max(0, storage_meta["limit_bytes"] - storage_meta["used_bytes"])
        if storage_meta["enabled"]
        else 0,
        exceeded=storage_meta["exceeded"],
    )

    embed_meta = check_tenant_embedding_char_quota(db, tenant_id=tenant_id)
    embed_window_hours = max(1, embed_meta["window_hours"])
    embedding_chars = TenantEmbeddingCharQuotaStatus(
        enabled=embed_meta["enabled"],
        mode=embed_meta["mode"],
        limit_chars=embed_meta["limit_chars"] if embed_meta["enabled"] else 0,
        used_chars=embed_meta["used_chars"] if embed_meta["enabled"] else 0,
        remaining_chars=max(0, embed_meta["limit_chars"] - embed_meta["used_chars"]) if embed_meta["enabled"] else 0,
        exceeded=embed_meta["exceeded"],
        window_hours=embed_window_hours,
        window_start=now - timedelta(hours=embed_window_hours),
        window_end=now,
    )

    qps_cfg = get_tenant_qps_quota_config()

    return TenantQuotaSummary(
        documents=documents,
        storage=storage,
        embedding_chars=embedding_chars,
        qps=TenantQpsQuotaConfig(
            **qps_cfg,
            scopes=["chat", "retrieval"],
        ),
    )


@router.get("/chat/tokens/summary", response_model=ChatTokenUsageSummary, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_chat_token_usage_summary(
    window_days: Annotated[int, Query(ge=1, le=30)] = 1,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
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

    now = datetime.now(UTC)
    window_end = until if until else now
    window_start = since if since else window_end - timedelta(days=int(window_days or 1))

    # Postgres JSONB expression (used elsewhere in the codebase); safe in production deployments.
    dataset_expr = Message.message_metadata["dataset_id"].astext  # type: ignore[attr-defined]

    rows = (
        db.query(
            dataset_expr.label("dataset_id"),
            func.count(Message.id).label("messages"),
            func.coalesce(func.sum(Message.token_count), 0).label("tokens"),
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

    items: list[ChatTokenUsageRow] = []
    total_messages = 0
    total_tokens = 0
    for dataset_id, message_count, token_count in rows:
        usage_row = ChatTokenUsageRow(
            dataset_id=str(dataset_id) if dataset_id is not None else None,
            assistant_messages=int(message_count or 0),
            assistant_tokens=int(token_count or 0),
        )
        items.append(usage_row)
        total_messages += usage_row.assistant_messages
        total_tokens += usage_row.assistant_tokens

    return ChatTokenUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=total_messages,
        total_assistant_tokens=total_tokens,
        by_dataset=items,
    )


@router.get("/chat/cost/summary", response_model=ChatCostUsageSummary, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_chat_cost_usage_summary(
    window_days: Annotated[int, Query(ge=1, le=30)] = 1,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
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

    now = datetime.now(UTC)
    window_end = until if until else now
    window_start = since if since else window_end - timedelta(days=int(window_days or 1))

    dataset_expr = Message.message_metadata["dataset_id"].astext  # type: ignore[attr-defined]

    def _int_meta(key: str):
        # `->>` returns NULL when missing; CAST(NULL AS int) is NULL; coalesce to 0.
        return func.coalesce(cast(Message.message_metadata[key].astext, Integer), 0)  # type: ignore[attr-defined]

    def _float_meta(key: str):
        return func.coalesce(cast(Message.message_metadata[key].astext, Float), 0.0)  # type: ignore[attr-defined]

    llm_prompt = _int_meta("cost_llm_prompt_tokens")
    llm_completion = _int_meta("cost_llm_completion_tokens")
    llm_total = _int_meta("cost_llm_total_tokens")
    embed_tokens = _int_meta("cost_embedding_query_tokens")
    embed_chars = _int_meta("cost_embedding_query_chars")
    retrieval_sec = _float_meta("cost_retrieval_elapsed_sec")
    rerank_sec = _float_meta("cost_rerank_elapsed_sec")

    rows = (
        db.query(
            dataset_expr.label("dataset_id"),
            func.count(Message.id).label("messages"),
            func.coalesce(func.sum(llm_prompt), 0).label("llm_prompt_tokens"),
            func.coalesce(func.sum(llm_completion), 0).label("llm_completion_tokens"),
            func.coalesce(func.sum(llm_total), 0).label("llm_total_tokens"),
            func.coalesce(func.sum(embed_tokens), 0).label("embedding_query_tokens"),
            func.coalesce(func.sum(embed_chars), 0).label("embedding_query_chars"),
            func.coalesce(func.sum(retrieval_sec), 0.0).label("retrieval_elapsed_sec_sum"),
            func.coalesce(func.sum(rerank_sec), 0.0).label("rerank_elapsed_sec_sum"),
        )
        .filter(
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
            Message.created_at >= window_start,
            Message.created_at <= window_end,
        )
        .group_by(dataset_expr)
        .order_by(func.coalesce(func.sum(llm_total), 0).desc())
        .all()
    )

    items: list[ChatCostUsageRow] = []
    total_messages = 0
    total_llm_prompt = 0
    total_llm_completion = 0
    total_llm_total = 0
    total_embed_tokens = 0
    total_embed_chars = 0
    total_retrieval_sec = 0.0
    total_rerank_sec = 0.0

    for (
        dataset_id,
        messages,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        embedding_tokens,
        embedding_chars,
        retrieval_elapsed,
        rerank_elapsed,
    ) in rows:
        usage_row = ChatCostUsageRow(
            dataset_id=str(dataset_id) if dataset_id is not None else None,
            assistant_messages=int(messages or 0),
            llm_prompt_tokens=int(prompt_tokens or 0),
            llm_completion_tokens=int(completion_tokens or 0),
            llm_total_tokens=int(total_tokens or 0),
            embedding_query_tokens=int(embedding_tokens or 0),
            embedding_query_chars=int(embedding_chars or 0),
            retrieval_elapsed_sec_sum=float(retrieval_elapsed or 0.0),
            rerank_elapsed_sec_sum=float(rerank_elapsed or 0.0),
        )
        items.append(usage_row)
        total_messages += usage_row.assistant_messages
        total_llm_prompt += usage_row.llm_prompt_tokens
        total_llm_completion += usage_row.llm_completion_tokens
        total_llm_total += usage_row.llm_total_tokens
        total_embed_tokens += usage_row.embedding_query_tokens
        total_embed_chars += usage_row.embedding_query_chars
        total_retrieval_sec += usage_row.retrieval_elapsed_sec_sum
        total_rerank_sec += usage_row.rerank_elapsed_sec_sum

    return ChatCostUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=total_messages,
        total_llm_prompt_tokens=total_llm_prompt,
        total_llm_completion_tokens=total_llm_completion,
        total_llm_total_tokens=total_llm_total,
        total_embedding_query_tokens=total_embed_tokens,
        total_embedding_query_chars=total_embed_chars,
        total_retrieval_elapsed_sec=total_retrieval_sec,
        total_rerank_elapsed_sec=total_rerank_sec,
        by_dataset=items,
    )

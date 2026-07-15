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
):
    """
    Return the current rolling assistant-token quota status for this tenant.

    Intended for admin dashboards and operational visibility.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(UTC)
    meta = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    enabled = bool(meta.get("enabled"))
    limit = int(meta.get("limit") or 0)
    used = int(meta.get("used") or 0)
    window_hours = int(meta.get("window_hours") or 24)
    mode = str(meta.get("mode") or "block")
    exceeded = bool(meta.get("exceeded")) if enabled else False
    remaining = max(0, limit - used) if enabled and limit > 0 else 0
    window_start = now - timedelta(hours=max(1, window_hours))
    return ChatTokenQuotaStatus(
        enabled=enabled,
        mode=mode,
        limit=limit,
        used=used,
        remaining=remaining,
        exceeded=exceeded,
        window_hours=window_hours,
        window_start=window_start,
        window_end=now,
    )


@router.get("/tenant/quotas", response_model=TenantQuotaSummary, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_tenant_quota_summary(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Return tenant quota status (docs/storage/embedding/QPS).

    Intended for admin dashboards and operational visibility. All fields are
    PII-safe aggregates.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(UTC)

    doc_meta = check_tenant_document_quota(db, tenant_id=tenant_id)
    doc_enabled = bool(doc_meta.get("enabled"))
    doc_limit = int(doc_meta.get("limit") or 0)
    doc_used = int(doc_meta.get("used") or 0)
    doc_exceeded = bool(doc_meta.get("exceeded")) if doc_enabled else False
    doc_remaining = max(0, doc_limit - doc_used) if doc_enabled and doc_limit > 0 else 0

    storage_meta = check_tenant_storage_quota(db, tenant_id=tenant_id)
    storage_enabled = bool(storage_meta.get("enabled"))
    storage_limit = int(storage_meta.get("limit_bytes") or 0)
    storage_used = int(storage_meta.get("used_bytes") or 0)
    storage_exceeded = bool(storage_meta.get("exceeded")) if storage_enabled else False
    storage_remaining = max(0, storage_limit - storage_used) if storage_enabled and storage_limit > 0 else 0

    embed_meta = check_tenant_embedding_char_quota(db, tenant_id=tenant_id)
    embed_enabled = bool(embed_meta.get("enabled"))
    embed_limit = int(embed_meta.get("limit_chars") or 0)
    embed_used = int(embed_meta.get("used_chars") or 0)
    embed_mode = str(embed_meta.get("mode") or "block")
    embed_window_hours = int(embed_meta.get("window_hours") or 24)
    embed_window_hours = max(1, embed_window_hours)
    embed_exceeded = bool(embed_meta.get("exceeded")) if embed_enabled else False
    embed_remaining = max(0, embed_limit - embed_used) if embed_enabled and embed_limit > 0 else 0
    embed_window_start = now - timedelta(hours=embed_window_hours)

    qps_cfg = get_tenant_qps_quota_config()

    return TenantQuotaSummary(
        documents=TenantDocumentQuotaStatus(
            enabled=doc_enabled,
            limit=doc_limit if doc_enabled else 0,
            used=doc_used if doc_enabled else 0,
            remaining=doc_remaining if doc_enabled else 0,
            exceeded=doc_exceeded,
        ),
        storage=TenantStorageQuotaStatus(
            enabled=storage_enabled,
            limit_bytes=storage_limit if storage_enabled else 0,
            used_bytes=storage_used if storage_enabled else 0,
            remaining_bytes=storage_remaining if storage_enabled else 0,
            exceeded=storage_exceeded,
        ),
        embedding_chars=TenantEmbeddingCharQuotaStatus(
            enabled=embed_enabled,
            mode=embed_mode,
            limit_chars=embed_limit if embed_enabled else 0,
            used_chars=embed_used if embed_enabled else 0,
            remaining_chars=embed_remaining if embed_enabled else 0,
            exceeded=embed_exceeded,
            window_hours=embed_window_hours,
            window_start=embed_window_start,
            window_end=now,
        ),
        qps=TenantQpsQuotaConfig(
            enabled=bool(qps_cfg.get("enabled")),
            mode=str(qps_cfg.get("mode") or "block"),
            rps=float(qps_cfg.get("rps") or 0.0),
            burst=int(qps_cfg.get("burst") or 0),
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
):
    """
    Summarize assistant token usage grouped by dataset_id (when available).

    Notes:
    - dataset_id is stored in Message.message_metadata by chat endpoints when request scope maps to a single dataset.
    - For multi-dataset chats (or legacy rows), dataset_id may be null.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(UTC)
    window_end = until or now
    window_start = since or (window_end - timedelta(days=int(window_days or 1)))

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
    total_msgs = 0
    total_tokens = 0
    for ds_id, messages, tokens in rows:
        m = int(messages or 0)
        t = int(tokens or 0)
        total_msgs += m
        total_tokens += t
        items.append(
            ChatTokenUsageRow(
                dataset_id=str(ds_id) if ds_id is not None else None,
                assistant_messages=m,
                assistant_tokens=t,
            )
        )

    return ChatTokenUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=total_msgs,
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
):
    """
    Summarize per-request cost attribution grouped by dataset_id (best-effort).

    Source of truth:
    - Cost attribution fields in `Message.message_metadata` written by chat/RAG engines.
    """
    _ensure_admin(db, tenant_id, account_id)

    now = datetime.now(UTC)
    window_end = until or now
    window_start = since or (window_end - timedelta(days=int(window_days or 1)))

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
    total_msgs = 0
    total_llm_prompt = 0
    total_llm_completion = 0
    total_llm_total = 0
    total_embed_tokens = 0
    total_embed_chars = 0
    total_retrieval_sec = 0.0
    total_rerank_sec = 0.0

    for (
        ds_id,
        messages,
        p_tokens,
        c_tokens,
        t_tokens,
        e_tokens,
        e_chars,
        r_sec,
        rr_sec,
    ) in rows:
        m = int(messages or 0)
        p = int(p_tokens or 0)
        c = int(c_tokens or 0)
        t = int(t_tokens or 0)
        et = int(e_tokens or 0)
        ec = int(e_chars or 0)
        rs = float(r_sec or 0.0)
        rrs = float(rr_sec or 0.0)

        total_msgs += m
        total_llm_prompt += p
        total_llm_completion += c
        total_llm_total += t
        total_embed_tokens += et
        total_embed_chars += ec
        total_retrieval_sec += rs
        total_rerank_sec += rrs

        items.append(
            ChatCostUsageRow(
                dataset_id=str(ds_id) if ds_id is not None else None,
                assistant_messages=m,
                llm_prompt_tokens=p,
                llm_completion_tokens=c,
                llm_total_tokens=t,
                embedding_query_tokens=et,
                embedding_query_chars=ec,
                retrieval_elapsed_sec_sum=rs,
                rerank_elapsed_sec_sum=rrs,
            )
        )

    return ChatCostUsageSummary(
        window_start=window_start,
        window_end=window_end,
        total_assistant_messages=total_msgs,
        total_llm_prompt_tokens=total_llm_prompt,
        total_llm_completion_tokens=total_llm_completion,
        total_llm_total_tokens=total_llm_total,
        total_embedding_query_tokens=total_embed_tokens,
        total_embedding_query_chars=total_embed_chars,
        total_retrieval_elapsed_sec=total_retrieval_sec,
        total_rerank_elapsed_sec=total_rerank_sec,
        by_dataset=items,
    )

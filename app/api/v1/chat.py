"""
Chat API.
"""
import asyncio
import contextlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langchain_community.retrievers.bm25 import BM25Retriever
from langchain_core.documents import Document
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import (
    ChatRequest,
    ChatResponse,
)
from app.api.v1 import chat_conversation_memory, chat_conversations
from app.core.config import settings
from app.core.database import get_db
from app.core.env import is_production_env
from app.core.stream_events import StreamEmitter, bind_stream_emitter, reset_stream_emitter
from app.core.token_utils import num_tokens_from_string
from app.models.chat import Conversation, Message
from app.rag.core.text import parse_json_from_text
from app.rag.engine import get_rag_engine
from app.rag.preprocessing.tokenization import tokenize_for_bm25
from app.services.audit_log_service import audit_log_event, build_chat_audit_details
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_AUTO,
)
from app.services.chat_conversation_titles import (
    CONVERSATION_TITLE_SOURCE_MANUAL as CONVERSATION_TITLE_SOURCE_MANUAL,
)
from app.services.chat_conversation_titles import (
    apply_auto_conversation_title as _apply_auto_conversation_title,
)
from app.services.chat_response_cache import (
    acquire_inflight_chat_response,
    get_cached_chat_response,
    reject_inflight_chat_response,
    resolve_chat_response_cache_key,
    resolve_inflight_chat_response,
    set_cached_chat_response,
)
from app.services.chat_scope import enforce_non_empty_chat_scope as _enforce_non_empty_chat_scope
from app.services.conversation_summary_service import (
    get_conversation_summary,
    update_conversation_summary,
)
from app.services.dataset_defaults import load_dataset_metadata, resolve_single_dataset_id_for_documents
from app.services.dataset_service import DatasetService
from app.services.document_access import (
    filter_allowed_document_ids,
    get_allowed_document_id_sets,
)
from app.services.metrics_logger import log_metrics, set_metrics_context
from app.services.prompt_defaults import merge_prompt_defaults_with_dataset
from app.services.quota_service import check_chat_assistant_token_quota
from app.services.rag_config_template_apply import apply_rag_config_patch
from app.services.rag_config_template_defaults import merge_rag_config_template_defaults_with_dataset
from app.services.rag_config_template_resolver import (
    build_adaptive_routing_reward_writeback,
    build_rag_config_patch_hash,
    resolve_rag_config_template,
)
from app.services.rag_defaults import merge_rag_config_with_dataset_defaults
from app.services.structured_memory_service import build_structured_memory_context, extract_structured_memory_for_turn

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _spawn_background_task(coro: Any) -> None:
    """
    Best-effort fire-and-forget task runner.

    Sonar rule python:S7502: keep a strong reference to background tasks until completion.
    """
    try:
        task = asyncio.create_task(coro)
    except Exception:
        with contextlib.suppress(Exception):
            coro.close()
        return

    _BACKGROUND_TASKS.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _BACKGROUND_TASKS.discard(t)
        with contextlib.suppress(asyncio.CancelledError, Exception):
            exc = t.exception()
            if exc is not None:
                logger.warning("Background task failed: %s", str(exc)[:200])

    task.add_done_callback(_done)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
router.include_router(chat_conversation_memory.router)
router.include_router(chat_conversations.router)

CONVERSATION_NOT_FOUND_DETAIL = "Conversation not found"
DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL = "dataset_id is required when document_ids is empty"
DOC_IDS_MUST_MATCH_DATASET_DETAIL = "document_ids must all belong to the specified dataset_id"
NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL = "No accessible documents for chat retrieval"
CHAT_STREAM_AUDIT_ACTION = "chat.stream"


def _annotate_chat_cache_metrics(
    metrics: dict[str, Any] | None,
    *,
    enabled: bool,
    hit: bool,
    skip_reason: str | None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    out["chat_cache_enabled"] = bool(enabled)
    out["chat_cache_hit"] = bool(hit)
    if skip_reason:
        out["chat_cache_skip_reason"] = str(skip_reason)
    else:
        out.pop("chat_cache_skip_reason", None)
    return out


def _annotate_chat_singleflight_metrics(
    metrics: dict[str, Any] | None,
    *,
    enabled: bool,
    hit: bool,
    role: str | None = None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    out["chat_singleflight_enabled"] = bool(enabled)
    out["chat_singleflight_hit"] = bool(hit)
    if role:
        out["chat_singleflight_role"] = str(role)
    else:
        out.pop("chat_singleflight_role", None)
    return out


def _build_chat_message_metadata(
    *,
    request_id: str,
    original_question: str | None,
    metrics: dict[str, Any] | None,
    citations: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    out = dict(metrics or {})
    out["request_id"] = str(request_id)

    rewritten = str((out.get("query_for_retrieval") or "")).strip()
    question = str(original_question or "").strip()
    out["rewritten_query"] = rewritten if rewritten and rewritten != question else None

    retrieved_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in citations or []:
        if not isinstance(item, dict):
            continue
        document_id = item.get("document_id")
        document_name = item.get("document_name") or item.get("source")
        chunk_id = item.get("chunk_id")
        page_number = item.get("page_number")
        key = str(document_id or document_name or chunk_id or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        retrieved_docs.append(
            {
                "document_id": str(document_id) if document_id is not None else None,
                "document_name": str(document_name) if document_name is not None else None,
                "chunk_id": str(chunk_id) if chunk_id is not None else None,
                "page_number": int(page_number) if page_number is not None else None,
            }
        )
        if len(retrieved_docs) >= 20:
            break
    out["retrieved_docs"] = retrieved_docs

    latency_keys = (
        "latency_ms",
        "elapsed_sec",
        "retrieval_elapsed_sec",
        "generation_elapsed_sec",
        "rewrite_elapsed_sec",
        "multi_query_elapsed_sec",
        "hyde_elapsed_sec",
        "decompose_elapsed_sec",
    )
    latency_stats = {
        key: out.get(key)
        for key in latency_keys
        if out.get(key) is not None
    }
    out["latency_stats"] = latency_stats
    return out


@dataclass(frozen=True)
class ChatCacheLookupInput:
    db: Session
    tenant_id: UUID
    account_id: str
    dataset_id: UUID | None
    document_ids: list[UUID]
    history: list[Any]
    enable_long_term_memory: bool
    long_term_messages: list[dict]
    enable_structured_memory: bool
    question: str
    rag_config: dict[str, Any]
    prompt_config: dict[str, Any]
    structured_output: bool
    structured_preset: str | None
    use_graph: bool


@dataclass(frozen=True)
class ChatStreamPersistInput:
    tenant_id: UUID
    conversation_id: UUID
    account_id: str
    assistant_message_id: UUID
    request_id: str
    question: str
    document_count: int
    content: str
    citations: list
    metrics: dict
    dataset_id_used: UUID | None
    cache_hit: bool
    cache_key: str | None
    cache_eligible: bool
    structured_data: object | None
    ip: str | None
    user_agent: str | None
    enable_summary_memory: bool
    enable_structured_memory: bool


def _resolve_chat_cache_lookup_input(
    *,
    options: ChatCacheLookupInput | None,
    legacy_overrides: dict[str, Any],
) -> ChatCacheLookupInput:
    if options is None:
        return ChatCacheLookupInput(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(ChatCacheLookupInput, replace(options, **legacy_overrides))


def _resolve_chat_stream_persist_input(
    *,
    options: ChatStreamPersistInput | None,
    legacy_overrides: dict[str, Any],
) -> ChatStreamPersistInput:
    if options is None:
        return ChatStreamPersistInput(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(ChatStreamPersistInput, replace(options, **legacy_overrides))


def _prepare_chat_cache_lookup(
    *,
    options: ChatCacheLookupInput | None = None,
    **legacy_overrides: Any,
) -> tuple[bool, str | None, str | None]:
    lookup = _resolve_chat_cache_lookup_input(options=options, legacy_overrides=legacy_overrides)
    cache_enabled = bool(getattr(settings, "CHAT_RESPONSE_CACHE_ENABLED", False))
    if not cache_enabled:
        return False, None, None
    if not lookup.document_ids and lookup.dataset_id is None:
        return True, None, "missing_scope"
    if bool(getattr(settings, "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", True)):
        if (
            lookup.history
            or lookup.enable_long_term_memory
            or lookup.long_term_messages
            or lookup.enable_structured_memory
        ):
            return True, None, "history_not_empty"
    try:
        cache_key, skip_reason = resolve_chat_response_cache_key(
            db=lookup.db,
            tenant_id=lookup.tenant_id,
            account_id=lookup.account_id,
            dataset_id=lookup.dataset_id,
            document_ids=lookup.document_ids,
            question=lookup.question,
            rag_config=lookup.rag_config,
            prompt_config=lookup.prompt_config,
            structured_output=lookup.structured_output,
            structured_preset=lookup.structured_preset,
            use_graph=lookup.use_graph,
        )
    except Exception:
        return True, None, "lookup_error"
    return True, cache_key, skip_reason

async def _auto_update_summary_background(*, tenant_id: UUID, conversation_id: UUID) -> None:
    """
    Best-effort async background task to update persistent summary memory.

    Important: uses a new DB session to avoid holding request-scoped sessions after responses.
    """
    try:
        from app.core.database import SessionLocal  # noqa: WPS433

        db2 = SessionLocal()
        try:
            await update_conversation_summary(db2, tenant_id=tenant_id, conversation_id=conversation_id)
        finally:
            try:
                db2.close()
            except Exception:
                pass
    except Exception:
        return


async def _persist_chat_stream_turn_background(
    *,
    options: ChatStreamPersistInput | None = None,
    **legacy_overrides: Any,
) -> None:
    """
    Best-effort async background persistence for streaming chat.

    Why: reduce tail latency for SSE by not blocking on DB commit after sending "done".
    Trade-off: if the worker crashes after responding, the assistant message might not be persisted.
    """
    persist_input = _resolve_chat_stream_persist_input(options=options, legacy_overrides=legacy_overrides)
    tenant_id = persist_input.tenant_id
    conversation_id = persist_input.conversation_id
    account_id = persist_input.account_id
    assistant_message_id = persist_input.assistant_message_id
    request_id = persist_input.request_id
    question = persist_input.question
    document_count = persist_input.document_count
    content = persist_input.content
    citations = persist_input.citations
    metrics = persist_input.metrics
    dataset_id_used = persist_input.dataset_id_used
    cache_hit = persist_input.cache_hit
    cache_key = persist_input.cache_key
    cache_eligible = persist_input.cache_eligible
    structured_data = persist_input.structured_data
    ip = persist_input.ip
    user_agent = persist_input.user_agent
    enable_summary_memory = persist_input.enable_summary_memory
    enable_structured_memory = persist_input.enable_structured_memory

    should_update_summary = (
        bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
        and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
        and bool(enable_summary_memory)
        and bool(conversation_id)
    )

    def _persist_sync() -> bool:
        try:
            from app.core.database import SessionLocal  # noqa: WPS433

            db2 = SessionLocal()
            try:
                metrics2 = dict(metrics or {})
                # Optional: store response in Redis cache (best-effort).
                if cache_eligible and (not cache_hit) and cache_key and (content or "").strip():
                    cache_payload = jsonable_encoder(
                        {
                            "content": content,
                            "citations": citations if isinstance(citations, list) else [],
                            "metrics": metrics2,
                            "structured_data": structured_data,
                        }
                    )
                    stored = bool(set_cached_chat_response(cache_key, cache_payload))
                    metrics2.setdefault("chat_cache_store_ok", stored)

                message_metadata = _build_chat_message_metadata(
                    request_id=str(request_id),
                    original_question=question,
                    metrics=metrics2,
                    citations=citations if isinstance(citations, list) else [],
                )
                if enable_structured_memory and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False)):
                    try:
                        message_metadata["structured_memory"] = extract_structured_memory_for_turn(
                            user_text=str(question or ""),
                            assistant_text=str(content or ""),
                            max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                            max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                        )
                    except Exception:
                        pass

                assistant_message = Message(
                    id=assistant_message_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=content or "",
                    citations=citations if isinstance(citations, list) else [],
                    token_count=num_tokens_from_string(content or ""),
                    message_metadata=message_metadata,
                )
                db2.add(assistant_message)

                audit_log_event(
                    db2,
                    tenant_id=tenant_id,
                    actor_id=account_id,
                    action=CHAT_STREAM_AUDIT_ACTION,
                    resource_type="conversation",
                    resource_id=str(conversation_id),
                    request_id=str(request_id),
                    ip=ip,
                    user_agent=user_agent,
                    details=build_chat_audit_details(
                        question=question,
                        document_count=int(document_count or 0),
                        dataset_id=dataset_id_used,
                        cache_hit=cache_hit,
                    ),
                )

                conv = (
                    db2.query(Conversation)
                    .filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
                    .first()
                )
                if conv is not None:
                    conv.message_count = int(conv.message_count or 0) + 1
                    conv.updated_at = datetime.now(UTC).replace(tzinfo=None)

                db2.commit()
            finally:
                try:
                    db2.close()
                except Exception:
                    pass

            return True
        except Exception:
            return False

    ok = await asyncio.to_thread(_persist_sync)
    if not ok:
        return

    if should_update_summary:
        with contextlib.suppress(Exception):
            _spawn_background_task(
                _auto_update_summary_background(tenant_id=tenant_id, conversation_id=conversation_id)
            )


def _format_stream_error_message(exc: Exception) -> str:
    raw = str(exc) or exc.__class__.__name__
    raw = " ".join(raw.split())
    raw = re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-***", raw)
    raw = re.sub(r"(?i)bearer\\s+[A-Z0-9\\-_.]{8,}", "Bearer ***", raw)
    status_code = getattr(exc, "status_code", None)
    if status_code and isinstance(status_code, int):
        raw = f"HTTP {status_code}: {raw}"
    return raw.strip()


def _resolve_conversation_document_scope_for_chat(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    conv: Conversation,
) -> list[UUID]:
    if not conv.document_ids:
        return []
    doc_ids = list(conv.document_ids)
    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        doc_ids,
        check_member=False,
    )
    remaining = [doc_id for doc_id in doc_ids if doc_id not in missing_ids]
    if remaining != doc_ids:
        conv.document_ids = remaining
    allowed = [doc_id for doc_id in remaining if doc_id in allowed_ids]
    if allowed:
        return allowed
    if remaining:
        raise HTTPException(status_code=403, detail="No accessible documents for this request")
    raise HTTPException(
        status_code=409,
        detail="Conversation documents are no longer available; choose new documents or dataset scope",
    )


def _retrieve_long_term_messages(
    db: Session,
    conversation_id: UUID,
    tenant_id: UUID,
    query: str,
    top_k: int = 3
) -> list[dict]:
    """
    Simple long-term memory recall using BM25 over past messages.
    Used to enrich history context only; it does not modify storage.
    """
    max_messages = int(getattr(settings, "LONG_TERM_MEMORY_MAX_MESSAGES", 200) or 0)
    query_builder = (
        db.query(Message.content, Message.role, Message.created_at)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
        )
        .order_by(Message.created_at.desc())
    )
    if max_messages > 0:
        query_builder = query_builder.limit(max_messages)

    rows = query_builder.all()
    if not rows:
        return []

    rows = list(reversed(rows))

    docs: list[Document] = []
    for content, role, created_at in rows:
        if not content or len(content.strip()) < settings.LONG_TERM_MEMORY_MIN_LEN:
            continue
        docs.append(
            Document(
                page_content=content,
                metadata={
                    "role": role,
                    "created_at": created_at.isoformat() if created_at else None,
                }
            )
        )

    if not docs:
        return []

    retriever = BM25Retriever.from_documents(
        docs,
        preprocess_func=tokenize_for_bm25,
        k=top_k
    )
    selected = retriever.invoke(query)

    enriched_history = []
    for doc in selected:
        enriched_history.append(
            {
                "role": doc.metadata.get("role", "assistant"),
                "content": doc.page_content,
                "from_long_term": True,
                "ts": doc.metadata.get("created_at")
            }
        )
    return enriched_history


def _retrieve_structured_memory_records(
    *,
    db: Session,
    conversation_id: UUID,
    tenant_id: UUID,
    max_messages: int,
) -> list[dict[str, Any]]:
    """
    Retrieve structured memory records stored in Message.message_metadata.

    Notes:
    - Best-effort: only assistant messages can carry records (we write them there).
    - Keeps DB reads bounded by max_messages.
    """
    lim = max(0, int(max_messages or 0))
    if lim <= 0:
        return []
    rows = (
        db.query(Message.message_metadata)
        .filter(
            Message.conversation_id == conversation_id,
            Message.tenant_id == tenant_id,
            Message.role == "assistant",
        )
        .order_by(Message.created_at.desc())
        .limit(lim)
        .all()
    )
    out: list[dict[str, Any]] = []
    for (meta,) in rows:
        if not isinstance(meta, dict):
            continue
        rec = meta.get("structured_memory")
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _touch_conversation_after_turn(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_id: UUID | None,
) -> None:
    if conversation_id is None:
        return
    # Lightweight endpoint tests may inject a minimal fake DB with only
    # add/flush/commit; skip this best-effort touch update in that case.
    if not hasattr(db, "query"):
        return
    db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.tenant_id == tenant_id,
    ).update(
        {
            Conversation.message_count: func.coalesce(Conversation.message_count, 0) + 1,
            Conversation.updated_at: datetime.now(UTC).replace(tzinfo=None),
        },
        synchronize_session=False,
    )


@router.post("", response_model=ChatResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def chat(
    http_request: Request,
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Non-streaming chat endpoint.

    It mirrors the `/chat/stream` behavior, but returns a single JSON payload
    after the answer is ready.
    """
    conversation_id = request.conversation_id
    citations_data: list = []
    full_response = ""
    full_response_parts: list[str] = []
    allowed_doc_ids: list[UUID] = []
    long_term_messages: list[dict] = []
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))
    allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))

    # Tenant QPS quotas (Wave22-T094): per-tenant aggregate limiter (best-effort).
    from app.services.tenant_quota_service import enforce_tenant_qps_quota

    tenant_qps_meta = enforce_tenant_qps_quota(tenant_id=tenant_id, key="chat")

    quota_meta = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    if quota_meta.get("enabled") and quota_meta.get("exceeded") and quota_meta.get("mode") == "block":
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Chat quota exceeded (assistant tokens)",
                "retry_after_sec": None,
                "limit": int(quota_meta.get("limit") or 0),
                "scope": "chat_tokens",
            },
        )

    # 1) Load or create a conversation.
    #
    # IMPORTANT: we no longer enumerate "accessible document ids" as the default retrieval scope.
    # When document_ids is empty, retrieval runs in "open scope" (tenant-level) and is trimmed
    # on the candidate set inside the retriever (defense-in-depth, scalable for large corpora).
    scope_dataset_id: UUID | None = None
    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)

        if request.document_ids:
            # Explicit doc scope.
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
            conversation.document_ids = allowed_doc_ids
            conversation.dataset_id = None

            if request.dataset_id is not None and allowed_doc_ids:
                from app.models.document import Document as DBDocument  # noqa: WPS433

                rows = (
                    db.query(DBDocument.dataset_id)
                    .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(allowed_doc_ids))
                    .all()
                )
                ds_ids = {row[0] for row in rows if row and row[0] is not None}
                if ds_ids and ds_ids != {request.dataset_id}:
                    raise HTTPException(status_code=400, detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL)

        elif request.dataset_id is not None:
            # Explicit dataset scope.
            DatasetService.ensure_member(db, tenant_id, account_id)
            ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
            DatasetService.assert_dataset_readable(db, ds, account_id)

            scope_dataset_id = request.dataset_id
            conversation.dataset_id = request.dataset_id
            conversation.document_ids = []
            allowed_doc_ids = []

        elif conversation.document_ids:
            # Bound doc scope: re-validate each request.
            allowed_doc_ids = _resolve_conversation_document_scope_for_chat(
                db,
                tenant_id,
                account_id,
                conversation,
            )
            conversation.document_ids = allowed_doc_ids
            conversation.dataset_id = None

        else:
            # Bound dataset scope (or open scope if dataset_id is NULL).
            scope_dataset_id = getattr(conversation, "dataset_id", None)
            allowed_doc_ids = []
            if scope_dataset_id is None and not allow_open_scope:
                raise HTTPException(
                    status_code=400,
                    detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
                )

        if not allow_empty_docs:
            _enforce_non_empty_chat_scope(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                allowed_doc_ids=allowed_doc_ids,
                scope_dataset_id=scope_dataset_id,
                error_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
            )

    else:
        # Create new conversation.
        if request.document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
            scope_dataset_id = None

            if request.dataset_id is not None and allowed_doc_ids:
                from app.models.document import Document as DBDocument  # noqa: WPS433

                rows = (
                    db.query(DBDocument.dataset_id)
                    .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(allowed_doc_ids))
                    .all()
                )
                ds_ids = {row[0] for row in rows if row and row[0] is not None}
                if ds_ids and ds_ids != {request.dataset_id}:
                    raise HTTPException(status_code=400, detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL)

        elif request.dataset_id is not None:
            DatasetService.ensure_member(db, tenant_id, account_id)
            ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
            DatasetService.assert_dataset_readable(db, ds, account_id)
            scope_dataset_id = request.dataset_id
            allowed_doc_ids = []
        else:
            scope_dataset_id = None
            allowed_doc_ids = []
            if not allow_open_scope:
                raise HTTPException(
                    status_code=400,
                    detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
                )

        if not allow_empty_docs:
            _enforce_non_empty_chat_scope(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                allowed_doc_ids=allowed_doc_ids,
                scope_dataset_id=scope_dataset_id,
                error_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
            )

        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title_source=CONVERSATION_TITLE_SOURCE_AUTO,
            dataset_id=scope_dataset_id,
            document_ids=allowed_doc_ids,
        )
        _apply_auto_conversation_title(conversation, request.message)
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id

    # 2) Persist user message.
    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role="user",
        content=request.message,
        token_count=num_tokens_from_string(request.message or ""),
    )
    db.add(user_message)
    _apply_auto_conversation_title(conversation, request.message)

    # Optional: long-term memory recall (BM25 over conversation messages).
    if request.enable_long_term_memory and settings.LONG_TERM_MEMORY_ENABLED and conversation_id:
        long_term_messages = _retrieve_long_term_messages(
            db=db,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            query=request.message,
            top_k=settings.LONG_TERM_MEMORY_TOP_K,
        )

    # Update conversation message count for the user message.
    conversation.message_count = (conversation.message_count or 0) + 1
    db.commit()

    request_id = getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
    assistant_message_id = uuid.uuid4()
    set_metrics_context(
        request_id=str(request_id),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        account_id=account_id,
    )

    doc_ids_to_use = allowed_doc_ids or []

    # Dataset-level default RAG config (best-effort): apply only when all documents share one dataset_id.
    effective_rag_config = request.rag_config
    dataset_rag_defaults_applied_fields: list[str] = []
    dataset_defaults_meta: dict | None = None
    # If the conversation/request is explicitly scoped to a dataset, prefer it over
    # "infer from document_ids" logic.
    dataset_id_used: UUID | None = scope_dataset_id
    rag_fields_set = set(getattr(request.rag_config, "model_fields_set", set()) or set())
    if "rag_config" not in set(getattr(request, "model_fields_set", set()) or set()):
        rag_fields_set = set()
    try:
        if dataset_id_used is None:
            dataset_id_used = resolve_single_dataset_id_for_documents(
                db, tenant_id=tenant_id, document_ids=doc_ids_to_use
            )
        if dataset_id_used is not None:
            ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=dataset_id_used)
            dataset_defaults_meta = ds_meta if isinstance(ds_meta, dict) else None
            raw_defaults = ds_meta.get("rag_defaults") if isinstance(ds_meta, dict) else None
            effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
                rag_config=effective_rag_config,
                request_fields_set=rag_fields_set,
                raw_dataset_defaults=raw_defaults,
            )
    except Exception:
        # Never block chat due to per-dataset defaults parsing.
        dataset_rag_defaults_applied_fields = []
        dataset_defaults_meta = None
        dataset_id_used = scope_dataset_id

    # Dataset-level default prompt settings (best-effort).
    req_fields = set(getattr(request, "model_fields_set", set()) or set())
    (
        effective_prompt_template_id,
        effective_prompt_template_key,
        effective_prompt_ab_experiment_key,
        dataset_prompt_defaults_applied_fields,
    ) = merge_prompt_defaults_with_dataset(
        prompt_template_id=request.prompt_template_id,
        prompt_template_key=request.prompt_template_key,
        prompt_ab_experiment_key=request.prompt_ab_experiment_key,
        request_fields_set=req_fields,
        dataset_meta=dataset_defaults_meta,
    )

    # Dataset-level default RAG config template selectors + patch application (best-effort).
    (
        effective_rag_config_template_id,
        effective_rag_config_template_key,
        effective_rag_config_ab_experiment_key,
        dataset_rag_config_template_defaults_applied_fields,
    ) = merge_rag_config_template_defaults_with_dataset(
        rag_config_template_id=request.rag_config_template_id,
        rag_config_template_key=request.rag_config_template_key,
        rag_config_ab_experiment_key=request.rag_config_ab_experiment_key,
        request_fields_set=req_fields,
        dataset_meta=dataset_defaults_meta,
    )

    rag_config_template_meta: dict[str, Any] | None = None
    rag_config_template_resolver_debug: dict[str, Any] | None = None
    rag_config_template_patch_applied_fields: list[str] = []
    try:
        if (
            effective_rag_config_template_id
            or (effective_rag_config_template_key or "").strip()
            or (effective_rag_config_ab_experiment_key or "").strip()
        ):
            chosen, rag_config_template_resolver_debug = resolve_rag_config_template(
                db=db,
                tenant_id=tenant_id,
                rag_config_template_id=effective_rag_config_template_id,
                template_key=effective_rag_config_template_key,
                ab_experiment_key=effective_rag_config_ab_experiment_key,
                ab_user_key=account_id,
                return_debug_metadata=True,
            )
            if chosen:
                effective_rag_config, rag_config_template_patch_applied_fields = apply_rag_config_patch(
                    rag_config=effective_rag_config,
                    patch=getattr(chosen, "config_patch", None),
                    request_fields_set=rag_fields_set,
                )
                rag_config_template_meta = {
                    "template_id": str(chosen.id),
                    "template_key": getattr(chosen, "template_key", None),
                    "version": int(getattr(chosen, "version", 0) or 0),
                    "ab_experiment_key": getattr(chosen, "ab_experiment_key", None),
                    "ab_variant": getattr(chosen, "ab_variant", None),
                    "patch_hash": build_rag_config_patch_hash(getattr(chosen, "config_patch", None)),
                    "patch_applied_fields": rag_config_template_patch_applied_fields,
                }
                if rag_config_template_resolver_debug:
                    rag_config_template_meta["resolver_debug"] = rag_config_template_resolver_debug
                    strategy = str(rag_config_template_resolver_debug.get("strategy") or "").strip().lower()
                    if strategy == "adaptive_epsilon_greedy":
                        rag_config_template_meta["reward_writeback"] = build_adaptive_routing_reward_writeback(
                            experiment_key=(getattr(chosen, "ab_experiment_key", None) or effective_rag_config_ab_experiment_key),
                            variant=getattr(chosen, "ab_variant", None),
                            strategy=rag_config_template_resolver_debug.get("strategy"),
                            decision=rag_config_template_resolver_debug.get("decision"),
                            request_id=str(request_id),
                            template_id=str(chosen.id),
                            template_key=getattr(chosen, "template_key", None),
                        )

                # Analytics only; never fail chat due to counter updates.
                try:
                    chosen.usage_count = int(getattr(chosen, "usage_count", 0) or 0) + 1
                    db.commit()
                except Exception:
                    with contextlib.suppress(Exception):
                        db.rollback()
    except Exception:
        rag_config_template_meta = None
        rag_config_template_patch_applied_fields = []

    # Optional: persistent summary memory injection.
    history_for_llm = [m.model_dump() for m in request.history] + long_term_messages
    if bool(getattr(request, "enable_summary_memory", False)) and conversation_id:
        try:
            summary_text = get_conversation_summary(db, tenant_id=tenant_id, conversation_id=conversation_id)
        except Exception:
            summary_text = None
        if summary_text:
            history_for_llm = [{"role": "system", "content": summary_text}] + history_for_llm
    # Optional: structured memory injection (entities/facts), stored per assistant turn in message_metadata.
    if bool(getattr(request, "enable_structured_memory", False)) and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False)) and conversation_id:
        try:
            records = _retrieve_structured_memory_records(
                db=db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                max_messages=int(getattr(settings, "STRUCTURED_MEMORY_LOOKBACK_MESSAGES", 80) or 80),
            )
            ctx = build_structured_memory_context(
                records=records,
                max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                max_chars=int(getattr(settings, "STRUCTURED_MEMORY_MAX_CONTEXT_CHARS", 1200) or 1200),
            )
        except Exception:
            ctx = ""
        if ctx:
            history_for_llm = [{"role": "system", "content": ctx}] + history_for_llm

    metrics_data: dict = {}
    structured_data = None

    # Optional chat response cache (best-effort).
    cache_key: str | None = None
    cache_hit = False
    singleflight_hit = False
    singleflight_leader = False
    singleflight_key: str | None = None
    cache_scope_dataset_id = dataset_id_used or scope_dataset_id
    rag_cfg = jsonable_encoder(effective_rag_config.model_dump())
    prompt_cfg = {
        "prompt_template_id": str(effective_prompt_template_id) if effective_prompt_template_id else None,
        "prompt_template_key": (effective_prompt_template_key or None),
        "prompt_ab_experiment_key": (effective_prompt_ab_experiment_key or None),
    }
    cache_feature_enabled, cache_key, cache_skip_reason = _prepare_chat_cache_lookup(
        db=db,
        tenant_id=tenant_id,
        account_id=str(account_id or ""),
        dataset_id=cache_scope_dataset_id,
        document_ids=doc_ids_to_use,
        history=request.history,
        enable_long_term_memory=bool(request.enable_long_term_memory),
        long_term_messages=long_term_messages,
        enable_structured_memory=bool(getattr(request, "enable_structured_memory", False)),
        question=request.message,
        rag_config=rag_cfg,
        prompt_config=prompt_cfg,
        structured_output=bool(request.structured_output),
        structured_preset=request.structured_preset,
        use_graph=bool(effective_rag_config.use_graph),
    )
    cache_eligible = bool(cache_key)
    cached = get_cached_chat_response(cache_key) if cache_key else None
    if isinstance(cached, dict):
        full_response = str(cached.get("content") or "")
        citations_data = cached.get("citations") if isinstance(cached.get("citations"), list) else []
        metrics_data = _annotate_chat_cache_metrics(
            dict(cached.get("metrics") or {}),
            enabled=cache_feature_enabled,
            hit=True,
            skip_reason=None,
        )
        structured_data = cached.get("structured_data")
        cache_hit = True
        metrics_data = _annotate_chat_singleflight_metrics(
            metrics_data,
            enabled=bool(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False)),
            hit=False,
            role=None,
        )
    else:
        singleflight_feature_enabled = bool(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False))
        singleflight_key = cache_key if singleflight_feature_enabled and cache_key else None
        if singleflight_key:
            singleflight_leader, inflight_future = await acquire_inflight_chat_response(singleflight_key)
            if not singleflight_leader:
                shared_payload = await asyncio.shield(inflight_future)
                full_response = str(shared_payload.get("content") or "")
                citations_data = (
                    shared_payload.get("citations") if isinstance(shared_payload.get("citations"), list) else []
                )
                metrics_data = _annotate_chat_cache_metrics(
                    dict(shared_payload.get("metrics") or {}),
                    enabled=cache_feature_enabled,
                    hit=False,
                    skip_reason=cache_skip_reason,
                )
                metrics_data = _annotate_chat_singleflight_metrics(
                    metrics_data,
                    enabled=singleflight_feature_enabled,
                    hit=True,
                    role="follower",
                )
                structured_data = shared_payload.get("structured_data")
                singleflight_hit = True

    try:
        if not cache_hit and not singleflight_hit:
            # Graph path (LangGraph): invoke once and return the final state.
            if effective_rag_config.use_graph:
                from app.rag.pipelines.langgraph import build_rag_state, rag_workflow

                thread_id = str(conversation_id) if conversation_id else f"rag-{request_id}"
                runtime_context = {
                    "request_id": str(request_id),
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "account_id": account_id,
                }

                state = build_rag_state(
                    question=request.message,
                    history=history_for_llm,
                    document_ids=doc_ids_to_use,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_id=dataset_id_used or scope_dataset_id,
                    top_k=effective_rag_config.top_k,
                    score_threshold=effective_rag_config.score_threshold,
                    retrieval_mode=effective_rag_config.retrieval_mode,
                    retrieval_profile=effective_rag_config.retrieval_profile,
                    retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
                    must_recall=effective_rag_config.must_recall,
                    must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
                    must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
                    intent_router=effective_rag_config.intent_router,
                    intent_router_policy=effective_rag_config.intent_router_policy,
                    enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
                    query_aliases=effective_rag_config.query_aliases,
                    query_alias_max_queries=effective_rag_config.query_alias_max_queries,
                    enable_multi_query=effective_rag_config.enable_multi_query,
                    multi_query_count=effective_rag_config.multi_query_count,
                    multi_query_temperature=effective_rag_config.multi_query_temperature,
                    multi_query_max_chars=effective_rag_config.multi_query_max_chars,
                    enable_hyde=effective_rag_config.enable_hyde,
                    enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
                    hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
                    hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
                    hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
                    hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
                    hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
                    hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
                    alpha=effective_rag_config.alpha,
                    fusion_strategy=effective_rag_config.fusion_strategy,
                    fusion_budgets=effective_rag_config.fusion_budgets,
                    fusion_min_scores=effective_rag_config.fusion_min_scores,
                    fusion_weights=effective_rag_config.fusion_weights,
                    enable_weight_rerank=effective_rag_config.enable_weight_rerank,
                    vector_weight=effective_rag_config.vector_weight,
                    keyword_weight=effective_rag_config.keyword_weight,
                    mmr_lambda=effective_rag_config.mmr_lambda,
                    enable_reranker=effective_rag_config.enable_reranker,
                    reranker_provider=effective_rag_config.reranker_provider,
                    reranker_top_n=effective_rag_config.reranker_top_n,
                    metadata_filter=effective_rag_config.metadata_filter,
                    structured_output=request.structured_output,
                    structured_preset=request.structured_preset,
                    visible_evidence_only=effective_rag_config.visible_evidence_only,
                    prompt_template_id=effective_prompt_template_id,
                    prompt_template_key=effective_prompt_template_key,
                    prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
                    ab_user_key=account_id,
                    db=db,
                )
                if rag_config_template_meta:
                    state["rag_config_template"] = rag_config_template_meta

                # Optional: Multi-modal routing (deterministic) + context injection.
                #
                # Notes:
                # - Keep DB/LLM calls outside the graph to avoid persisting non-serializable resources.
                # - Injection happens via `tag_docs` (existing surface used by the retrieval node).
                multimodal_meta: dict[str, Any] = {"enabled": True, "modality": "text", "reasons": []}
                injected_docs: list[Any] = []

                tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
                image_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}

                try:
                    from app.rag.policy.modality_router import classify_query_modality

                    modality, reasons = classify_query_modality(request.message)
                    multimodal_meta["modality"] = modality
                    multimodal_meta["reasons"] = reasons
                except Exception as exc:  # noqa: BLE001
                    multimodal_meta["enabled"] = False
                    multimodal_meta["modality"] = "text"
                    multimodal_meta["reasons"] = [f"router_exception:{str(exc)[:80]}"]
                    modality = "text"

                # TAG injection: keep behavior consistent with streaming graph path.
                # We always attempt lightweight TAG context building and let the
                # service decide whether data is available/usable.
                try:
                    import inspect

                    from app.services.chat_tag_service import build_chat_tag_context_docs

                    tag_kwargs: dict[str, Any] = {
                        "tenant_id": tenant_id,
                        "document_ids": doc_ids_to_use,
                        "question": request.message,
                    }
                    if "must_recall_expected_source_keys" in inspect.signature(build_chat_tag_context_docs).parameters:
                        tag_kwargs["must_recall_expected_source_keys"] = (
                            effective_rag_config.must_recall_expected_source_keys
                        )

                    tag_docs, tag_meta = build_chat_tag_context_docs(db, **tag_kwargs)
                    if tag_docs:
                        injected_docs.extend(tag_docs)
                except Exception as exc:  # noqa: BLE001
                    tag_meta = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

                # Image injection (only when the query asks for images/figures).
                try:
                    if str(modality or "text").lower().strip() == "image":
                        from app.services.chat_image_service import build_chat_image_context_docs

                        ds_for_images = dataset_id_used or scope_dataset_id
                        if ds_for_images is not None:
                            image_docs, image_meta = build_chat_image_context_docs(
                                db,
                                tenant_id=tenant_id,
                                account_id=account_id,
                                dataset_id=ds_for_images,
                                question=request.message,
                                top_k=6,
                            )
                            if image_docs:
                                injected_docs.extend(image_docs)
                        else:
                            image_meta = {"enabled": False, "used": False, "reason": "missing_dataset_id"}
                except Exception as exc:  # noqa: BLE001
                    image_meta = {"enabled": False, "used": False, "reason": f"image_exception:{str(exc)[:120]}"}

                # Legacy surface: retrieval node consumes `tag_docs` (prepended before text retrieval results).
                if injected_docs:
                    state["tag_docs"] = injected_docs

                state["tag_meta"] = tag_meta
                state["image_meta"] = image_meta
                state["multimodal_router"] = multimodal_meta

                recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
                config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
                graph_result = rag_workflow.invoke(state, config=config, context=runtime_context) or {}

                citations_data = graph_result.get("citations") or []
                full_response = graph_result.get("answer") or ""
                metrics_data = dict(graph_result.get("metrics") or {})
                metrics_data.setdefault("multimodal_router", multimodal_meta)
                metrics_data.setdefault("tag", tag_meta)
                metrics_data.setdefault("image", image_meta)

                if request.structured_output:
                    structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
                    metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
                    metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
                    metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
                    metrics_data["structured_type"] = (
                        type(structured_data).__name__ if structured_data is not None else None
                    )
                    metrics_data["structured_preset"] = request.structured_preset
            else:
                # LangChain engine path: consume the stream and assemble a final payload.
                engine = get_rag_engine()
                done_data: dict = {}
                async for event in engine.stream_chat(
                    question=request.message,
                    history=history_for_llm,
                    conversation_id=conversation_id,
                    document_ids=doc_ids_to_use,
                    metadata_filter=effective_rag_config.metadata_filter,
                    top_k=effective_rag_config.top_k,
                    score_threshold=effective_rag_config.score_threshold,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_id=dataset_id_used or scope_dataset_id,
                    structured_output=request.structured_output,
                    retrieval_mode=effective_rag_config.retrieval_mode,
                    retrieval_profile=effective_rag_config.retrieval_profile,
                    retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
                    must_recall=effective_rag_config.must_recall,
                    must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
                    must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
                    intent_router=effective_rag_config.intent_router,
                    intent_router_policy=effective_rag_config.intent_router_policy,
                    enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
                    query_aliases=effective_rag_config.query_aliases,
                    query_alias_max_queries=effective_rag_config.query_alias_max_queries,
                    enable_multi_query=effective_rag_config.enable_multi_query,
                    multi_query_count=effective_rag_config.multi_query_count,
                    multi_query_temperature=effective_rag_config.multi_query_temperature,
                    multi_query_max_chars=effective_rag_config.multi_query_max_chars,
                    enable_hyde=effective_rag_config.enable_hyde,
                    enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
                    hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
                    hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
                    hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
                    hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
                    hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
                    hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
                    alpha=effective_rag_config.alpha,
                    fusion_strategy=effective_rag_config.fusion_strategy,
                    fusion_budgets=effective_rag_config.fusion_budgets,
                    fusion_min_scores=effective_rag_config.fusion_min_scores,
                    fusion_weights=effective_rag_config.fusion_weights,
                    enable_weight_rerank=effective_rag_config.enable_weight_rerank,
                    vector_weight=effective_rag_config.vector_weight,
                    keyword_weight=effective_rag_config.keyword_weight,
                    mmr_lambda=effective_rag_config.mmr_lambda,
                    enable_reranker=effective_rag_config.enable_reranker,
                    reranker_provider=effective_rag_config.reranker_provider,
                    reranker_top_n=effective_rag_config.reranker_top_n,
                    structured_preset=request.structured_preset,
                    visible_evidence_only=effective_rag_config.visible_evidence_only,
                    prompt_template_id=effective_prompt_template_id,
                    prompt_template_key=effective_prompt_template_key,
                    prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
                    rag_config_template=rag_config_template_meta,
                    ab_user_key=account_id,
                    db=db,
                    request_id=str(request_id),
                ):
                    etype = event.get("type")
                    if etype == "citations":
                        citations_data = event.get("data") or []
                    elif etype == "token":
                        data = event.get("data") or {}
                        full_response_parts.append(str(data.get("content") or ""))
                    elif etype == "done":
                        done_data = event.get("data") or {}

                # Avoid O(n^2) string concatenation for long answers.
                if full_response_parts:
                    full_response = "".join(full_response_parts)

                if isinstance(done_data, dict):
                    metrics_data = dict(done_data.get("metrics") or {})
                    structured_data = done_data.get("structured_data")

        metrics_data = _annotate_chat_cache_metrics(
            metrics_data,
            enabled=cache_feature_enabled,
            hit=cache_hit,
            skip_reason=None if cache_hit else cache_skip_reason,
        )
        metrics_data = _annotate_chat_singleflight_metrics(
            metrics_data,
            enabled=bool(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_ENABLED", False)),
            hit=singleflight_hit,
            role=("follower" if singleflight_hit else ("leader" if singleflight_leader else None)),
        )

        # Best-effort: sampled online evaluation (async, PII-minimal outputs).
        #
        # - Engine path already enqueues online eval inside `RAGEngine.stream_chat`.
        # - Graph path and cache-hit path need an explicit enqueue here.
        try:
            if bool(effective_rag_config.use_graph) or bool(cache_hit):
                from app.services.online_eval_service import maybe_enqueue_online_eval

                contexts: list[str] = []
                for c in citations_data or []:
                    if hasattr(c, "model_dump"):
                        try:
                            c = c.model_dump(mode="json")
                        except Exception:
                            continue
                    if not isinstance(c, dict):
                        continue
                    text = str(c.get("chunk_content") or c.get("quote") or c.get("text") or "").strip()
                    if not text:
                        continue
                    if text not in contexts:
                        contexts.append(text)
                    if len(contexts) >= 24:
                        break

                maybe_enqueue_online_eval(
                    tenant_id=tenant_id,
                    dataset_id=(dataset_id_used or scope_dataset_id),
                    request_id=str(request_id),
                    answer=str(full_response or ""),
                    contexts=contexts,
                    retrieval_mode=str(metrics_data.get("retrieval_mode") or effective_rag_config.retrieval_mode or "") or None,
                    citations_count=int(len(citations_data or [])),
                )
        except Exception:
            pass

        # 3) Persist assistant response.
        # Persist dataset-level default metadata into the stored message for later analytics/debugging.
        if dataset_id_used is not None:
            metrics_data.setdefault("dataset_id", str(dataset_id_used))
        if dataset_rag_defaults_applied_fields:
            metrics_data.setdefault("dataset_rag_defaults_applied", True)
            metrics_data.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
        if dataset_rag_config_template_defaults_applied_fields:
            metrics_data.setdefault("dataset_rag_config_template_defaults_applied", True)
            metrics_data.setdefault(
                "dataset_rag_config_template_defaults_fields",
                dataset_rag_config_template_defaults_applied_fields,
            )
        if rag_config_template_meta:
            metrics_data.setdefault("rag_config_template", rag_config_template_meta)
        if dataset_prompt_defaults_applied_fields:
            metrics_data.setdefault("dataset_prompt_defaults_applied", True)
            metrics_data.setdefault("dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields)
        if tenant_qps_meta.get("enabled"):
            metrics_data.setdefault("tenant_qps_quota", tenant_qps_meta)
        if quota_meta.get("enabled"):
            metrics_data.setdefault("quota", quota_meta)

        # Optional: store response in Redis cache before DB commit so metadata is consistent.
        if cache_eligible and (not cache_hit) and cache_key and full_response.strip():
            cache_payload = jsonable_encoder(
                {
                    "content": full_response,
                    "citations": citations_data,
                    "metrics": metrics_data,
                    "structured_data": structured_data,
                }
            )
            stored = bool(set_cached_chat_response(cache_key, cache_payload))
            metrics_data.setdefault("chat_cache_store_ok", stored)

        if singleflight_key and singleflight_leader:
            resolve_inflight_chat_response(
                singleflight_key,
                jsonable_encoder(
                    {
                        "content": full_response,
                        "citations": citations_data,
                        "metrics": metrics_data,
                        "structured_data": structured_data,
                    }
                ),
            )

        message_metadata = _build_chat_message_metadata(
            request_id=str(request_id),
            original_question=request.message,
            metrics=metrics_data,
            citations=citations_data if isinstance(citations_data, list) else [],
        )
        if (
            bool(getattr(request, "enable_structured_memory", False))
            and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False))
        ):
            try:
                message_metadata["structured_memory"] = extract_structured_memory_for_turn(
                    user_text=str(request.message or ""),
                    assistant_text=str(full_response or ""),
                    max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                    max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                )
            except Exception:
                # Best-effort: never block chat persistence on memory extraction.
                pass

        assistant_message = Message(
            id=assistant_message_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
            citations=citations_data,
            token_count=num_tokens_from_string(full_response or ""),
            message_metadata=message_metadata,
        )
        db.add(assistant_message)

        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="chat.ask",
            resource_type="conversation",
            resource_id=str(conversation_id),
            request_id=str(request_id),
            ip=getattr(getattr(http_request, "client", None), "host", None),
            user_agent=http_request.headers.get("user-agent"),
            details=build_chat_audit_details(
                question=request.message,
                document_count=len(doc_ids_to_use),
                dataset_id=dataset_id_used,
                cache_hit=cache_hit,
            ),
        )

        _touch_conversation_after_turn(db=db, tenant_id=tenant_id, conversation_id=conversation_id)
        db.commit()

    except Exception as exc:  # noqa: BLE001
        if singleflight_key and singleflight_leader:
            reject_inflight_chat_response(singleflight_key, exc)
        logger.error("Chat error: %s", str(exc)[:200])
        raise HTTPException(status_code=500, detail=_format_stream_error_message(exc)) from exc

    if conversation_id is None:
        raise HTTPException(status_code=500, detail="Conversation id missing")

    # Optional: auto-update persistent summary after the assistant turn (best-effort).
    if (
        bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
        and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
        and bool(getattr(request, "enable_summary_memory", False))
        and conversation_id
    ):
        with contextlib.suppress(Exception):
            background_tasks.add_task(_auto_update_summary_background, tenant_id=tenant_id, conversation_id=conversation_id)

    retrieval_mode_used = metrics_data.get("retrieval_mode") or effective_rag_config.retrieval_mode
    vector_backend_used = metrics_data.get("vector_backend") or settings.VECTOR_BACKEND
    structured_ok = bool(metrics_data.get("structured_parse_ok")) and structured_data is not None

    total_tokens = num_tokens_from_string(full_response or "")
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": total_tokens,
        "total_tokens": total_tokens,
        "source": "mock" if bool(getattr(settings, "LLM_MOCK_ENABLED", False)) else "estimate",
    }

    return {
        "conversation_id": conversation_id,
        "assistant_message_id": assistant_message_id,
        "request_id": str(request_id),
        "content": full_response,
        "citations": citations_data,
        "total_tokens": total_tokens,
        "usage": usage,
        "total_chars": len(full_response or ""),
        "retrieval_mode": retrieval_mode_used,
        "vector_backend": vector_backend_used,
        "confidence_score": metrics_data.get("confidence_score"),
        "followup_questions": metrics_data.get("followup_questions") or [],
        "metrics": metrics_data,
        "structured": structured_ok if request.structured_output else False,
        "structured_data": structured_data,
    }


@router.post("/stream", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def stream_chat(
    http_request: Request,
    request: ChatRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)]
):
    """
    Streaming chat endpoint (core flow).
    """

    conversation_id = request.conversation_id
    citations_data = []
    full_response = ""
    allowed_doc_ids: list[UUID] = []
    long_term_messages: list[dict] = []
    allow_empty_docs = bool(getattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True))
    allow_open_scope = bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False))

    # Tenant QPS quotas (Wave22-T094): per-tenant aggregate limiter (best-effort).
    from app.services.tenant_quota_service import enforce_tenant_qps_quota

    tenant_qps_meta = enforce_tenant_qps_quota(tenant_id=tenant_id, key="chat")

    quota_meta = check_chat_assistant_token_quota(db, tenant_id=tenant_id)
    if quota_meta.get("enabled") and quota_meta.get("exceeded") and quota_meta.get("mode") == "block":
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Chat quota exceeded (assistant tokens)",
                "retry_after_sec": None,
                "limit": int(quota_meta.get("limit") or 0),
                "scope": "chat_tokens",
            },
        )

    # 1. Load or create a conversation.
    #
    # IMPORTANT: empty document_ids means "open scope" (tenant-level), trimmed on candidate set
    # inside the retriever. This avoids the old implicit behavior of limiting retrieval to
    # the latest N documents.
    scope_dataset_id: UUID | None = None
    if conversation_id:
        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail=CONVERSATION_NOT_FOUND_DETAIL)

        if request.document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
            conversation.document_ids = allowed_doc_ids
            conversation.dataset_id = None

            if request.dataset_id is not None and allowed_doc_ids:
                from app.models.document import Document as DBDocument  # noqa: WPS433

                rows = (
                    db.query(DBDocument.dataset_id)
                    .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(allowed_doc_ids))
                    .all()
                )
                ds_ids = {row[0] for row in rows if row and row[0] is not None}
                if ds_ids and ds_ids != {request.dataset_id}:
                    raise HTTPException(status_code=400, detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL)

        elif request.dataset_id is not None:
            DatasetService.ensure_member(db, tenant_id, account_id)
            ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
            DatasetService.assert_dataset_readable(db, ds, account_id)

            scope_dataset_id = request.dataset_id
            conversation.dataset_id = request.dataset_id
            conversation.document_ids = []
            allowed_doc_ids = []

        elif conversation.document_ids:
            allowed_doc_ids = _resolve_conversation_document_scope_for_chat(
                db,
                tenant_id,
                account_id,
                conversation,
            )
            conversation.document_ids = allowed_doc_ids
            conversation.dataset_id = None
        else:
            scope_dataset_id = getattr(conversation, "dataset_id", None)
            allowed_doc_ids = []
            if scope_dataset_id is None and not allow_open_scope:
                raise HTTPException(
                    status_code=400,
                    detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
                )

        if not allow_empty_docs:
            _enforce_non_empty_chat_scope(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                allowed_doc_ids=allowed_doc_ids,
                scope_dataset_id=scope_dataset_id,
                error_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
            )

    else:
        if request.document_ids:
            allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, request.document_ids)
            scope_dataset_id = None

            if request.dataset_id is not None and allowed_doc_ids:
                from app.models.document import Document as DBDocument  # noqa: WPS433

                rows = (
                    db.query(DBDocument.dataset_id)
                    .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(allowed_doc_ids))
                    .all()
                )
                ds_ids = {row[0] for row in rows if row and row[0] is not None}
                if ds_ids and ds_ids != {request.dataset_id}:
                    raise HTTPException(status_code=400, detail=DOC_IDS_MUST_MATCH_DATASET_DETAIL)

        elif request.dataset_id is not None:
            DatasetService.ensure_member(db, tenant_id, account_id)
            ds = DatasetService.get_dataset(db, tenant_id, request.dataset_id)
            DatasetService.assert_dataset_readable(db, ds, account_id)
            scope_dataset_id = request.dataset_id
            allowed_doc_ids = []
        else:
            scope_dataset_id = None
            allowed_doc_ids = []
            if not allow_open_scope:
                raise HTTPException(
                    status_code=400,
                    detail=DATASET_REQUIRED_WHEN_DOC_IDS_EMPTY_DETAIL,
                )

        if not allow_empty_docs:
            _enforce_non_empty_chat_scope(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                allowed_doc_ids=allowed_doc_ids,
                scope_dataset_id=scope_dataset_id,
                error_detail=NO_ACCESSIBLE_DOCS_CHAT_RETRIEVAL_DETAIL,
            )

        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            title_source=CONVERSATION_TITLE_SOURCE_AUTO,
            dataset_id=scope_dataset_id,
            document_ids=allowed_doc_ids,
        )
        _apply_auto_conversation_title(conversation, request.message)
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id

    # 2. Persist the user message.
    user_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role='user',
        content=request.message,
        token_count=num_tokens_from_string(request.message or ""),
    )
    db.add(user_message)
    _apply_auto_conversation_title(conversation, request.message)

    # Optional: long-term memory recall (BM25 over conversation messages).
    if request.enable_long_term_memory and settings.LONG_TERM_MEMORY_ENABLED and conversation_id:
        long_term_messages = _retrieve_long_term_messages(
            db=db,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            query=request.message,
            top_k=settings.LONG_TERM_MEMORY_TOP_K
        )

    # Update the conversation message count.
    conversation.message_count = (conversation.message_count or 0) + 1
    db.commit()

    # Provide a stable assistant message id for the whole stream so clients can
    # correlate SSE events with persisted rows (and so headers can expose it).
    assistant_message_id = uuid.uuid4()

    # 3. Streaming response generator.
    async def event_stream():
        nonlocal citations_data, full_response
        doc_ids_to_use = allowed_doc_ids or []
        request_id = getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
        # Avoid O(n^2) string concatenation while streaming tokens.
        response_parts: list[str] = []
        metrics_data = {}
        structured_data = None
        set_metrics_context(
            request_id=request_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            account_id=account_id,
        )
        persist_in_background = bool(getattr(settings, "CHAT_STREAM_PERSIST_IN_BACKGROUND", False))
        client_ip = getattr(getattr(http_request, "client", None), "host", None)
        user_agent = http_request.headers.get("user-agent")
        enable_summary_memory = bool(getattr(request, "enable_summary_memory", False))
        enable_structured_memory = bool(getattr(request, "enable_structured_memory", False))

        # Send an immediate SSE frame so clients/proxies don't see an idle connection.
        yield ": keepalive\n\n"
        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'event', 'data': {'message': '开始处理…'}}, ensure_ascii=False)}\n\n"

        # Dataset-level default RAG config (best-effort): apply only when all docs share one dataset_id.
        effective_rag_config = request.rag_config
        dataset_rag_defaults_applied_fields: list[str] = []
        dataset_defaults_meta: dict | None = None
        dataset_id_used: UUID | None = scope_dataset_id
        rag_fields_set = set(getattr(request.rag_config, "model_fields_set", set()) or set())
        if "rag_config" not in set(getattr(request, "model_fields_set", set()) or set()):
            rag_fields_set = set()
        try:
            if dataset_id_used is None:
                dataset_id_used = resolve_single_dataset_id_for_documents(
                    db, tenant_id=tenant_id, document_ids=doc_ids_to_use
                )
            if dataset_id_used is not None:
                ds_meta = load_dataset_metadata(db, tenant_id=tenant_id, dataset_id=dataset_id_used)
                dataset_defaults_meta = ds_meta if isinstance(ds_meta, dict) else None
                raw_defaults = ds_meta.get("rag_defaults") if isinstance(ds_meta, dict) else None
                effective_rag_config, dataset_rag_defaults_applied_fields = merge_rag_config_with_dataset_defaults(
                    rag_config=effective_rag_config,
                    request_fields_set=rag_fields_set,
                    raw_dataset_defaults=raw_defaults,
                )
        except Exception:
            dataset_rag_defaults_applied_fields = []
            dataset_defaults_meta = None
            dataset_id_used = scope_dataset_id

        # Dataset-level default prompt settings (best-effort).
        req_fields = set(getattr(request, "model_fields_set", set()) or set())
        (
            effective_prompt_template_id,
            effective_prompt_template_key,
            effective_prompt_ab_experiment_key,
            dataset_prompt_defaults_applied_fields,
        ) = merge_prompt_defaults_with_dataset(
            prompt_template_id=request.prompt_template_id,
            prompt_template_key=request.prompt_template_key,
            prompt_ab_experiment_key=request.prompt_ab_experiment_key,
            request_fields_set=req_fields,
            dataset_meta=dataset_defaults_meta,
        )

        # Dataset-level default RAG config template selectors + patch application (best-effort).
        (
            effective_rag_config_template_id,
            effective_rag_config_template_key,
            effective_rag_config_ab_experiment_key,
            dataset_rag_config_template_defaults_applied_fields,
        ) = merge_rag_config_template_defaults_with_dataset(
            rag_config_template_id=request.rag_config_template_id,
            rag_config_template_key=request.rag_config_template_key,
            rag_config_ab_experiment_key=request.rag_config_ab_experiment_key,
            request_fields_set=req_fields,
            dataset_meta=dataset_defaults_meta,
        )

        rag_config_template_meta: dict[str, Any] | None = None
        rag_config_template_resolver_debug: dict[str, Any] | None = None
        rag_config_template_patch_applied_fields: list[str] = []
        try:
            if (
                effective_rag_config_template_id
                or (effective_rag_config_template_key or "").strip()
                or (effective_rag_config_ab_experiment_key or "").strip()
            ):
                chosen, rag_config_template_resolver_debug = resolve_rag_config_template(
                    db=db,
                    tenant_id=tenant_id,
                    rag_config_template_id=effective_rag_config_template_id,
                    template_key=effective_rag_config_template_key,
                    ab_experiment_key=effective_rag_config_ab_experiment_key,
                    ab_user_key=account_id,
                    return_debug_metadata=True,
                )
                if chosen:
                    effective_rag_config, rag_config_template_patch_applied_fields = apply_rag_config_patch(
                        rag_config=effective_rag_config,
                        patch=getattr(chosen, "config_patch", None),
                        request_fields_set=rag_fields_set,
                    )
                    rag_config_template_meta = {
                        "template_id": str(chosen.id),
                        "template_key": getattr(chosen, "template_key", None),
                        "version": int(getattr(chosen, "version", 0) or 0),
                        "ab_experiment_key": getattr(chosen, "ab_experiment_key", None),
                        "ab_variant": getattr(chosen, "ab_variant", None),
                        "patch_hash": build_rag_config_patch_hash(getattr(chosen, "config_patch", None)),
                        "patch_applied_fields": rag_config_template_patch_applied_fields,
                    }
                    if rag_config_template_resolver_debug:
                        rag_config_template_meta["resolver_debug"] = rag_config_template_resolver_debug
                        strategy = str(rag_config_template_resolver_debug.get("strategy") or "").strip().lower()
                        if strategy == "adaptive_epsilon_greedy":
                            rag_config_template_meta["reward_writeback"] = build_adaptive_routing_reward_writeback(
                                experiment_key=(getattr(chosen, "ab_experiment_key", None) or effective_rag_config_ab_experiment_key),
                                variant=getattr(chosen, "ab_variant", None),
                                strategy=rag_config_template_resolver_debug.get("strategy"),
                                decision=rag_config_template_resolver_debug.get("decision"),
                                request_id=str(request_id),
                                template_id=str(chosen.id),
                                template_key=getattr(chosen, "template_key", None),
                            )

                    # Analytics only; never fail chat due to counter updates.
                    try:
                        chosen.usage_count = int(getattr(chosen, "usage_count", 0) or 0) + 1
                        db.commit()
                    except Exception:
                        with contextlib.suppress(Exception):
                            db.rollback()
        except Exception:
            rag_config_template_meta = None
            rag_config_template_patch_applied_fields = []

        history_for_llm = [m.model_dump() for m in request.history] + long_term_messages
        if bool(getattr(request, "enable_summary_memory", False)) and conversation_id:
            try:
                summary_text = get_conversation_summary(db, tenant_id=tenant_id, conversation_id=conversation_id)
            except Exception:
                summary_text = None
            if summary_text:
                history_for_llm = [{"role": "system", "content": summary_text}] + history_for_llm
        if (
            bool(getattr(request, "enable_structured_memory", False))
            and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False))
            and conversation_id
        ):
            try:
                records = _retrieve_structured_memory_records(
                    db=db,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    max_messages=int(getattr(settings, "STRUCTURED_MEMORY_LOOKBACK_MESSAGES", 80) or 80),
                )
                ctx = build_structured_memory_context(
                    records=records,
                    max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                    max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                    max_chars=int(getattr(settings, "STRUCTURED_MEMORY_MAX_CONTEXT_CHARS", 1200) or 1200),
                )
            except Exception:
                ctx = ""
            if ctx:
                history_for_llm = [{"role": "system", "content": ctx}] + history_for_llm

        # Optional: chat response cache (Redis, best-effort).
        cache_key: str | None = None
        cache_hit = False
        cache_scope_dataset_id = dataset_id_used or scope_dataset_id
        rag_cfg = jsonable_encoder(effective_rag_config.model_dump())
        prompt_cfg = {
            "prompt_template_id": str(effective_prompt_template_id) if effective_prompt_template_id else None,
            "prompt_template_key": (effective_prompt_template_key or None),
            "prompt_ab_experiment_key": (effective_prompt_ab_experiment_key or None),
        }
        cache_feature_enabled, cache_key, cache_skip_reason = _prepare_chat_cache_lookup(
            db=db,
            tenant_id=tenant_id,
            account_id=str(account_id or ""),
            dataset_id=cache_scope_dataset_id,
            document_ids=doc_ids_to_use,
            history=request.history,
            enable_long_term_memory=bool(request.enable_long_term_memory),
            long_term_messages=long_term_messages,
            enable_structured_memory=bool(getattr(request, "enable_structured_memory", False)),
            question=request.message,
            rag_config=rag_cfg,
            prompt_config=prompt_cfg,
            structured_output=bool(request.structured_output),
            structured_preset=request.structured_preset,
            use_graph=bool(effective_rag_config.use_graph),
        )
        cache_eligible = bool(cache_key)
        cached = get_cached_chat_response(cache_key) if cache_key else None

        if isinstance(cached, dict):
            full_response = str(cached.get("content") or "")
            citations_data = cached.get("citations") if isinstance(cached.get("citations"), list) else []
            metrics_data = _annotate_chat_cache_metrics(
                dict(cached.get("metrics") or {}),
                enabled=cache_feature_enabled,
                hit=True,
                skip_reason=None,
            )
            structured_data = cached.get("structured_data")
            cache_hit = True

        if cache_hit:
            # Stream cached content as token chunks so the frontend can reuse the same SSE handler.
            cancel_on_disconnect = bool(getattr(settings, "CHAT_STREAM_CANCEL_ON_DISCONNECT", True))
            if cancel_on_disconnect:
                with contextlib.suppress(Exception):
                    if await http_request.is_disconnected():
                        return

            yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'event', 'data': {'message': '缓存命中，直接返回…'}}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'citations', 'data': citations_data}, ensure_ascii=False)}\n\n"

            answer_text = full_response or ""
            chunk_size = 120
            for i in range(0, len(answer_text), chunk_size):
                if cancel_on_disconnect and i % (chunk_size * 50) == 0:
                    with contextlib.suppress(Exception):
                        if await http_request.is_disconnected():
                            return
                token_chunk = answer_text[i : i + chunk_size]
                yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'token', 'data': {'content': token_chunk}}, ensure_ascii=False)}\n\n"

            # Ensure lineage/default metadata is present even for cached responses.
            if dataset_id_used is not None:
                metrics_data.setdefault("dataset_id", str(dataset_id_used))
            if dataset_rag_defaults_applied_fields:
                metrics_data.setdefault("dataset_rag_defaults_applied", True)
                metrics_data.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
            if dataset_rag_config_template_defaults_applied_fields:
                metrics_data.setdefault("dataset_rag_config_template_defaults_applied", True)
                metrics_data.setdefault(
                    "dataset_rag_config_template_defaults_fields",
                    dataset_rag_config_template_defaults_applied_fields,
                )
            if rag_config_template_meta:
                metrics_data.setdefault("rag_config_template", rag_config_template_meta)
            if dataset_prompt_defaults_applied_fields:
                metrics_data.setdefault("dataset_prompt_defaults_applied", True)
                metrics_data.setdefault("dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields)
            if tenant_qps_meta.get("enabled"):
                metrics_data.setdefault("tenant_qps_quota", tenant_qps_meta)
            if quota_meta.get("enabled"):
                metrics_data.setdefault("quota", quota_meta)

            retrieval_mode_used = metrics_data.get("retrieval_mode") or effective_rag_config.retrieval_mode
            vector_backend_used = metrics_data.get("vector_backend") or settings.VECTOR_BACKEND

            done_payload = {
                "type": "done",
                "data": {
                    "assistant_message_id": str(assistant_message_id),
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "total_tokens": num_tokens_from_string(answer_text or ""),
                    "total_chars": len(answer_text or ""),
                    "citations_count": len(citations_data),
                    "model_used": metrics_data.get("model_used"),
                    "route": metrics_data.get("route"),
                    "retrieval_mode": retrieval_mode_used,
                    "vector_backend": vector_backend_used,
                    "confidence_score": metrics_data.get("confidence_score"),
                    "followup_questions": metrics_data.get("followup_questions") or [],
                    "metrics": metrics_data,
                    "structured": bool(structured_data is not None) if request.structured_output else False,
                    "structured_data": structured_data,
                    "structured_preset": request.structured_preset,
                },
                "request_id": str(request_id),
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

            # Best-effort: emit a metrics record for cached responses too.
            log_metrics(
                {
                    "event": "rag_done",
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "vector_backend": vector_backend_used,
                    "retrieval_mode": retrieval_mode_used,
                    "route": metrics_data.get("route"),
                    "model_used": metrics_data.get("model_used"),
                    "metrics": metrics_data,
                    "request_id": str(request_id),
                }
            )

            if persist_in_background:
                with contextlib.suppress(Exception):
                    _spawn_background_task(
                        _persist_chat_stream_turn_background(
                            tenant_id=tenant_id,
                            conversation_id=conversation_id,
                            account_id=account_id,
                            assistant_message_id=assistant_message_id,
                            request_id=str(request_id),
                            question=request.message,
                            document_count=len(doc_ids_to_use),
                            content=answer_text,
                            citations=citations_data,
                            metrics=metrics_data,
                            dataset_id_used=dataset_id_used,
                            cache_hit=True,
                            cache_key=cache_key,
                            cache_eligible=False,
                            structured_data=structured_data,
                            ip=client_ip,
                            user_agent=user_agent,
                            enable_summary_memory=enable_summary_memory,
                            enable_structured_memory=enable_structured_memory,
                        )
                    )
                return

            message_metadata = _build_chat_message_metadata(
                request_id=str(request_id),
                original_question=request.message,
                metrics=metrics_data,
                citations=citations_data if isinstance(citations_data, list) else [],
            )
            if enable_structured_memory and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False)):
                try:
                    message_metadata["structured_memory"] = extract_structured_memory_for_turn(
                        user_text=str(request.message or ""),
                        assistant_text=str(answer_text or ""),
                        max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                        max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                    )
                except Exception:
                    pass

            assistant_message = Message(
                id=assistant_message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role="assistant",
                content=answer_text,
                citations=citations_data,
                token_count=num_tokens_from_string(answer_text or ""),
                message_metadata=message_metadata,
            )
            db.add(assistant_message)

            audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action=CHAT_STREAM_AUDIT_ACTION,
                resource_type="conversation",
                resource_id=str(conversation_id),
                request_id=str(request_id),
                ip=getattr(getattr(http_request, "client", None), "host", None),
                user_agent=http_request.headers.get("user-agent"),
                details=build_chat_audit_details(
                    question=request.message,
                    document_count=len(doc_ids_to_use),
                    dataset_id=dataset_id_used,
                    cache_hit=True,
                ),
            )

            _touch_conversation_after_turn(db=db, tenant_id=tenant_id, conversation_id=conversation_id)
            db.commit()

            if (
                bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
                and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
                and bool(getattr(request, "enable_summary_memory", False))
                and conversation_id
            ):
                with contextlib.suppress(Exception):
                    _spawn_background_task(_auto_update_summary_background(tenant_id=tenant_id, conversation_id=conversation_id))
            return

        # LangGraph path: stream stage events (custom) + state snapshots (values).
        if effective_rag_config.use_graph:
            try:
                from app.rag.pipelines.langgraph import build_rag_state, rag_workflow

                thread_id = str(conversation_id) if conversation_id else f"rag-{request_id}"
                runtime_context = {
                    "request_id": str(request_id),
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "account_id": account_id,
                }

                state = build_rag_state(
                    question=request.message,
                    history=history_for_llm,
                    document_ids=doc_ids_to_use,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_id=dataset_id_used or scope_dataset_id,
                    top_k=effective_rag_config.top_k,
                    score_threshold=effective_rag_config.score_threshold,
                    retrieval_mode=effective_rag_config.retrieval_mode,
                    retrieval_profile=effective_rag_config.retrieval_profile,
                    retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
                    must_recall=effective_rag_config.must_recall,
                    must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
                    must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
                    intent_router=effective_rag_config.intent_router,
                    intent_router_policy=effective_rag_config.intent_router_policy,
                    enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
                    query_aliases=effective_rag_config.query_aliases,
                    query_alias_max_queries=effective_rag_config.query_alias_max_queries,
                    enable_multi_query=effective_rag_config.enable_multi_query,
                    multi_query_count=effective_rag_config.multi_query_count,
                    multi_query_temperature=effective_rag_config.multi_query_temperature,
                    multi_query_max_chars=effective_rag_config.multi_query_max_chars,
                    enable_hyde=effective_rag_config.enable_hyde,
                    enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
                    hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
                    hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
                    hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
                    hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
                    hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
                    hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
                    alpha=effective_rag_config.alpha,
                    fusion_strategy=effective_rag_config.fusion_strategy,
                    fusion_budgets=effective_rag_config.fusion_budgets,
                    fusion_min_scores=effective_rag_config.fusion_min_scores,
                    fusion_weights=effective_rag_config.fusion_weights,
                    enable_weight_rerank=effective_rag_config.enable_weight_rerank,
                    vector_weight=effective_rag_config.vector_weight,
                    keyword_weight=effective_rag_config.keyword_weight,
                    mmr_lambda=effective_rag_config.mmr_lambda,
                    enable_reranker=effective_rag_config.enable_reranker,
                    reranker_provider=effective_rag_config.reranker_provider,
                    reranker_top_n=effective_rag_config.reranker_top_n,
                    metadata_filter=effective_rag_config.metadata_filter,
                    structured_output=request.structured_output,
                    structured_preset=request.structured_preset,
                    visible_evidence_only=effective_rag_config.visible_evidence_only,
                    prompt_template_id=effective_prompt_template_id,
                    prompt_template_key=effective_prompt_template_key,
                    prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
                    ab_user_key=account_id,
                    db=db,
                )
                if rag_config_template_meta:
                    state["rag_config_template"] = rag_config_template_meta

                # Optional: Chat -> TAG injection for LangGraph path (streaming).
                try:
                    import inspect

                    from app.services.chat_tag_service import build_chat_tag_context_docs

                    tag_kwargs: dict[str, Any] = {
                        "tenant_id": tenant_id,
                        "document_ids": doc_ids_to_use,
                        "question": request.message,
                    }
                    if "must_recall_expected_source_keys" in inspect.signature(build_chat_tag_context_docs).parameters:
                        tag_kwargs["must_recall_expected_source_keys"] = (
                            effective_rag_config.must_recall_expected_source_keys
                        )

                    tag_docs, tag_meta = build_chat_tag_context_docs(db, **tag_kwargs)
                    state["tag_docs"] = tag_docs
                    state["tag_meta"] = tag_meta
                    if bool(tag_meta.get("enabled")):
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'event', 'data': {'message': '尝试表格查询（TAG）…'}}, ensure_ascii=False)}\n\n"
                except Exception as exc:  # noqa: BLE001
                    state["tag_meta"] = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

                recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
                config = {"configurable": {"thread_id": thread_id}, "recursion_limit": recursion_limit}
                final_state: dict | None = None
                citations_sent = False
                answer_sent = False

                for mode, chunk in rag_workflow.stream(
                    state,
                    config=config,
                    context=runtime_context,
                    stream_mode=["custom", "values"],
                ):
                    if mode == "custom":
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'graph', 'data': chunk}, ensure_ascii=False)}\n\n"
                        continue

                    if mode != "values" or not isinstance(chunk, dict):
                        continue

                    final_state = chunk

                    if not citations_sent and "citations" in chunk:
                        citations_data = chunk.get("citations") or []
                        citations_sent = True
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'citations', 'data': citations_data}, ensure_ascii=False)}\n\n"

                    if not answer_sent and "answer" in chunk:
                        answer_text = chunk.get("answer") or ""
                        chunk_size = 120
                        for i in range(0, len(answer_text), chunk_size):
                            token_chunk = answer_text[i : i + chunk_size]
                            yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'token', 'data': {'content': token_chunk}}, ensure_ascii=False)}\n\n"
                            response_parts.append(token_chunk)
                        answer_sent = True

                graph_result = final_state or {}

                if not citations_sent:
                    citations_data = graph_result.get("citations") or []
                    yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'citations', 'data': citations_data}, ensure_ascii=False)}\n\n"

                if not answer_sent:
                    answer_text = graph_result.get("answer") or ""
                    chunk_size = 120
                    for i in range(0, len(answer_text), chunk_size):
                        token_chunk = answer_text[i : i + chunk_size]
                        yield f"data: {json.dumps({'request_id': str(request_id), 'type': 'token', 'data': {'content': token_chunk}}, ensure_ascii=False)}\n\n"
                        response_parts.append(token_chunk)

                full_response = "".join(response_parts)

                metrics_data = graph_result.get("metrics") or {
                    "retrieval_mode": effective_rag_config.retrieval_mode,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "elapsed_sec": None,
                }
                metrics_data = dict(metrics_data or {})
                metrics_data = _annotate_chat_cache_metrics(
                    metrics_data,
                    enabled=cache_feature_enabled,
                    hit=cache_hit,
                    skip_reason=None if cache_hit else cache_skip_reason,
                )
                if dataset_id_used is not None:
                    metrics_data.setdefault("dataset_id", str(dataset_id_used))
                if dataset_rag_defaults_applied_fields:
                    metrics_data.setdefault("dataset_rag_defaults_applied", True)
                    metrics_data.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
                if dataset_rag_config_template_defaults_applied_fields:
                    metrics_data.setdefault("dataset_rag_config_template_defaults_applied", True)
                    metrics_data.setdefault(
                        "dataset_rag_config_template_defaults_fields",
                        dataset_rag_config_template_defaults_applied_fields,
                    )
                if rag_config_template_meta:
                    metrics_data.setdefault("rag_config_template", rag_config_template_meta)

                if dataset_prompt_defaults_applied_fields:
                    metrics_data.setdefault("dataset_prompt_defaults_applied", True)
                    metrics_data.setdefault("dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields)
                if tenant_qps_meta.get("enabled"):
                    metrics_data.setdefault("tenant_qps_quota", tenant_qps_meta)
                if quota_meta.get("enabled"):
                    metrics_data.setdefault("quota", quota_meta)

                retrieval_mode_used = metrics_data.get("retrieval_mode") or effective_rag_config.retrieval_mode
                vector_backend_used = metrics_data.get("vector_backend") or settings.VECTOR_BACKEND

                structured_data = None
                structured_parse_meta = {"ok": False, "method": None, "error": None}
                if request.structured_output:
                    structured_data, structured_parse_meta = parse_json_from_text(full_response, expected="object")
                    metrics_data["structured_parse_ok"] = bool(structured_parse_meta.get("ok"))
                    metrics_data["structured_parse_method"] = structured_parse_meta.get("method")
                    metrics_data["structured_parse_error"] = structured_parse_meta.get("error")
                    metrics_data["structured_type"] = type(structured_data).__name__ if structured_data is not None else None
                    metrics_data["structured_preset"] = request.structured_preset

                done_payload = {
                    "type": "done",
                    "data": {
                        "assistant_message_id": str(assistant_message_id),
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "total_tokens": num_tokens_from_string(full_response or ""),
                        "total_chars": len(full_response or ""),
                        "citations_count": len(citations_data),
                        "model_used": graph_result.get("model_used"),
                        "route": graph_result.get("route"),
                        "retrieval_mode": retrieval_mode_used,
                        "vector_backend": vector_backend_used,
                        "confidence_score": metrics_data.get("confidence_score"),
                        "followup_questions": metrics_data.get("followup_questions") or [],
                        "metrics": metrics_data,
                        "structured": bool(structured_parse_meta.get("ok")) and structured_data is not None,
                        "structured_data": structured_data,
                    },
                    "request_id": str(request_id),
                }
                yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

                # Optional: store response in Redis cache after the client sees "done"
                # (keeps UI latency low; best-effort).
                if cache_eligible and (not cache_hit) and cache_key and full_response.strip():
                    cache_payload = jsonable_encoder(
                        {
                            "content": full_response,
                            "citations": citations_data,
                            "metrics": metrics_data,
                            "structured_data": structured_data,
                        }
                    )
                    stored = bool(set_cached_chat_response(cache_key, cache_payload))
                    metrics_data.setdefault("chat_cache_store_ok", stored)

                log_metrics(
                    {
                        "event": "rag_done",
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "vector_backend": vector_backend_used,
                        "retrieval_mode": retrieval_mode_used,
                        "route": graph_result.get("route"),
                        "model_used": graph_result.get("model_used"),
                        "metrics": metrics_data,
                        "request_id": str(request_id),
                    }
                )

                if persist_in_background:
                    with contextlib.suppress(Exception):
                        _spawn_background_task(
                            _persist_chat_stream_turn_background(
                                tenant_id=tenant_id,
                                conversation_id=conversation_id,
                                account_id=account_id,
                                assistant_message_id=assistant_message_id,
                                request_id=str(request_id),
                                question=request.message,
                                document_count=len(doc_ids_to_use),
                                content=full_response,
                                citations=citations_data,
                                metrics=metrics_data,
                                dataset_id_used=dataset_id_used,
                                cache_hit=cache_hit,
                                cache_key=cache_key,
                                cache_eligible=False,
                                structured_data=structured_data,
                                ip=client_ip,
                                user_agent=user_agent,
                                enable_summary_memory=enable_summary_memory,
                                enable_structured_memory=enable_structured_memory,
                            )
                        )
                    return

                message_metadata = _build_chat_message_metadata(
                    request_id=str(request_id),
                    original_question=request.message,
                    metrics=metrics_data,
                    citations=citations_data if isinstance(citations_data, list) else [],
                )
                if enable_structured_memory and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False)):
                    try:
                        message_metadata["structured_memory"] = extract_structured_memory_for_turn(
                            user_text=str(request.message or ""),
                            assistant_text=str(full_response or ""),
                            max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                            max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                        )
                    except Exception:
                        pass

                assistant_message = Message(
                    id=assistant_message_id,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    role='assistant',
                    content=full_response,
                    citations=citations_data,
                    token_count=num_tokens_from_string(full_response or ""),
                    message_metadata=message_metadata,
                )
                db.add(assistant_message)

                audit_log_event(
                    db,
                    tenant_id=tenant_id,
                    actor_id=account_id,
                    action=CHAT_STREAM_AUDIT_ACTION,
                    resource_type="conversation",
                    resource_id=str(conversation_id),
                    request_id=str(request_id),
                    ip=getattr(getattr(http_request, "client", None), "host", None),
                    user_agent=http_request.headers.get("user-agent"),
                    details=build_chat_audit_details(
                        question=request.message,
                        document_count=len(doc_ids_to_use),
                        dataset_id=dataset_id_used,
                        cache_hit=cache_hit,
                    ),
                )

                _touch_conversation_after_turn(db=db, tenant_id=tenant_id, conversation_id=conversation_id)
                db.commit()

                if (
                    bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
                    and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
                    and bool(getattr(request, "enable_summary_memory", False))
                    and conversation_id
                ):
                    with contextlib.suppress(Exception):
                        _spawn_background_task(_auto_update_summary_background(tenant_id=tenant_id, conversation_id=conversation_id))
                return

            except Exception as e:  # noqa: BLE001
                logger.error("LangGraph stream error: %s", str(e)[:200])
                error_event = {
                    "type": "error",
                    "data": {
                        "message": "An error occurred during chat processing",
                        "conversation_id": str(conversation_id) if conversation_id else None,
                    },
                    "request_id": str(request_id),
                }
                yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"
                return

        try:
            # Use the LangChain engine.
            engine = get_rag_engine()
            heartbeat_sec = max(0.0, float(getattr(settings, "CHAT_STREAM_HEARTBEAT_SEC", 10.0) or 10.0))
            cancel_on_disconnect = bool(getattr(settings, "CHAT_STREAM_CANCEL_ON_DISCONNECT", True))

            q: asyncio.Queue[dict | None] = asyncio.Queue()
            producer_exc: Exception | None = None

            async def _produce() -> None:
                nonlocal producer_exc
                stream_emitter_token = bind_stream_emitter(StreamEmitter(queue=q, loop=asyncio.get_running_loop()))
                try:
                    async for ev in engine.stream_chat(
                        question=request.message,
                        history=history_for_llm,
                        conversation_id=conversation_id,
                        document_ids=doc_ids_to_use,
                        metadata_filter=effective_rag_config.metadata_filter,
                        top_k=effective_rag_config.top_k,
                        score_threshold=effective_rag_config.score_threshold,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        dataset_id=dataset_id_used or scope_dataset_id,
                        structured_output=request.structured_output,
                    retrieval_mode=effective_rag_config.retrieval_mode,
                    retrieval_profile=effective_rag_config.retrieval_profile,
                    retrieval_contract_mode=effective_rag_config.retrieval_contract_mode,
                    must_recall=effective_rag_config.must_recall,
                    must_recall_expected_source_keys=effective_rag_config.must_recall_expected_source_keys,
                    must_recall_required_anchor_fields=effective_rag_config.must_recall_required_anchor_fields,
                    intent_router=effective_rag_config.intent_router,
                    intent_router_policy=effective_rag_config.intent_router_policy,
                    enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
                    query_aliases=effective_rag_config.query_aliases,
                    query_alias_max_queries=effective_rag_config.query_alias_max_queries,
                    enable_multi_query=effective_rag_config.enable_multi_query,
                    multi_query_count=effective_rag_config.multi_query_count,
                    multi_query_temperature=effective_rag_config.multi_query_temperature,
                    multi_query_max_chars=effective_rag_config.multi_query_max_chars,
                    enable_hyde=effective_rag_config.enable_hyde,
                    enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
                    hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
                    hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
                    hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
                    hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
                    hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
                    hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
                    alpha=effective_rag_config.alpha,
                    fusion_strategy=effective_rag_config.fusion_strategy,
                    fusion_budgets=effective_rag_config.fusion_budgets,
                    fusion_min_scores=effective_rag_config.fusion_min_scores,
                    fusion_weights=effective_rag_config.fusion_weights,
                    enable_weight_rerank=effective_rag_config.enable_weight_rerank,
                    vector_weight=effective_rag_config.vector_weight,
                    keyword_weight=effective_rag_config.keyword_weight,
                    mmr_lambda=effective_rag_config.mmr_lambda,
                    enable_reranker=effective_rag_config.enable_reranker,
                        reranker_provider=effective_rag_config.reranker_provider,
                        reranker_top_n=effective_rag_config.reranker_top_n,
                        structured_preset=request.structured_preset,
                        visible_evidence_only=effective_rag_config.visible_evidence_only,
                        prompt_template_id=effective_prompt_template_id,
                        prompt_template_key=effective_prompt_template_key,
                        prompt_ab_experiment_key=effective_prompt_ab_experiment_key,
                        rag_config_template=rag_config_template_meta,
                        ab_user_key=account_id,
                        db=db,
                        request_id=str(request_id),
                    ):
                        await q.put(ev)
                except Exception as exc:  # noqa: BLE001
                    producer_exc = exc
                finally:
                    reset_stream_emitter(stream_emitter_token)
                    await q.put(None)

            producer_task = asyncio.create_task(_produce())
            disconnected = False

            while True:
                if cancel_on_disconnect:
                    try:
                        if await http_request.is_disconnected():
                            disconnected = True
                            producer_task.cancel()
                            break
                    except Exception:
                        pass

                try:
                    ev = await asyncio.wait_for(q.get(), timeout=heartbeat_sec) if heartbeat_sec > 0 else await q.get()
                except asyncio.TimeoutError:
                    # Keep the SSE connection warm for proxies/load balancers.
                    yield ": keepalive\n\n"
                    continue

                if ev is None:
                    break

                event = ev

                # Capture citations.
                if event.get("type") == "citations":
                    citations_data = event.get("data") or []

                if event.get("type") == "done":
                    if isinstance(event.get("data"), dict):
                        event["data"]["assistant_message_id"] = str(assistant_message_id)
                        metrics_data = event["data"].get("metrics", {})  # type: ignore[assignment]
                        structured_data = event["data"].get("structured_data")
                    else:
                        metrics_data = {}  # type: ignore[assignment]
                    if isinstance(metrics_data, dict):
                        metrics_data = _annotate_chat_cache_metrics(
                            metrics_data,
                            enabled=cache_feature_enabled,
                            hit=cache_hit,
                            skip_reason=None if cache_hit else cache_skip_reason,
                        )
                    else:
                        metrics_data = _annotate_chat_cache_metrics(
                            {},
                            enabled=cache_feature_enabled,
                            hit=cache_hit,
                            skip_reason=None if cache_hit else cache_skip_reason,
                        )
                    if isinstance(event.get("data"), dict):
                        event["data"]["metrics"] = metrics_data

                    if dataset_id_used is not None:
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("dataset_id", str(dataset_id_used))
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("dataset_id", str(dataset_id_used))
                        except Exception:
                            pass

                    if tenant_qps_meta.get("enabled"):
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("tenant_qps_quota", tenant_qps_meta)
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("tenant_qps_quota", tenant_qps_meta)
                        except Exception:
                            pass

                    if quota_meta.get("enabled"):
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("quota", quota_meta)
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("quota", quota_meta)
                        except Exception:
                            pass

                    if dataset_rag_defaults_applied_fields:
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("dataset_rag_defaults_applied", True)
                                metrics_data.setdefault("dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields)
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("dataset_rag_defaults_applied", True)
                                event["data"]["metrics"].setdefault(
                                    "dataset_rag_defaults_fields", dataset_rag_defaults_applied_fields
                                )
                        except Exception:
                            pass

                    if dataset_rag_config_template_defaults_applied_fields:
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("dataset_rag_config_template_defaults_applied", True)
                                metrics_data.setdefault(
                                    "dataset_rag_config_template_defaults_fields",
                                    dataset_rag_config_template_defaults_applied_fields,
                                )
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("dataset_rag_config_template_defaults_applied", True)
                                event["data"]["metrics"].setdefault(
                                    "dataset_rag_config_template_defaults_fields",
                                    dataset_rag_config_template_defaults_applied_fields,
                                )
                        except Exception:
                            pass

                    if rag_config_template_meta:
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("rag_config_template", rag_config_template_meta)
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("rag_config_template", rag_config_template_meta)
                        except Exception:
                            pass

                    if dataset_prompt_defaults_applied_fields:
                        try:
                            if isinstance(metrics_data, dict):
                                metrics_data.setdefault("dataset_prompt_defaults_applied", True)
                                metrics_data.setdefault(
                                    "dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields
                                )
                            if isinstance(event.get("data"), dict) and isinstance(event["data"].get("metrics"), dict):
                                event["data"]["metrics"].setdefault("dataset_prompt_defaults_applied", True)
                                event["data"]["metrics"].setdefault(
                                    "dataset_prompt_defaults_fields", dataset_prompt_defaults_applied_fields
                                )
                        except Exception:
                            pass

                # Accumulate full response.
                if event.get("type") == "token":
                    data = event.get("data") if isinstance(event.get("data"), dict) else {}
                    response_parts.append(str((data or {}).get("content") or ""))

                # Stream SSE events.
                event["request_id"] = str(request_id)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            with contextlib.suppress(asyncio.CancelledError, Exception):
                await producer_task

            if disconnected:
                # Client has gone away; skip persisting assistant message to avoid wasting work.
                return

            if producer_exc is not None:
                raise producer_exc

            full_response = "".join(response_parts)
            if isinstance(metrics_data, dict):
                metrics_data = _annotate_chat_cache_metrics(
                    metrics_data,
                    enabled=cache_feature_enabled,
                    hit=cache_hit,
                    skip_reason=None if cache_hit else cache_skip_reason,
                )
            else:
                metrics_data = _annotate_chat_cache_metrics(
                    {},
                    enabled=cache_feature_enabled,
                    hit=cache_hit,
                    skip_reason=None if cache_hit else cache_skip_reason,
                )

            # Optional: store response in Redis cache after streaming (best-effort).
            if cache_eligible and (not cache_hit) and cache_key and full_response.strip():
                cache_payload = jsonable_encoder(
                    {
                        "content": full_response,
                        "citations": citations_data,
                        "metrics": metrics_data,
                        "structured_data": structured_data,
                    }
                )
                stored = bool(set_cached_chat_response(cache_key, cache_payload))
                metrics_data.setdefault("chat_cache_store_ok", stored)

            # 4. Persist assistant response.
            if dataset_id_used is not None and isinstance(metrics_data, dict):
                metrics_data.setdefault("dataset_id", str(dataset_id_used))
            if tenant_qps_meta.get("enabled") and isinstance(metrics_data, dict):
                metrics_data.setdefault("tenant_qps_quota", tenant_qps_meta)
            if quota_meta.get("enabled") and isinstance(metrics_data, dict):
                metrics_data.setdefault("quota", quota_meta)

            if persist_in_background:
                with contextlib.suppress(Exception):
                    _spawn_background_task(
                        _persist_chat_stream_turn_background(
                            tenant_id=tenant_id,
                            conversation_id=conversation_id,
                            account_id=account_id,
                            assistant_message_id=assistant_message_id,
                            request_id=str(request_id),
                            question=request.message,
                            document_count=len(doc_ids_to_use),
                            content=full_response,
                            citations=citations_data,
                            metrics=metrics_data,
                            dataset_id_used=dataset_id_used,
                            cache_hit=cache_hit,
                            cache_key=cache_key,
                            cache_eligible=False,
                            structured_data=structured_data,
                            ip=client_ip,
                            user_agent=user_agent,
                            enable_summary_memory=enable_summary_memory,
                            enable_structured_memory=enable_structured_memory,
                        )
                        )
                return

            message_metadata = _build_chat_message_metadata(
                request_id=str(request_id),
                original_question=request.message,
                metrics=metrics_data,
                citations=citations_data if isinstance(citations_data, list) else [],
            )
            if enable_structured_memory and bool(getattr(settings, "STRUCTURED_MEMORY_ENABLED", False)):
                try:
                    message_metadata["structured_memory"] = extract_structured_memory_for_turn(
                        user_text=str(request.message or ""),
                        assistant_text=str(full_response or ""),
                        max_entities=int(getattr(settings, "STRUCTURED_MEMORY_MAX_ENTITIES", 20) or 20),
                        max_facts=int(getattr(settings, "STRUCTURED_MEMORY_MAX_FACTS", 8) or 8),
                    )
                except Exception:
                    pass

            assistant_message = Message(
                id=assistant_message_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role='assistant',
                content=full_response,
                citations=citations_data,
                token_count=num_tokens_from_string(full_response or ""),
                message_metadata=message_metadata,
            )
            db.add(assistant_message)

            audit_log_event(
                db,
                tenant_id=tenant_id,
                actor_id=account_id,
                action=CHAT_STREAM_AUDIT_ACTION,
                resource_type="conversation",
                resource_id=str(conversation_id),
                request_id=str(request_id),
                ip=getattr(getattr(http_request, "client", None), "host", None),
                user_agent=http_request.headers.get("user-agent"),
                details=build_chat_audit_details(
                    question=request.message,
                    document_count=len(doc_ids_to_use),
                    dataset_id=dataset_id_used,
                    cache_hit=cache_hit,
                ),
            )

            # Update conversation metadata without relying on the pre-stream ORM instance.
            _touch_conversation_after_turn(db=db, tenant_id=tenant_id, conversation_id=conversation_id)
            db.commit()

            if (
                bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False))
                and bool(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False))
                and bool(getattr(request, "enable_summary_memory", False))
                and conversation_id
            ):
                with contextlib.suppress(Exception):
                    _spawn_background_task(_auto_update_summary_background(tenant_id=tenant_id, conversation_id=conversation_id))

        except Exception as e:
            logger.error("Chat stream error: %s", str(e)[:200])
            is_production = is_production_env()
            detail = _format_stream_error_message(e)
            message = "An error occurred during chat processing"
            if not is_production and detail:
                message = f"{message}: {detail[:200]}"
            error_event = {
                "type": "error",
                "data": {
                    "message": message,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "error_id": str(request_id),
                },
                "request_id": str(request_id),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Conversation-ID": str(conversation_id) if conversation_id else "",
            "X-Assistant-Message-ID": str(assistant_message_id),
            "Access-Control-Expose-Headers": "X-Request-ID, X-Conversation-ID, X-Assistant-Message-ID",
        }
    )

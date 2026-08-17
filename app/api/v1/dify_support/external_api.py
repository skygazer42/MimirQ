"""Dify external API schemas, auth, and conversation trace helpers."""

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.api.v1.dify_support.anchor_strength import _dify_kg_bool, _dify_kg_float, _dify_kg_int
from app.api.v1.dify_support.common import _clamp_score
from app.api.v1.dify_support.scoring import _diagnostic_query_hash
from app.core.config import settings
from app.models.chat import Conversation, Message
from app.rag.core.logging import get_logger
from app.services.external_conversation_ingest import _mimirq_citations_for_storage

logger = get_logger("app.api.v1.integrations_dify")

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS = 160
_DIFY_TRACE_QUERY_PATH_MAX_CHARS = 120
_DIFY_TRACE_CITATION_METADATA_KEYS = (
    "document_id",
    "chunk_id",
    "chunk_index",
    "page_number",
    "start_char",
    "end_char",
    "retrieval_role",
    "neighbor_of",
    "doc_pipeline_key",
    "pipeline_hash",
    "relevance_score",
    "vector_score",
    "bm25_score",
    "lexical_score",
    "sparse_score",
    "colbert_score",
    "keyword_score",
    "rerank_score",
    "retrieval_score",
    "reranker_provider",
    "rerank_elapsed_sec",
    "rerank_model_used",
    "hit_type",
    "has_image",
    "kg_path",
    "kg_path_provenance",
)


def _api():
    # Resolve helpers from integrations_dify at call time so existing
    # monkeypatch targets in tests keep affecting moved implementations.
    from app.api.v1 import integrations_dify

    return integrations_dify


@dataclass(frozen=True)
class _DifyActor:
    tenant_id: UUID
    account_id: str


class DifyRetrievalSetting(BaseModel):
    top_k: int = Field(default=5, ge=1, le=200)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    # MimirQ extension: "fast" keeps online chat latency low by disabling
    # expensive fallback/rerank branches. Omit for the existing quality path.
    latency_profile: str | None = Field(default=None, max_length=32)
    # MimirQ-compatible extension for direct gates and internal probes.
    # Dify's standard payload can omit these fields; None keeps env/default behavior.
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = Field(default=None, ge=0, le=50)
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    kg_chunk_boost_max_promoted: int | None = Field(default=None, ge=0, le=20)


@dataclass(frozen=True)
class _DifyKGFlags:
    enable_query_expansion: bool
    enable_chunk_injection: bool
    chunk_injection_max_chunks: int
    enable_chunk_boost: bool
    chunk_boost_weight: float
    chunk_boost_max_promoted: int

    @property
    def enabled(self) -> bool:
        return bool(self.enable_query_expansion or self.enable_chunk_injection or self.enable_chunk_boost)


def _disabled_dify_kg_flags() -> _DifyKGFlags:
    return _DifyKGFlags(
        enable_query_expansion=False,
        enable_chunk_injection=False,
        chunk_injection_max_chunks=0,
        enable_chunk_boost=False,
        chunk_boost_weight=0.0,
        chunk_boost_max_promoted=0,
    )


def _resolve_dify_kg_flags(setting: DifyRetrievalSetting) -> _DifyKGFlags:
    return _DifyKGFlags(
        enable_query_expansion=(
            _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", False)
            if setting.enable_kg_query_expansion is None
            else bool(setting.enable_kg_query_expansion)
        ),
        enable_chunk_injection=(
            _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", False)
            if setting.enable_kg_chunk_injection is None
            else bool(setting.enable_kg_chunk_injection)
        ),
        chunk_injection_max_chunks=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3)
            if setting.kg_chunk_injection_max_chunks is None
            else int(setting.kg_chunk_injection_max_chunks)
        ),
        enable_chunk_boost=(
            _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)
            if setting.enable_kg_chunk_boost is None
            else bool(setting.enable_kg_chunk_boost)
        ),
        chunk_boost_weight=(
            _dify_kg_float("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25)
            if setting.kg_chunk_boost_weight is None
            else float(setting.kg_chunk_boost_weight)
        ),
        chunk_boost_max_promoted=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2)
            if setting.kg_chunk_boost_max_promoted is None
            else int(setting.kg_chunk_boost_max_promoted)
        ),
    )


class DifyExternalKnowledgeRequest(BaseModel):
    knowledge_id: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    retrieval_setting: DifyRetrievalSetting = Field(default_factory=DifyRetrievalSetting)
    metadata_condition: dict[str, Any] | None = None
    # MimirQ extension: lets Dify HTTP/workflow calls attach retrieval traces
    # to the existing History RAG Trace panel.
    conversation_id: UUID | str | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_conversation_id: str | None = Field(default=None, max_length=255)
    source_message_id: str | None = Field(default=None, max_length=255)
    source_run_id: str | None = Field(default=None, max_length=255)
    dify_conversation_id: str | None = Field(default=None, max_length=255)
    dify_message_id: str | None = Field(default=None, max_length=200)
    dify_workflow_run_id: str | None = Field(default=None, max_length=200)


class DifyExternalKnowledgeRecord(BaseModel):
    content: str
    score: float
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DifyExternalKnowledgeResponse(BaseModel):
    records: list[DifyExternalKnowledgeRecord]


def _resolve_dify_latency_profile(setting: DifyRetrievalSetting) -> str:
    raw = str(setting.latency_profile or "").strip().lower().replace("-", "_")
    if not raw or raw in {"default", "quality", "standard"}:
        return "quality"
    if raw in {"fast", "low_latency", "online"}:
        return "fast"
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported Dify retrieval latency_profile: {setting.latency_profile}",
    )


class DifyConversationTurnRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
    answer: str = Field(min_length=1)
    conversation_id: UUID | str | None = None
    trace_request_id: str | None = Field(default=None, max_length=200)
    source_conversation_id: str | None = Field(default=None, max_length=255)
    source_message_id: str | None = Field(default=None, max_length=255)
    source_run_id: str | None = Field(default=None, max_length=255)
    dify_conversation_id: str | None = Field(default=None, max_length=255)
    dify_message_id: str | None = Field(default=None, max_length=200)
    dify_workflow_run_id: str | None = Field(default=None, max_length=200)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DifyConversationTurnResponse(BaseModel):
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    reused_user_message: bool


def _first_nonempty_str(*values: object) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _uuid_or_none(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _dify_trace_citation(record: DifyExternalKnowledgeRecord, *, elapsed_sec: float | None) -> dict[str, Any]:
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    citation = {key: metadata.get(key) for key in _DIFY_TRACE_CITATION_METADATA_KEYS if metadata.get(key) is not None}
    citation.setdefault("relevance_score", _clamp_score(record.score))
    citation.setdefault("retrieval_score", _clamp_score(record.score))
    citation.setdefault("retrieval_mode", "dify_external_knowledge")
    if elapsed_sec is not None:
        citation.setdefault("retrieval_elapsed_sec", elapsed_sec)
    return citation


def _first_reranker_provider(records: list[DifyExternalKnowledgeRecord]) -> str | None:
    for record in records or []:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        provider = _first_nonempty_str(metadata.get("reranker_provider"))
        if provider:
            return provider
    return None


def _has_dify_rerank(records: list[DifyExternalKnowledgeRecord]) -> bool:
    for record in records or []:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        if any(
            metadata.get(key) is not None
            for key in ("reranker_provider", "rerank_score", "rerank_elapsed_sec", "rerank_model_used")
        ):
            return True
    return False


def _bounded_trace_query_preview(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS]


def _dify_trace_retrieval_queries(
    *,
    question: str,
    retrieval_path: str,
    retrieval_queries: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    rows = list(retrieval_queries or [])
    if not rows:
        rows = [{"kind": "main", "query": question, "path": retrieval_path, "ok": True}]

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        query_text = str(row.get("query") or "").strip()
        query_preview = _bounded_trace_query_preview(query_text)
        path = str(row.get("path") or "").strip()[:_DIFY_TRACE_QUERY_PATH_MAX_CHARS]
        item = {
            "kind": _first_nonempty_str(row.get("kind")) or "subq",
            "query_chars": len(query_text),
            "ok": bool(row.get("ok", True)),
        }
        if query_preview:
            item["query_preview"] = query_preview
        if path:
            item["path"] = path
        elapsed_sec = row.get("elapsed_sec")
        if isinstance(elapsed_sec, int | float):
            item["elapsed_sec"] = round(max(0.0, float(elapsed_sec)), 6)
        out.append(item)
    return out


def _log_dify_external_rag_trace(
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    request_id: str | None,
    question: str,
    response_records: list[DifyExternalKnowledgeRecord],
    top_k: int,
    candidate_top_k: int,
    retrieval_path: str,
    elapsed_ms: float,
    metadata_anchor_fallback_count: int,
    mixed_intent_query_count: int,
    retrieval_queries: list[dict[str, Any]] | None = None,
    dify_message_id: str | None = None,
    dify_workflow_run_id: str | None = None,
) -> None:
    if conversation_id is None:
        return
    resolved_request_id = _first_nonempty_str(request_id) or f"dify-{uuid.uuid4().hex}"
    elapsed_sec = round(max(0.0, float(elapsed_ms or 0.0)) / 1000.0, 6)
    records = list(response_records or [])
    citations = [_dify_trace_citation(record, elapsed_sec=elapsed_sec) for record in records]
    reranker_provider = _first_reranker_provider(records)
    per_query = _dify_trace_retrieval_queries(
        question=question,
        retrieval_path=retrieval_path,
        retrieval_queries=retrieval_queries,
    )
    _api().log_metrics(
        {
            "event": "rag_trace",
            "source": "dify_external_knowledge",
            "conversation_id": str(conversation_id),
            "tenant_id": str(tenant_id),
            "request_id": str(resolved_request_id),
            "question": str(question or ""),
            "query_for_retrieval": str(question or ""),
            "citations_count": len(citations),
            "citations": citations,
            "retrieval": {
                "mode": "dify_external_knowledge",
                "requested_mode": "external_knowledge",
                "top_k": int(top_k),
                "query_count": max(len(per_query), 1 + max(0, int(mixed_intent_query_count or 0))),
                "per_query": per_query,
                "elapsed_sec": elapsed_sec,
                "errors": [],
                "enable_reranker": _has_dify_rerank(records),
                "reranker_provider": reranker_provider,
                "reranker_top_n": int(candidate_top_k),
            },
            "route": "dify_external_knowledge",
            "retrieval_path": str(retrieval_path or ""),
            "metadata_anchor_fallback_count": int(metadata_anchor_fallback_count or 0),
            "dify_message_id": _first_nonempty_str(dify_message_id),
            "dify_workflow_run_id": _first_nonempty_str(dify_workflow_run_id),
        }
    )


def _log_dify_result_rag_trace(
    *,
    tenant_id: UUID,
    conversation_id: UUID | None,
    request_id: str | None,
    question: str,
    answer: str,
    source_conversation_id: str | None,
    source_message_id: str | None,
    source_run_id: str | None,
    citations: list[dict[str, Any]],
) -> None:
    if conversation_id is None:
        return
    final_answer = str(answer or "")
    safe_citations = [item for item in citations or [] if isinstance(item, dict)]
    _api().log_metrics(
        {
            "event": "rag_trace",
            "source": "dify_result",
            "conversation_id": str(conversation_id),
            "tenant_id": str(tenant_id),
            "request_id": _first_nonempty_str(request_id) or f"dify-result-{uuid.uuid4().hex}",
            "question_hash": _diagnostic_query_hash(str(question or "")),
            "retrieval": {
                "mode": "dify_result",
                "requested_mode": "dify_workflow",
                "top_k": 0,
                "query_count": 0,
                "errors": [],
                "enable_reranker": False,
            },
            "citations_count": len(safe_citations),
            "citations": [_dify_result_trace_citation(item) for item in safe_citations],
            "dify_result": {
                "status": "completed",
                "answer_chars": len(final_answer),
                "answer_hash": _diagnostic_query_hash(final_answer),
                "source_conversation_id": _first_nonempty_str(source_conversation_id),
                "source_message_id": _first_nonempty_str(source_message_id),
                "source_run_id": _first_nonempty_str(source_run_id),
                "citations_count": len(safe_citations),
            },
        }
    )


def _dify_result_trace_citation(citation: dict[str, Any]) -> dict[str, Any]:
    safe = {key: citation.get(key) for key in _DIFY_TRACE_CITATION_METADATA_KEYS if citation.get(key) is not None}
    safe.setdefault("retrieval_mode", "dify_result")
    return safe


def _dify_trace_source_conversation_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    body_conversation_id = body.conversation_id
    non_uuid_body_conversation_id = None
    if body_conversation_id is not None and _uuid_or_none(body_conversation_id) is None:
        non_uuid_body_conversation_id = str(body_conversation_id).strip()
    return _first_nonempty_str(
        body.source_conversation_id,
        body.dify_conversation_id,
        non_uuid_body_conversation_id,
        request.headers.get("x-mimirq-source-conversation-id"),
        request.headers.get("x-dify-conversation-id"),
        request.headers.get("x-source-conversation-id"),
    )


def _dify_trace_source_message_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.source_message_id,
        body.dify_message_id,
        request.headers.get("x-mimirq-source-message-id"),
        request.headers.get("x-dify-message-id"),
        request.headers.get("x-source-message-id"),
    )


def _dify_trace_source_run_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.source_run_id,
        body.dify_workflow_run_id,
        request.headers.get("x-mimirq-source-run-id"),
        request.headers.get("x-dify-workflow-run-id"),
        request.headers.get("x-source-run-id"),
    )


def _external_conversation_metadata_text(field: str):
    return Message.message_metadata["external_conversation"][field].astext  # type: ignore[index]


def _find_dify_trace_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    source_conversation_id: str,
) -> UUID | None:
    row = (
        db.query(Message.conversation_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Conversation.owner_account_id == str(account_id or "").strip(),
            _external_conversation_metadata_text("source") == "dify",
            _external_conversation_metadata_text("source_conversation_id") == source_conversation_id,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )
    if not row:
        return None
    return row[0]


def _conversation_owner_matches_account(conversation: Conversation | None, *, account_id: str) -> bool:
    if conversation is None:
        return False
    owner_account_id = str(getattr(conversation, "owner_account_id", "") or "").strip()
    return bool(owner_account_id) and owner_account_id == str(account_id or "").strip()


def _ensure_dify_trace_conversation_accessible(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    account_id: str,
    source_conversation_id: str | None = None,
) -> Conversation:
    api = _api()
    conversation = api._load_dify_trace_conversation(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not api._conversation_owner_matches_account(conversation, account_id=account_id):
        raise HTTPException(status_code=403, detail="Conversation is not accessible")
    expected_source_id = str(source_conversation_id or "").strip()
    if expected_source_id:
        bound_conversation_id = api._find_dify_trace_conversation(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            source_conversation_id=expected_source_id,
        )
        if bound_conversation_id != conversation_id:
            raise HTTPException(status_code=403, detail="Conversation source does not match")
    return conversation


def _load_dify_trace_conversation(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(Conversation.tenant_id == tenant_id, Conversation.id == conversation_id)
        .with_for_update()
        .first()
    )


def _dify_turn_source_conversation_id(body: DifyConversationTurnRequest) -> str | None:
    body_conversation_id = body.conversation_id
    non_uuid_body_conversation_id = None
    if body_conversation_id is not None and _uuid_or_none(body_conversation_id) is None:
        non_uuid_body_conversation_id = str(body_conversation_id).strip()
    return _first_nonempty_str(
        body.source_conversation_id,
        body.dify_conversation_id,
        non_uuid_body_conversation_id,
    )


def _dify_turn_source_message_id(body: DifyConversationTurnRequest) -> str | None:
    return _first_nonempty_str(body.source_message_id, body.dify_message_id)


def _dify_turn_source_run_id(body: DifyConversationTurnRequest) -> str | None:
    return _first_nonempty_str(body.source_run_id, body.dify_workflow_run_id)


def _dify_external_conversation_metadata(
    *,
    account_id: str,
    source_conversation_id: str | None,
    source_message_id: str | None,
    source_run_id: str | None,
    trace_request_id: str | None,
    role: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "external_conversation": {
            "source": "dify",
            "source_conversation_id": source_conversation_id,
            "source_message_id": source_message_id,
            "source_run_id": source_run_id,
            "trace_request_id": trace_request_id,
            "imported_by": account_id,
            "imported_at": datetime.now(UTC).isoformat(),
            "role": role,
        }
    }
    if isinstance(extra, dict) and extra:
        metadata["external_conversation"]["metadata"] = extra
    return metadata


def _find_reusable_dify_seed_message(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    source_conversation_id: str | None,
    source_message_id: str | None,
) -> Message | None:
    query = db.query(Message).filter(
        Message.tenant_id == tenant_id,
        Message.conversation_id == conversation_id,
        Message.role == "user",
        _external_conversation_metadata_text("source") == "dify",
        Message.message_metadata["external_conversation"]["trace_seed"].astext == "true",  # type: ignore[index]
    )
    if source_conversation_id:
        query = query.filter(_external_conversation_metadata_text("source_conversation_id") == source_conversation_id)
    if source_message_id:
        query = query.filter(_external_conversation_metadata_text("source_message_id") == source_message_id)
    return query.order_by(Message.created_at.asc(), Message.id.asc()).first()


def _find_persisted_dify_conversation_turn(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    source_conversation_id: str | None,
    source_message_id: str | None,
) -> tuple[Message, Message] | None:
    if not source_message_id:
        return None
    query = db.query(Message).filter(
        Message.tenant_id == tenant_id,
        Message.conversation_id == conversation_id,
        Message.role.in_(("user", "assistant")),
        _external_conversation_metadata_text("source") == "dify",
        _external_conversation_metadata_text("source_message_id") == source_message_id,
        _external_conversation_metadata_text("turn_persisted") == "true",
    )
    if source_conversation_id:
        query = query.filter(_external_conversation_metadata_text("source_conversation_id") == source_conversation_id)
    messages = query.order_by(Message.created_at.asc(), Message.id.asc()).all()
    user_message = next((message for message in messages if message.role == "user"), None)
    assistant_message = next((message for message in messages if message.role == "assistant"), None)
    if user_message is None or assistant_message is None:
        return None
    return user_message, assistant_message


def _lock_dify_conversation_turn_scope(
    *,
    db: Session,
    tenant_id: UUID,
    conversation_scope: str,
) -> None:
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
        return
    digest = hashlib.sha256(f"dify-turn:{tenant_id}:{conversation_scope}".encode()).digest()
    lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    db.execute(sql_text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def _dify_turn_citations_for_storage(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _mimirq_citations_for_storage([item for item in citations or [] if isinstance(item, dict)])


def _dify_trace_title(question: str) -> str:
    title = str(question or "").strip()
    return title[:80] if title else "Dify external retrieval"


def _ensure_dify_trace_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    source_conversation_id: str,
    source_message_id: str | None,
    source_run_id: str | None,
    question: str,
) -> UUID | None:
    api = _api()
    source_conversation_id = str(source_conversation_id or "").strip()
    if not source_conversation_id:
        return None

    try:
        api._lock_dify_conversation_turn_scope(
            db=db,
            tenant_id=tenant_id,
            conversation_scope=source_conversation_id,
        )
        existing_id = api._find_dify_trace_conversation(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
        )
        if existing_id is not None:
            existing = api._load_dify_trace_conversation(
                db,
                tenant_id=tenant_id,
                conversation_id=existing_id,
            )
            if not api._conversation_owner_matches_account(existing, account_id=account_id):
                logger.warning(
                    "Refusing to reuse Dify trace conversation across owners: tenant=%s source_conversation_id=%s",
                    tenant_id,
                    source_conversation_id,
                )
                return None
            return existing_id

        if not settings.DIFY_EXTERNAL_KNOWLEDGE_TRACE_AUTO_CREATE_CONVERSATION_ENABLED:
            return None

        now = datetime.now(UTC)
        conversation = Conversation(
            tenant_id=tenant_id,
            owner_account_id=str(account_id or "").strip() or None,
            title=_dify_trace_title(question),
            title_source="auto",
            document_ids=[],
            message_count=1,
            updated_at=now,
        )
        db.add(conversation)
        db.flush()

        message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=str(question or "").strip() or source_conversation_id,
            citations=[],
            message_metadata={
                "external_conversation": {
                    "source": "dify",
                    "source_conversation_id": source_conversation_id,
                    "source_message_id": source_message_id,
                    "source_run_id": source_run_id,
                    "imported_by": account_id,
                    "imported_at": now.isoformat(),
                    "trace_seed": True,
                }
            },
            created_at=now,
        )
        db.add(message)
        db.commit()
        return conversation.id
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("Ignoring Dify trace conversation rollback failure", exc_info=True)
        logger.warning("Failed to ensure Dify trace conversation: %s", str(exc)[:200])
        return None


def _persist_dify_conversation_turn(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    query: str,
    answer: str,
    trace_request_id: str | None,
    source_conversation_id: str | None,
    source_message_id: str | None,
    source_run_id: str | None,
    citations: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    conversation_id: UUID | None = None,
) -> DifyConversationTurnResponse:
    api = _api()
    source_conversation_id = str(source_conversation_id or "").strip() or None
    source_message_id = str(source_message_id or "").strip() or None
    source_run_id = str(source_run_id or "").strip() or None
    trace_request_id = str(trace_request_id or "").strip() or None
    question = str(query or "").strip()
    final_answer = str(answer or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="query is required")
    if not final_answer:
        raise HTTPException(status_code=400, detail="answer is required")

    if conversation_id is not None:
        conversation_scope = source_conversation_id or str(conversation_id)
        api._lock_dify_conversation_turn_scope(
            db=db,
            tenant_id=tenant_id,
            conversation_scope=conversation_scope,
        )
        conversation = api._ensure_dify_trace_conversation_accessible(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
        )
    else:
        if not source_conversation_id:
            raise HTTPException(status_code=400, detail="dify_conversation_id is required")
        resolved_id = api._ensure_dify_trace_conversation(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            source_conversation_id=source_conversation_id,
            source_message_id=source_message_id,
            source_run_id=source_run_id,
            question=question,
        )
        if resolved_id is None:
            raise HTTPException(status_code=503, detail="Failed to resolve Dify conversation")
        conversation = api._load_dify_trace_conversation(db, tenant_id=tenant_id, conversation_id=resolved_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    if not api._conversation_owner_matches_account(conversation, account_id=account_id):
        raise HTTPException(status_code=403, detail="Conversation is not accessible")

    persisted_turn = api._find_persisted_dify_conversation_turn(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    if persisted_turn is not None:
        user_message, assistant_message = persisted_turn
        return DifyConversationTurnResponse(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            reused_user_message=True,
        )

    now = datetime.now(UTC)
    user_metadata = api._dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="user",
        extra=metadata,
    )
    assistant_metadata = api._dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="assistant",
        extra=metadata,
    )

    reusable_user = api._find_reusable_dify_seed_message(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
    )
    reused_user_message = reusable_user is not None
    if reusable_user is not None:
        reusable_user.content = question
        reusable_user.message_metadata = {
            **user_metadata,
            "external_conversation": {
                **user_metadata["external_conversation"],
                "trace_seed": False,
                "turn_persisted": True,
            },
        }
        user_message = reusable_user
    else:
        user_message = Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=question,
            citations=[],
            message_metadata={
                **user_metadata,
                "external_conversation": {
                    **user_metadata["external_conversation"],
                    "turn_persisted": True,
                },
            },
            created_at=now,
        )
        db.add(user_message)
        db.flush()

    assistant_message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role="assistant",
        content=final_answer,
        citations=api._dify_turn_citations_for_storage(citations),
        message_metadata={
            **assistant_metadata,
            "external_conversation": {
                **assistant_metadata["external_conversation"],
                "turn_persisted": True,
            },
        },
        created_at=now,
    )
    db.add(assistant_message)
    db.flush()

    conversation.updated_at = now
    conversation.message_count = (
        db.query(Message).filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation.id).count()
    )
    db.commit()
    api._log_dify_result_rag_trace(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        request_id=trace_request_id,
        question=question,
        answer=final_answer,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        citations=citations,
    )
    return DifyConversationTurnResponse(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        reused_user_message=reused_user_message,
    )


def _dify_trace_conversation_id(
    request: Request,
    body: DifyExternalKnowledgeRequest,
    *,
    db: Session | None = None,
    tenant_id: UUID | None = None,
    account_id: str | None = None,
) -> UUID | None:
    api = _api()
    source_conversation_id = _dify_trace_source_conversation_id(request, body)
    body_conversation_id = _uuid_or_none(body.conversation_id)
    if body_conversation_id is not None:
        if db is not None and tenant_id is not None and account_id is not None:
            api._ensure_dify_trace_conversation_accessible(
                db=db,
                tenant_id=tenant_id,
                conversation_id=body_conversation_id,
                account_id=account_id,
                source_conversation_id=source_conversation_id,
            )
        return body_conversation_id
    for header_name in ("x-mimirq-conversation-id", "x-conversation-id"):
        raw = str(request.headers.get(header_name) or "").strip()
        if not raw:
            continue
        header_conversation_id = _uuid_or_none(raw)
        if header_conversation_id is not None:
            if db is not None and tenant_id is not None and account_id is not None:
                api._ensure_dify_trace_conversation_accessible(
                    db=db,
                    tenant_id=tenant_id,
                    conversation_id=header_conversation_id,
                    account_id=account_id,
                    source_conversation_id=source_conversation_id,
                )
            return header_conversation_id
        logger.debug("Ignoring invalid Dify trace conversation header %s", header_name)
    if db is None or tenant_id is None or account_id is None:
        return None

    if not source_conversation_id:
        return None
    return api._ensure_dify_trace_conversation(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=_dify_trace_source_message_id(request, body),
        source_run_id=_dify_trace_source_run_id(request, body),
        question=body.query,
    )


def _dify_trace_request_id(request: Request, body: DifyExternalKnowledgeRequest) -> str | None:
    return _first_nonempty_str(
        body.request_id,
        request.headers.get("x-mimirq-request-id"),
        request.headers.get("x-request-id"),
        getattr(request.state, "request_id", None),
    )


def _split_items(raw: object) -> list[str]:
    return [part for part in _TOKEN_SPLIT_RE.split(str(raw or "").strip()) if part]


def _token_matches(provided_token: str, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    provided = str(provided_token or "").strip()
    if not expected or not provided:
        return False
    if expected.lower().startswith("sha256:"):
        digest = expected.split(":", 1)[1].strip().lower()
        if not digest:
            return False
        provided_digest = hashlib.sha256(provided.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided, expected)


def _extract_bearer_token(authorization: str | None) -> str:
    raw = str(authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid Dify Authorization header")
    return token


def _coerce_uuid(value: object, *, label: str) -> UUID:
    try:
        return UUID(str(value or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}") from exc


def _require_dify_actor(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> _DifyActor:
    api = _api()
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        raise HTTPException(status_code=404, detail="Dify external knowledge is disabled")

    expected_tokens = _split_items(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", ""))
    if not expected_tokens:
        raise HTTPException(status_code=503, detail="Dify external knowledge API key is not configured")

    provided = _extract_bearer_token(authorization)
    if not any(_token_matches(provided, expected) for expected in expected_tokens):
        raise HTTPException(status_code=401, detail="Invalid Dify API key")

    raw_tenant = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "") or "").strip()
    if not raw_tenant:
        if api.is_production_env():
            raise HTTPException(
                status_code=503,
                detail="Dify external knowledge tenant is not configured",
            )
        raw_tenant = str(
            request.headers.get(str(getattr(settings, "TENANT_HEADER", "X-Tenant-ID") or "X-Tenant-ID"))
            or getattr(settings, "DEFAULT_TENANT_ID", "")
        ).strip()
    tenant_id = _coerce_uuid(raw_tenant, label="Dify tenant id")
    account_id = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "") or "system:dify").strip()
    if not account_id:
        raise HTTPException(status_code=503, detail="Dify external knowledge account is not configured")
    return _DifyActor(tenant_id=tenant_id, account_id=account_id)

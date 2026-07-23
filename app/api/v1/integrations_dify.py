"""
Dify external knowledge adapter.

This router exposes MimirQ datasets as a Dify External Knowledge API source.
Dify calls this endpoint with a `knowledge_id`; MimirQ maps it to one or more
dataset IDs, runs the existing retrieval-only pipeline, and returns Dify records.
"""


import asyncio
import contextlib
import hashlib
import hmac
import json
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy import Text as SQLText
from sqlalchemy import and_, or_
from sqlalchemy import cast as sql_cast
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.api.schemas.chat import ChatRAGConfig
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.chat import Conversation, Message
from app.models.dataset import Dataset
from app.models.document import Document, DocumentChunk
from app.rag.core.logging import get_logger
from app.rag.pipeline_plugins.contracts import DISPLAY_METADATA_KEY, EVALUABLE_METADATA_KEY, INDEXED_METADATA_KEY
from app.rag.reranker.factory import get_reranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.planner import (
    DatasetRouteHint,
    DatasetScopePlan,
    compact_high_confidence_items,
    normalize_route_mode,
    plan_dataset_scope,
    resolve_internal_candidate_top_k,
    retrieval_policy_fallback_multiplier,
    retrieval_policy_mixed_intent_leading_noise_terms,
    retrieval_policy_mixed_intent_subject_terms,
    retrieval_policy_query_terms,
    retrieval_policy_response_compaction,
    retrieval_policy_service_anchor_noise_terms,
    retrieval_policy_service_anchor_priority_terms,
    retrieval_policy_service_anchor_query_rewrite_terms,
)
from app.rag.retrieval.plugin_policy import (
    filter_records_by_retrieval_policy_alignment,
    record_retrieval_policy_anchor_binding_scores,
    record_retrieval_policy_bonus,
    records_retrieval_policy_diagnostics,
)
from app.services.chat_response_cache import InflightResponseLeaderCancelledError
from app.services.chat_response_cache import (
    acquire_inflight_chat_response as acquire_inflight_response,
)
from app.services.chat_response_cache import (
    reject_inflight_chat_response as reject_inflight_response,
)
from app.services.chat_response_cache import (
    resolve_inflight_chat_response as resolve_inflight_response,
)
from app.services.external_conversation_ingest import _mimirq_citations_for_storage
from app.services.metrics_logger import log_metrics
from app.services.rag_runtime_limiter import (
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call,
)

logger = get_logger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    401: {"description": "Unauthorized"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    503: {"description": "Service Unavailable"},
}

_TOKEN_SPLIT_RE = re.compile(r"[,\s]+")
_CONTENT_KEYS = ("content", "chunk_content", "text", "quote", "snippet", "page_content")
_TITLE_KEYS = ("title", "document_name", "filename", "source", "document_id", "chunk_id")
_SCORE_KEYS = (
    "score",
    "relevance_score",
    "retrieval_score",
    "rerank_score",
    "vector_score",
    "bm25_score",
    "keyword_score",
    "mimirq_score",
)
_METADATA_SCORE_KEYS = tuple(key for key in _SCORE_KEYS if key != "score")
_METADATA_KEYS = (
    "document_id",
    "chunk_id",
    "chunk_index",
    "page_number",
    "header_path",
    "source_path",
    "retrieval_role",
    "hit_type",
    "rerank_score",
    "rerank_score_final",
    "reranker_provider",
    "rerank_elapsed_sec",
    "rerank_model_used",
    "kg_pagerank",
    "kg_path_length",
    "kg_shared_events",
    "kg_evidence_anchored",
    "kg_path",
    "kg_path_provenance",
    "kg_duplicate_candidate",
    "kg_edge_conf_low",
    "kg_edge_conf_mid",
    "kg_edge_conf_high",
)
_PUBLIC_METADATA_VIEW_KEYS = (EVALUABLE_METADATA_KEY, DISPLAY_METADATA_KEY)
_RETRIEVAL_METADATA_VIEW_KEYS = (INDEXED_METADATA_KEY, *_PUBLIC_METADATA_VIEW_KEYS)
_RETRIEVAL_INTENT_KEYS = ("retrieval_intents", "query_intents", "intent_terms")
_EXACT_QUERY_ANCHOR_FIELDS = (
    "question",
    "primary_alias",
    "aliases",
    "source_topic",
    "title",
)
_METADATA_ANCHOR_KEYS = (
    "question",
    "aliases",
    "primary_alias",
    "service_name",
    "service_aliases",
    "case_title",
    "source_topic",
    "title",
)
_FUZZY_METADATA_ANCHOR_KEYS = (
    "service_name",
    "aliases",
    "primary_alias",
    "service_aliases",
    "case_title",
    "source_topic",
    "title",
)
_REGION_ANCHOR_KEYS = ("district", "applicable_area")
_MIN_REGION_ANCHOR_OVERLAP_CHARS = 3
_MIN_REGIONAL_QUESTION_OVERLAP_CHARS = 8
_MIN_SPECIFIC_INTENT_CHARS = 7
_MIN_QUERY_INTENT_SUBJECT_OVERLAP_CHARS = 3
_INTENT_MATCH_BONUS = 0.06
_INTENT_MATCH_BONUS_MAX = 0.18
_QUESTION_INTENT_MATCH_BONUS = 0.2
_EXACT_PRIMARY_ALIAS_MATCH_BONUS = 0.16
_URL_EVIDENCE_BONUS = 0.04
_URL_EVIDENCE_BONUS_MAX = 0.08
_SOURCE_RECORD_ID_KEYS = ("source_record_id", "record_id")
_SOURCE_RECORD_SCOPE_KEYS = ("knowledge_section", "source_file", "source_topic", "document_id")
_DEFAULT_RESPONSE_HINT_ANSWER_PREFIX = "Answer highlights"
_DEFAULT_RESPONSE_HINT_SOURCE_PREFIX = "Source evidence"
_MAX_HINT_VALUE_CHARS = 700
_MAX_QA_HINT_VALUE_CHARS = 420
_ANSWERFUL_RECORD_BONUS = 0.08
_ANCHOR_ONLY_QA_RECORD_PENALTY = 0.28
_QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH = 0.8
_QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS = 8
_QUESTION_ANCHOR_NEAR_MATCH_MIN_RATIO = 0.86
_QUESTION_ANCHOR_BIGRAM_MIN_OVERLAP = 3
_QUESTION_ANCHOR_BIGRAM_MIN_RATIO = 0.5
_QUESTION_ANCHOR_QUERY_MARKERS = ("是否", "能否", "可否", "什么是", "为什么", "怎么", "如何", "哪里", "吗", "？", "?")
_EXPLICIT_QUESTION_FORM_MARKERS = ("请问", "是否", "能否", "可否", "吗", "？", "?", "什么是", "为什么")
_MIXED_INTENT_QUERY_MARKERS = (
    "另外",
    "同时",
    "以及",
    "并且",
    "还想",
    "还要",
    "一次知道",
    "分别",
    "顺便",
    "合并回答",
    "一并回答",
    "一起回答",
    "分别回答",
    "分开回答",
    "请合并",
    "请分别",
)
_MIXED_INTENT_DEFAULT_LEADING_NOISE_TERMS = (
    "关于",
    "回答",
    "告诉我",
    "先帮我看下",
    "帮我看下",
    "看下",
    "请同时说明",
    "请说明",
    "说明",
    "请",
)
_MIXED_INTENT_SPLIT_RE = re.compile(
    r"(?:[，,。；;、：:]\s*)?"
    r"(?:另外|同时|以及|并且|还想|还要|一次知道|分别|顺便|请合并回答|请分别回答|合并回答|一并回答|一起回答|分别回答|分开回答|请合并|请分别)\s*"
    r"|[；;]"
)
_MIXED_INTENT_LIST_SPLIT_RE = re.compile(r"[、,，/]|以及|或者|或|和")
_MIXED_INTENT_SUBJECT_TRAILING_INSTRUCTION_RE = re.compile(
    r"(?:[，,、：:；;]\s*)?"
    r"(?:请|麻烦|帮我|帮忙)?"
    r"(?:合并回答|一并回答|一起回答|分别回答|分开回答|同时说明|说明一下|告诉我|给一下|列一下|回答)\s*$"
)
_QUOTED_ANCHOR_RE = re.compile(
    r'"([^"]{3,80})"'
    r"|“([^”]{3,80})”"
    r"|「([^」]{3,80})」"
    r"|『([^』]{3,80})』"
    r"|《([^》]{3,80})》"
    r"|'([^']{3,80})'"
)
_QUESTION_ANCHOR_SHORT_QUERY_MIN_CHARS = 4
_QUESTION_ANCHOR_SHORT_QUERY_MAX_CHARS = 24
_METADATA_ANCHOR_DB_FALLBACK_MIN_SCORE = 0.72
_METADATA_ANCHOR_DB_FALLBACK_DEFAULT_SCORE = 0.74
_METADATA_ANCHOR_DB_FALLBACK_MAX_QUERY_TERMS = 12
_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS = 8
_SERVICE_ANCHOR_ADMIN_MARKERS = ("在", "到")
_SERVICE_ANCHOR_QUERY_TRAILING_CHARS = " \t\r\n?？。！!，,、：:；;"
_METADATA_ANCHOR_DB_FALLBACK_ARRAY_FIELDS = (
    "retrieval_intents",
    "query_intents",
    "intent_terms",
    "aliases",
    "service_aliases",
    "keywords",
    "semantic_keys",
)
_METADATA_ANCHOR_DB_FALLBACK_SCALAR_FIELDS = (
    "question",
    "service_name",
    "primary_alias",
    "case_title",
    "source_topic",
    "title",
)
_METADATA_ANCHOR_DB_FALLBACK_TITLE_FIELDS = ("case_title", "source_topic", "title")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_DIFY_WARMUP_DEFAULT_QUERY = "warmup probe"
_DIFY_TRACE_QUERY_PREVIEW_MAX_CHARS = 160
_DIFY_TRACE_QUERY_PATH_MAX_CHARS = 120


def _resolve_internal_candidate_top_k(requested_top_k: int) -> int:
    return resolve_internal_candidate_top_k(
        requested_top_k,
        minimum=getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 20),
        multiplier=getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 4),
        maximum=getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50),
    )


def _resolve_mixed_intent_subquery_top_k(*, response_top_k: int, candidate_top_k: int) -> int:
    try:
        configured = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K", response_top_k) or response_top_k
        )
    except (TypeError, ValueError):
        configured = int(response_top_k or 1)
    return max(1, min(max(1, int(candidate_top_k or 1)), max(1, configured)))


class _DifyErrorRoute(APIRoute):
    def get_route_handler(self):  # noqa: ANN201
        original_route_handler = super().get_route_handler()

        async def _custom_route_handler(request: Request):  # noqa: ANN202
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                return _dify_error_response(exc)

        return _custom_route_handler


def _dify_error_response(exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "error_code" in detail and "error_msg" in detail:
        payload = {"error_code": int(detail["error_code"]), "error_msg": str(detail["error_msg"])}
    else:
        msg = str(detail or "")
        if exc.status_code == 401 and "authorization header" in msg.lower():
            code = 1001
        elif exc.status_code == 401:
            code = 1002
        elif exc.status_code == 404 and "knowledge" in msg.lower():
            code = 2001
        else:
            code = int(exc.status_code or 500)
        payload = {"error_code": code, "error_msg": msg or "Dify external knowledge request failed"}
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)


router = APIRouter(route_class=_DifyErrorRoute, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@dataclass(frozen=True)
class _DifyActor:
    tenant_id: UUID
    account_id: str


@dataclass(frozen=True)
class _DifyResponseCacheEntry:
    created_at_monotonic: float
    records: tuple[dict[str, Any], ...]


class _DifyResponseCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _DifyResponseCacheEntry]" = OrderedDict()

    def _purge_expired_locked(self, *, now: float, ttl_sec: int) -> None:
        if ttl_sec <= 0 or not self._entries:
            return
        expired = [
            key
            for key, entry in self._entries.items()
            if now - float(entry.created_at_monotonic) > float(ttl_sec)
        ]
        for key in expired:
            self._entries.pop(key, None)

    def get(self, key: str, *, ttl_sec: int) -> list[dict[str, Any]] | None:
        if not key or ttl_sec <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=ttl_sec)
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key, last=True)
            return [dict(record) for record in entry.records]

    def set(self, key: str, records: list[dict[str, Any]], *, ttl_sec: int, max_entries: int) -> None:
        if not key or ttl_sec <= 0 or max_entries <= 0:
            return
        snapshot = tuple(dict(record) for record in records or [])
        now = time.monotonic()
        with self._lock:
            self._purge_expired_locked(now=now, ttl_sec=ttl_sec)
            self._entries[key] = _DifyResponseCacheEntry(created_at_monotonic=now, records=snapshot)
            self._entries.move_to_end(key, last=True)
            while len(self._entries) > max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


_dify_response_cache = _DifyResponseCache()
_dify_external_warmup_state_lock = threading.Lock()
_dify_external_warmup_state: dict[str, Any] = {
    "enabled": False,
    "status": "idle",
    "attempted": 0,
    "completed": 0,
    "failed": 0,
    "elapsed_ms": None,
    "updated_at": None,
}


def _clear_dify_response_cache() -> None:
    _dify_response_cache.clear()


async def _acquire_or_wait_for_inflight_response(
    key: str,
) -> tuple[bool, dict[str, Any] | None]:
    while True:
        leader, future = await acquire_inflight_response(key)
        if leader:
            return True, None
        try:
            return False, await asyncio.shield(future)
        except InflightResponseLeaderCancelledError:
            continue


def _set_dify_external_warmup_status(**updates: Any) -> None:
    with _dify_external_warmup_state_lock:
        _dify_external_warmup_state.update(updates)
        _dify_external_warmup_state["updated_at"] = datetime.now(UTC).isoformat()


def get_dify_external_knowledge_warmup_status() -> dict[str, Any]:
    with _dify_external_warmup_state_lock:
        return dict(_dify_external_warmup_state)


def dify_external_knowledge_warmup_ready() -> bool:
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        return True
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED", True)):
        return True
    return str(get_dify_external_knowledge_warmup_status().get("status") or "idle") == "completed"


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
    query: str = Field(min_length=1)
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
    raise HTTPException(status_code=400, detail=f"Unsupported Dify retrieval latency_profile: {setting.latency_profile}")


class DifyConversationTurnRequest(BaseModel):
    query: str = Field(min_length=1)
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
    citation = {
        key: metadata.get(key)
        for key in _DIFY_TRACE_CITATION_METADATA_KEYS
        if metadata.get(key) is not None
    }
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
        if any(metadata.get(key) is not None for key in ("reranker_provider", "rerank_score", "rerank_elapsed_sec", "rerank_model_used")):
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
    log_metrics(
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
    log_metrics(
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
    safe = {
        key: citation.get(key)
        for key in _DIFY_TRACE_CITATION_METADATA_KEYS
        if citation.get(key) is not None
    }
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
    source_conversation_id: str,
) -> UUID | None:
    row = (
        db.query(Message.conversation_id)
        .filter(
            Message.tenant_id == tenant_id,
            _external_conversation_metadata_text("source") == "dify",
            _external_conversation_metadata_text("source_conversation_id") == source_conversation_id,
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )
    if not row:
        return None
    return row[0]


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
    return (title[:80] if title else "Dify external retrieval")


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
    source_conversation_id = str(source_conversation_id or "").strip()
    if not source_conversation_id:
        return None

    try:
        _lock_dify_conversation_turn_scope(
            db=db,
            tenant_id=tenant_id,
            conversation_scope=source_conversation_id,
        )
        existing_id = _find_dify_trace_conversation(
            db,
            tenant_id=tenant_id,
            source_conversation_id=source_conversation_id,
        )
        if existing_id is not None:
            return existing_id

        if not settings.DIFY_EXTERNAL_KNOWLEDGE_TRACE_AUTO_CREATE_CONVERSATION_ENABLED:
            return None

        now = datetime.now(UTC)
        conversation = Conversation(
            tenant_id=tenant_id,
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
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
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
        _lock_dify_conversation_turn_scope(
            db=db,
            tenant_id=tenant_id,
            conversation_scope=conversation_scope,
        )
        conversation = _load_dify_trace_conversation(db, tenant_id=tenant_id, conversation_id=conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        if not source_conversation_id:
            raise HTTPException(status_code=400, detail="dify_conversation_id is required")
        resolved_id = _ensure_dify_trace_conversation(
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
        conversation = _load_dify_trace_conversation(db, tenant_id=tenant_id, conversation_id=resolved_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    persisted_turn = _find_persisted_dify_conversation_turn(
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
    user_metadata = _dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="user",
        extra=metadata,
    )
    assistant_metadata = _dify_external_conversation_metadata(
        account_id=account_id,
        source_conversation_id=source_conversation_id,
        source_message_id=source_message_id,
        source_run_id=source_run_id,
        trace_request_id=trace_request_id,
        role="assistant",
        extra=metadata,
    )

    reusable_user = _find_reusable_dify_seed_message(
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
        citations=_dify_turn_citations_for_storage(citations),
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
        db.query(Message)
        .filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation.id)
        .count()
    )
    db.commit()
    _log_dify_result_rag_trace(
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
    body_conversation_id = _uuid_or_none(body.conversation_id)
    if body_conversation_id is not None:
        return body_conversation_id
    for header_name in ("x-mimirq-conversation-id", "x-conversation-id"):
        raw = str(request.headers.get(header_name) or "").strip()
        if not raw:
            continue
        header_conversation_id = _uuid_or_none(raw)
        if header_conversation_id is not None:
            return header_conversation_id
        else:
            logger.debug("Ignoring invalid Dify trace conversation header %s", header_name)
    if db is None or tenant_id is None or account_id is None:
        return None

    source_conversation_id = _dify_trace_source_conversation_id(request, body)
    if not source_conversation_id:
        return None
    return _ensure_dify_trace_conversation(
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
    return [p for p in _TOKEN_SPLIT_RE.split(str(raw or "").strip()) if p]


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
        raw_tenant = str(
            request.headers.get(str(getattr(settings, "TENANT_HEADER", "X-Tenant-ID") or "X-Tenant-ID"))
            or getattr(settings, "DEFAULT_TENANT_ID", "")
        ).strip()
    tenant_id = _coerce_uuid(raw_tenant, label="Dify tenant id")
    account_id = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "") or "system:dify").strip()
    if not account_id:
        raise HTTPException(status_code=503, detail="Dify external knowledge account is not configured")
    return _DifyActor(tenant_id=tenant_id, account_id=account_id)


def _dedupe_dataset_ids(dataset_ids: list[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    out: list[UUID] = []
    for dataset_id in dataset_ids:
        if dataset_id in seen:
            continue
        seen.add(dataset_id)
        out.append(dataset_id)
    return out


def _cache_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    text = str(value or "").strip()
    return text or None


def _resolve_dify_response_cache_corpus_token(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
) -> str | None:
    scoped_dataset_ids = _dedupe_dataset_ids(list(dataset_ids or []))
    if not scoped_dataset_ids:
        return None
    try:
        rows = (
            db.query(Dataset.id, Dataset.updated_at)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(scoped_dataset_ids))
            .all()
        )
    except Exception:
        return None
    if not rows or len(rows) != len(scoped_dataset_ids):
        return None
    items = [
        {
            "dataset_id": str(dataset_id),
            "updated_at": _cache_timestamp(updated_at),
        }
        for dataset_id, updated_at in rows
    ]
    items.sort(key=lambda item: item["dataset_id"])
    raw = json.dumps(
        {
            "schema": "mimirq.dify_external_response_corpus.v1",
            "datasets": items,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:32]


def _dify_response_cache_settings_signature() -> dict[str, Any]:
    return {
        "internal_top_k_min": int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 20) or 20),
        "internal_top_k_multiplier": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 4) or 4
        ),
        "internal_top_k_max": int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50) or 50),
        "primary_scope_enabled": bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True)),
        "primary_min_records": int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS", 1) or 1),
        "primary_min_top_score": float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE", 0.45) or 0.0),
        "compact_enabled": bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED", True)),
        "compact_min_top_score": float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE", 0.7) or 0.0),
        "compact_relative_score_floor": float(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR", 0.65) or 0.0
        ),
        "compact_min_records": int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS", 1) or 1),
        "fast_candidate_top_k_max": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX", 3) or 3
        ),
        "fast_response_top_k_max": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX", 2) or 2
        ),
        "fast_content_max_chars": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 1400) or 1400
        ),
        "fast_total_content_max_chars": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 2200) or 2200
        ),
        "enable_reranker": bool(getattr(settings, "ENABLE_RERANKER", False)),
        "dify_reranker_enabled": bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True)),
        "reranker_provider": str(getattr(settings, "RERANKER_PROVIDER", "") or ""),
        "reranker_model": str(getattr(settings, "RERANKER_MODEL", "") or ""),
        "reranker_top_n": int(getattr(settings, "RERANKER_TOP_N", 20) or 20),
        "metadata_anchor_enabled": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", False)
        ),
        "metadata_anchor_preflight_enabled": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", False)
        ),
        "metadata_anchor_max_scan": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN", 80) or 80
        ),
        "metadata_anchor_total_budget_ms": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS", 1500) or 0
        ),
        "metadata_anchor_text_scan_enabled": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED", False)
        ),
        "metadata_anchor_extend_sibling_policy_scope_enabled": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED", False)
        ),
        "metadata_anchor_extended_scope_max_datasets": int(
            settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS
        ),
        "mixed_intent_supplement_enabled": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED", True)
        ),
        "mixed_intent_max_subqueries": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES", 4) or 4
        ),
        "mixed_intent_subquery_top_k": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K", 0) or 0
        ),
        "kg_on_demand_enabled": bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED", True)),
        "kg_query_expansion_default": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", False)
        ),
        "kg_chunk_injection_default": bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", False)
        ),
        "kg_chunk_injection_max_chunks_default": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3) or 3
        ),
        "kg_chunk_boost_default": bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)),
        "kg_chunk_boost_weight_default": float(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25) or 0.0
        ),
        "kg_chunk_boost_max_promoted_default": int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2) or 2
        ),
    }


def _build_dify_response_cache_key(
    *,
    actor: _DifyActor,
    knowledge_id: str,
    query: str,
    retrieval_setting: DifyRetrievalSetting,
    metadata_condition: dict[str, Any] | None,
    scope_plan: DatasetScopePlan,
    top_k: int,
    candidate_top_k: int,
    score_threshold: float,
    policy_plugin_refs: tuple[str, ...],
    corpus_token: str,
) -> str:
    signature = {
        "schema": "mimirq.dify_external_response_cache.v1",
        "tenant_id": str(actor.tenant_id),
        "account_id": str(actor.account_id or ""),
        "knowledge_id": str(knowledge_id or "").strip(),
        "query": str(query or "").strip(),
        "retrieval_setting": retrieval_setting.model_dump(mode="json"),
        "metadata_condition": metadata_condition or None,
        "dataset_ids": [str(item) for item in scope_plan.dataset_ids],
        "primary_dataset_ids": [str(item) for item in scope_plan.primary_dataset_ids],
        "expansion_dataset_ids": [str(item) for item in scope_plan.expansion_dataset_ids],
        "strict_scope": bool(scope_plan.strict_scope),
        "matched_terms": list(scope_plan.matched_terms),
        "top_k": int(top_k),
        "candidate_top_k": int(candidate_top_k),
        "score_threshold": float(score_threshold),
        "policy_plugin_refs": list(policy_plugin_refs),
        "corpus_token": str(corpus_token or ""),
        "settings": _dify_response_cache_settings_signature(),
    }
    raw = json.dumps(signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()
    return f"difyext:{actor.tenant_id}:{digest[:32]}"


def _coerce_dataset_id_list(value: Any) -> list[UUID]:
    if isinstance(value, dict):
        for key in ("dataset_ids", "datasets", "dataset_id"):
            if key in value:
                return _coerce_dataset_id_list(value[key])
        raise HTTPException(status_code=400, detail="Dify knowledge mapping must include dataset_id or dataset_ids")
    if isinstance(value, str):
        return [_coerce_uuid(value, label="dataset id")]
    if isinstance(value, list | tuple | set):
        dataset_ids: list[UUID] = []
        for item in value:
            if isinstance(item, dict):
                dataset_ids.extend(_coerce_dataset_id_list(item))
            else:
                dataset_ids.append(_coerce_uuid(item, label="dataset id"))
        return _dedupe_dataset_ids(dataset_ids)
    raise HTTPException(status_code=400, detail="Dify knowledge mapping must be a dataset id or list")


def _route_hint_terms(raw_route: dict[str, Any]) -> tuple[str, ...]:
    raw_terms = raw_route.get("terms") or raw_route.get("query_terms") or raw_route.get("contains")
    terms = raw_terms if isinstance(raw_terms, list | tuple | set) else [raw_terms]
    return tuple(str(term or "").strip() for term in terms if str(term or "").strip())


def _mapping_query_routes(mapping: dict[str, Any]) -> list[Any] | None:
    routes = mapping.get("query_routes") or mapping.get("query_dataset_routes") or mapping.get("routes")
    return routes if isinstance(routes, list) else None


def _route_hints_from_routes(routes: list[Any]) -> list[DatasetRouteHint]:
    route_hints: list[DatasetRouteHint] = []
    for raw_route in routes:
        if not isinstance(raw_route, dict):
            continue
        routed_dataset_ids = _coerce_dataset_id_list(raw_route)
        if not routed_dataset_ids:
            continue
        route_hints.append(
            DatasetRouteHint(
                terms=_route_hint_terms(raw_route),
                dataset_ids=tuple(routed_dataset_ids),
                mode=normalize_route_mode(raw_route.get("mode") or raw_route.get("merge") or "prepend"),
            )
        )
    return route_hints


def _merge_route_hints(*groups: list[DatasetRouteHint]) -> list[DatasetRouteHint]:
    merged: list[DatasetRouteHint] = []
    seen: set[tuple[tuple[str, ...], tuple[UUID, ...], str]] = set()
    for group in groups:
        for route_hint in group:
            identity = (route_hint.terms, route_hint.dataset_ids, route_hint.mode)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(route_hint)
    return merged


def _inherited_query_route_hints(
    *,
    knowledge_map: dict[str, Any],
    current_key: str,
    base_dataset_ids: list[UUID],
) -> list[DatasetRouteHint]:
    base_set = set(base_dataset_ids)
    if not base_set:
        return []

    current_mapping = knowledge_map.get(current_key)
    raw_inherited_sources = (
        current_mapping.get("inherit_query_routes_from")
        if isinstance(current_mapping, dict)
        else None
    )
    raw_sources = (
        sorted(raw_inherited_sources, key=str)
        if isinstance(raw_inherited_sources, set)
        else raw_inherited_sources
        if isinstance(raw_inherited_sources, list | tuple)
        else [raw_inherited_sources]
    )
    inherited_sources: list[str] = []
    seen_sources: set[str] = set()
    for source in raw_sources:
        source_key = str(source or "").strip()
        if not source_key or source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        inherited_sources.append(source_key)
    if not inherited_sources:
        return []
    inherited: list[DatasetRouteHint] = []
    seen: set[tuple[tuple[str, ...], tuple[UUID, ...], str]] = set()
    for mapping_key in inherited_sources:
        raw_mapping = knowledge_map.get(mapping_key)
        if not isinstance(raw_mapping, dict):
            continue
        routes = _mapping_query_routes(raw_mapping)
        if not routes:
            continue
        for route_hint in _route_hints_from_routes(routes):
            if not route_hint.dataset_ids:
                continue
            identity = (route_hint.terms, route_hint.dataset_ids, route_hint.mode)
            if identity in seen:
                continue
            seen.add(identity)
            inherited.append(route_hint)
    return inherited


def _apply_query_dataset_routes(base_dataset_ids: list[UUID], mapping: dict[str, Any], *, query: str) -> list[UUID]:
    return list(_plan_query_dataset_scope(base_dataset_ids, mapping, query=query).dataset_ids)


def _knowledge_mapping_plugin_refs(mapping: Any) -> tuple[str, ...]:
    if not isinstance(mapping, dict):
        return ()
    raw_refs = mapping.get("plugin_refs") or mapping.get("pipeline_plugin_refs") or mapping.get("plugin_ref")
    refs = raw_refs if isinstance(raw_refs, list | tuple | set) else [raw_refs]
    out: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        ref = str(raw or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        out.append(ref)
    return tuple(out)


def _retrieval_policy_filter_fields_for_plugin_refs(plugin_refs: tuple[str, ...]) -> set[str] | None:
    if not plugin_refs:
        return None
    out: set[str] = set()
    for plugin_ref in plugin_refs:
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        raw_fields = policy.get("filter_fields") if isinstance(policy, dict) else None
        if not isinstance(raw_fields, list | tuple | set):
            continue
        for raw in raw_fields:
            field_name = str(raw or "").strip()
            if field_name:
                out.add(field_name)
    return out


def _retrieval_policy_fallback_multiplier_for_plugin_refs(plugin_refs: tuple[str, ...]) -> int:
    multiplier = 1
    for plugin_ref in plugin_refs:
        multiplier = max(
            multiplier,
            retrieval_policy_fallback_multiplier(_retrieval_policy_for_plugin_ref(plugin_ref)),
        )
    return multiplier


def _resolve_knowledge_policy_filter_fields(knowledge_id: str) -> set[str] | None:
    key = str(knowledge_id or "").strip()
    raw_mapping = _load_knowledge_map().get(key)
    return _retrieval_policy_filter_fields_for_plugin_refs(_knowledge_mapping_plugin_refs(raw_mapping))


def _resolve_knowledge_policy_fallback_multiplier(knowledge_id: str) -> int:
    key = str(knowledge_id or "").strip()
    raw_mapping = _load_knowledge_map().get(key)
    return _retrieval_policy_fallback_multiplier_for_plugin_refs(_knowledge_mapping_plugin_refs(raw_mapping))


def _resolve_knowledge_policy_plugin_refs(knowledge_id: str) -> tuple[str, ...]:
    key = str(knowledge_id or "").strip()
    raw_mapping = _load_knowledge_map().get(key)
    return _knowledge_mapping_plugin_refs(raw_mapping)


def _apply_policy_fallback_candidate_multiplier(candidate_top_k: int, *, multiplier: int) -> int:
    safe_candidate_top_k = max(1, int(candidate_top_k or 1))
    safe_multiplier = max(1, int(multiplier or 1))
    try:
        configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50) or 50)
    except (TypeError, ValueError):
        configured_max = 50
    max_candidates = max(safe_candidate_top_k, configured_max)
    return min(max_candidates, safe_candidate_top_k * safe_multiplier)


def _metadata_anchor_dataset_ids_for_query(
    *,
    knowledge_id: str,
    base_dataset_ids: list[UUID] | tuple[UUID, ...],
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[UUID]:
    dataset_ids = _dedupe_dataset_ids(list(base_dataset_ids or []))
    if not dataset_ids:
        return []
    if not bool(
        getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTEND_SIBLING_POLICY_SCOPE_ENABLED", False)
    ):
        return dataset_ids
    if not _query_has_specific_service_anchor_candidate(query, policy_plugin_refs=policy_plugin_refs):
        return dataset_ids

    requested_refs = {str(ref or "").strip() for ref in policy_plugin_refs or () if str(ref or "").strip()}
    if not requested_refs:
        return dataset_ids

    knowledge_map = _load_knowledge_map()
    current_mapping = knowledge_map.get(str(knowledge_id or "").strip())
    if not isinstance(current_mapping, dict):
        return dataset_ids
    try:
        current_base_ids = _dedupe_dataset_ids(_coerce_dataset_id_list(current_mapping))
    except HTTPException:
        return dataset_ids
    if set(dataset_ids) != set(current_base_ids):
        return dataset_ids
    current_base_set = set(current_base_ids)
    current_route_hints = _route_hints_from_routes(_mapping_query_routes(current_mapping) or [])
    has_external_route_hint = any(
        any(route_dataset_id not in current_base_set for route_dataset_id in route_hint.dataset_ids)
        for route_hint in current_route_hints
    )
    if not has_external_route_hint:
        return dataset_ids

    expanded: list[UUID] = list(dataset_ids)
    for raw_mapping in knowledge_map.values():
        if not isinstance(raw_mapping, dict):
            continue
        mapping_refs = set(_knowledge_mapping_plugin_refs(raw_mapping))
        if not mapping_refs or requested_refs.isdisjoint(mapping_refs):
            continue
        try:
            expanded.extend(_coerce_dataset_id_list(raw_mapping))
        except HTTPException:
            continue
        for route_hint in _route_hints_from_routes(_mapping_query_routes(raw_mapping) or []):
            expanded.extend(route_hint.dataset_ids)

    max_datasets = max(
        len(dataset_ids),
        min(
            200,
            int(settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_EXTENDED_SCOPE_MAX_DATASETS),
        ),
    )
    return list(_dedupe_dataset_ids(expanded)[:max_datasets])


def _plan_query_dataset_scope(
    base_dataset_ids: list[UUID],
    mapping: dict[str, Any],
    *,
    query: str,
    inherited_route_hints: list[DatasetRouteHint] | None = None,
) -> DatasetScopePlan:
    routes = _mapping_query_routes(mapping)
    if not routes and not inherited_route_hints:
        return plan_dataset_scope(base_dataset_ids=base_dataset_ids, query=query)

    route_hints = _merge_route_hints(
        list(inherited_route_hints or []),
        _route_hints_from_routes(routes or []),
    )
    strict_routes = bool(
        route_hints and (mapping.get("strict_query_routes") or mapping.get("query_routes_strict"))
    )
    return plan_dataset_scope(
        base_dataset_ids=base_dataset_ids,
        route_hints=route_hints,
        query=query,
        strict_routes=strict_routes,
        include_unmatched_hint_datasets=bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INCLUDE_UNMATCHED_ROUTE_HINTS", False)
        ),
        matched_replace_routes_as_primary_scope=strict_routes,
    )


def _load_knowledge_map() -> dict[str, Any]:
    raw = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Dify knowledge map JSON is invalid") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=503, detail="Dify knowledge map JSON must be an object")
    return data


def _resolve_dify_warmup_knowledge_ids(knowledge_map: dict[str, Any] | None = None) -> tuple[str, ...]:
    raw_ids = _split_items(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_KNOWLEDGE_IDS", ""))
    candidates = raw_ids if raw_ids else [str(key).strip() for key in (knowledge_map or _load_knowledge_map()).keys()]
    try:
        max_ids = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS", 8) or 0)
    except (TypeError, ValueError):
        max_ids = 8
    if max_ids <= 0:
        return ()

    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        knowledge_id = str(item or "").strip()
        if not knowledge_id or knowledge_id in seen:
            continue
        seen.add(knowledge_id)
        out.append(knowledge_id)
        if len(out) >= max_ids:
            break
    return tuple(out)


def _resolve_knowledge_dataset_ids(knowledge_id: str, *, query: str = "") -> list[UUID]:
    return list(_resolve_knowledge_dataset_scope(knowledge_id, query=query).dataset_ids)


def _resolve_knowledge_dataset_scope(knowledge_id: str, *, query: str = "") -> DatasetScopePlan:
    key = str(knowledge_id or "").strip()
    knowledge_map = _load_knowledge_map()
    if key in knowledge_map:
        raw_mapping = knowledge_map[key]
        dataset_ids = _coerce_dataset_id_list(raw_mapping)
        if isinstance(raw_mapping, dict):
            inherited_route_hints = _inherited_query_route_hints(
                knowledge_map=knowledge_map,
                current_key=key,
                base_dataset_ids=dataset_ids,
            )
            plan = _plan_query_dataset_scope(
                dataset_ids,
                raw_mapping,
                query=query,
                inherited_route_hints=inherited_route_hints,
            )
        else:
            plan = plan_dataset_scope(base_dataset_ids=dataset_ids, query=query)
        if not plan.dataset_ids:
            raise HTTPException(status_code=404, detail="Dify knowledge mapping is empty")
        return plan

    try:
        return plan_dataset_scope(base_dataset_ids=[UUID(key)], query=query)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Dify knowledge mapping not found") from exc


def _metadata_condition_to_filter(
    condition: dict[str, Any] | None,
    *,
    allowed_fields: set[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(condition, dict) or not condition:
        return None
    for key in ("metadata_filter", "filter"):
        value = condition.get(key)
        if isinstance(value, dict) and value:
            _validate_metadata_filter_fields(value, allowed_fields=allowed_fields)
            return value

    raw_conditions = condition.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        return None

    logical_operator = str(condition.get("logical_operator") or "and").strip().lower()
    if logical_operator not in {"and", "or"}:
        raise HTTPException(status_code=400, detail="Invalid Dify metadata_condition logical_operator")

    parts: list[dict[str, Any]] = []
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, dict):
            raise HTTPException(status_code=400, detail="Invalid Dify metadata_condition condition")
        parts.append(_dify_metadata_condition_item_to_filter(raw_condition))

    if not parts:
        return None
    metadata_filter = parts[0] if len(parts) == 1 else {"$or" if logical_operator == "or" else "$and": parts}
    _validate_metadata_filter_fields(metadata_filter, allowed_fields=allowed_fields)
    return metadata_filter


def _metadata_filter_field_names(metadata_filter: Any) -> set[str]:
    if not isinstance(metadata_filter, dict):
        return set()
    out: set[str] = set()
    for key, value in metadata_filter.items():
        name = str(key or "").strip()
        if not name:
            continue
        if name in {"$and", "$or"}:
            values = value if isinstance(value, list | tuple | set) else [value]
            for item in values:
                out.update(_metadata_filter_field_names(item))
            continue
        if name == "$not":
            out.update(_metadata_filter_field_names(value))
            continue
        if name.startswith("$"):
            continue
        out.add(name)
    return out


def _validate_metadata_filter_fields(metadata_filter: dict[str, Any], *, allowed_fields: set[str] | None) -> None:
    if allowed_fields is None:
        return
    disallowed = sorted(field_name for field_name in _metadata_filter_field_names(metadata_filter) if field_name not in allowed_fields)
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"Dify metadata filter field is not allowed by plugin retrieval_policy: {disallowed[0]}",
        )


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _dify_metadata_condition_item_to_filter(condition: dict[str, Any]) -> dict[str, Any]:
    name = str(condition.get("name") or "").strip()
    op = str(condition.get("comparison_operator") or "").strip().lower()
    value = condition.get("value")
    if not name or not op:
        raise HTTPException(status_code=400, detail="Invalid Dify metadata_condition condition")

    if op == "contains":
        return {name: {"$contains": value}}
    if op == "not contains":
        return {"$not": {name: {"$contains": value}}}
    if op == "start with":
        return {name: {"$startswith": value}}
    if op == "end with":
        return {name: {"$endswith": value}}
    if op in {"is", "="}:
        return {name: {"$eq": value}}
    if op in {"is not", "≠", "!="}:
        return {name: {"$ne": value}}
    if op == "in":
        return {name: {"$in": _as_list(value)}}
    if op == "not in":
        return {name: {"$nin": _as_list(value)}}
    if op == "empty":
        return {"$or": [{name: {"$exists": False}}, {name: {"$eq": ""}}, {name: {"$eq": []}}]}
    if op == "not empty":
        return {
            "$and": [
                {name: {"$exists": True}},
                {"$not": {name: {"$eq": ""}}},
                {"$not": {name: {"$eq": []}}},
            ]
        }
    if op in {">", "after"}:
        return {name: {"$gt": value}}
    if op == "<" or op == "before":
        return {name: {"$lt": value}}
    if op in {"≥", ">="}:
        return {name: {"$gte": value}}
    if op in {"≤", "<="}:
        return {name: {"$lte": value}}

    raise HTTPException(status_code=400, detail=f"Unsupported Dify metadata comparison operator: {op}")


def _first_non_empty(citation: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = citation.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _clamp_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def _citation_score(citation: dict[str, Any]) -> float:
    for key in _SCORE_KEYS:
        if citation.get(key) is not None:
            return _clamp_score(citation.get(key))
    metadata = citation.get("metadata")
    if isinstance(metadata, dict):
        for key in _METADATA_SCORE_KEYS:
            if metadata.get(key) is not None:
                return _clamp_score(metadata.get(key))
    return 0.0


def _citation_dataset_id(citation: dict[str, Any], *, fallback_dataset_id: UUID | None) -> UUID | None:
    raw_metadata = citation.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    for value in (citation.get("dataset_id"), metadata.get("dataset_id"), fallback_dataset_id):
        if value is None:
            continue
        try:
            return UUID(str(value))
        except ValueError:
            continue
    return None


def _citation_chunk_id(citation: dict[str, Any]) -> str:
    raw_metadata = citation.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    for value in (citation.get("chunk_id"), metadata.get("chunk_id")):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _load_chunk_content_map(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    chunk_ids: list[UUID] = []
    seen: set[UUID] = set()
    for citation in citations or []:
        chunk_id = _citation_chunk_id(citation)
        if not chunk_id:
            continue
        try:
            parsed = UUID(chunk_id)
        except ValueError:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        chunk_ids.append(parsed)
    if not chunk_ids:
        return {}

    try:
        rows = (
            db.query(DocumentChunk.id, DocumentChunk.content)
            .filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.disabled_at.is_(None),
            )
            .all()
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to hydrate Dify chunk content; falling back to citation snippets", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for chunk_id, content in rows:
        text = str(content or "").strip()
        if text:
            out[str(chunk_id)] = text
    return out


def _load_chunk_content_map_with_managed_session(
    *,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    worker_db = SessionLocal()
    try:
        return _load_chunk_content_map(
            db=worker_db,
            tenant_id=tenant_id,
            citations=citations,
        )
    finally:
        worker_db.close()


async def _offload_chunk_content_hydration(
    *,
    request_db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
) -> dict[str, str]:
    rollback = getattr(request_db, "rollback", None)
    if callable(rollback):
        rollback()
    return await run_blocking_retrieval_call(
        _load_chunk_content_map_with_managed_session,
        tenant_id=tenant_id,
        citations=citations,
    )


def _iter_record_metadata_layers(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_metadata = record.get("metadata")
    if not isinstance(raw_metadata, dict):
        return []
    layers = [raw_metadata]
    for key in _RETRIEVAL_METADATA_VIEW_KEYS:
        nested = raw_metadata.get(key)
        if isinstance(nested, dict) and nested:
            layers.append(nested)
    return layers


def _metadata_terms(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list | tuple | set) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _response_hint_metadata_conditions_match(layer: dict[str, Any], field_spec: dict[str, Any]) -> bool:
    conditions = field_spec.get("when_metadata")
    if conditions is None:
        conditions = field_spec.get("metadata_when")
    if not isinstance(conditions, dict) or not conditions:
        return True
    for key, expected in conditions.items():
        name = str(key or "").strip()
        if not name:
            return False
        expected_terms = {_normalize_match_term(term) for term in _metadata_terms(expected)}
        if not expected_terms:
            return False
        actual_terms = {_normalize_match_term(term) for term in _metadata_terms(layer.get(name))}
        if not actual_terms or actual_terms.isdisjoint(expected_terms):
            return False
    return True


def _request_client_ip(request: Request) -> str:
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        first = forwarded_for.split(",", 1)[0].strip()
        if first:
            return first
    return str(getattr(getattr(request, "client", None), "host", "") or "").strip()


def _diagnostic_value_hash(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


def _diagnostic_query_hash(query: str) -> str:
    return _diagnostic_value_hash(query)


def _is_cjk_char(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _contains_cjk(value: str) -> bool:
    return any(_is_cjk_char(char) for char in str(value or ""))


def _is_anchor_word_char(char: str) -> bool:
    return (char.isascii() and char.isalnum()) or _is_cjk_char(char)


def _iter_anchor_word_segments(value: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    for char in str(value or ""):
        if _is_anchor_word_char(char):
            current.append(char)
            continue
        if current:
            segments.append("".join(current))
            current = []
    if current:
        segments.append("".join(current))
    return segments


def _strip_trailing_service_anchor_admin(value: str, *, admin_aliases: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    for marker in _SERVICE_ANCHOR_ADMIN_MARKERS:
        for alias in admin_aliases:
            suffix = f"{marker}{alias}"
            if text.endswith(suffix):
                return text[: -len(suffix)].strip()
    return text


def _rstrip_service_anchor_query_noise(value: str) -> str:
    return str(value or "").rstrip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS).strip()


def _clamp_hint_value(value: str, *, limit: int = _MAX_HINT_VALUE_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _field_line_parts(line: str) -> tuple[str, str] | None:
    text = str(line or "").strip()
    if not text:
        return None
    colon_positions = [index for index in (text.find("："), text.find(":")) if index >= 0]
    if not colon_positions:
        return None
    split_at = min(colon_positions)
    label = text[:split_at].strip()
    value = text[split_at + 1 :].strip()
    if not label or not value or len(label) > 20:
        return None
    return label, value


def _response_hint_string_list(response_hints: dict[str, Any], key: str, *, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = response_hints.get(key) if isinstance(response_hints, dict) else None
    if raw is None:
        return default
    if not isinstance(raw, list | tuple | set):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def _response_hint_text(response_hints: dict[str, Any], key: str, *, default: str) -> str:
    value = response_hints.get(key) if isinstance(response_hints, dict) else None
    text = str(value or "").strip()
    return text or default


def _response_hint_dict(response_hints: dict[str, Any], key: str) -> dict[str, Any]:
    raw = response_hints.get(key) if isinstance(response_hints, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def _response_hint_dict_list(response_hints: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    raw = response_hints.get(key) if isinstance(response_hints, dict) else None
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(dict(item) for item in raw if isinstance(item, dict))


def _response_hint_groups(response_hints: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_groups = response_hints.get("groups") if isinstance(response_hints, dict) else None
    if not isinstance(raw_groups, list):
        return ()
    return tuple(dict(group) for group in raw_groups if isinstance(group, dict))


def _response_hints_for_record(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    if not plugin_ref:
        return {}
    policy = _retrieval_policy_for_plugin_ref(plugin_ref)
    raw = policy.get("response_hints") if isinstance(policy, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def _response_hints_for_metadata(
    metadata: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    return _response_hints_for_record({"metadata": metadata}, policy_plugin_refs=policy_plugin_refs)


def _structured_fields_from_content(content: str, *, response_hints: dict[str, Any]) -> dict[str, str]:
    labels = set(_response_hint_string_list(response_hints, "structured_labels"))
    if not labels:
        return {}
    fields: dict[str, str] = {}
    for line in str(content or "").splitlines():
        parts = _field_line_parts(line)
        if parts is None:
            continue
        label, value = parts
        if label not in labels or label in fields:
            continue
        answer_labels = set(_response_hint_string_list(response_hints, "answer_labels"))
        limit = _MAX_QA_HINT_VALUE_CHARS if label in answer_labels else _MAX_HINT_VALUE_CHARS
        fields[label] = _clamp_hint_value(value, limit=limit)
    return fields


def _metadata_answer_highlights(
    metadata: dict[str, Any],
    *,
    response_hints: dict[str, Any],
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        value = str(text or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        highlights.append(value)

    highlight_keys = _response_hint_string_list(response_hints, "answer_highlight_metadata")
    field_specs = _response_hint_dict_list(response_hints, "answer_highlight_metadata_fields")
    answer_field_configured = "answer" in highlight_keys or any(
        str(spec.get("metadata") or spec.get("key") or spec.get("field") or "").strip() == "answer"
        for spec in field_specs
    )
    for layer in [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]:
        if not isinstance(layer, dict):
            continue
        if not answer_field_configured:
            for value in _metadata_terms(layer.get("answer")):
                add(f"答案：{_clamp_hint_value(value, limit=1600)}")
        for key in highlight_keys:
            for value in _metadata_terms(layer.get(key)):
                text = _clamp_hint_value(value)
                add(text)
        for field_spec in field_specs:
            if not _response_hint_metadata_conditions_match(layer, field_spec):
                continue
            metadata_key = str(field_spec.get("metadata") or field_spec.get("key") or "").strip()
            source = layer.get(metadata_key) if metadata_key else layer
            if source is None:
                continue
            max_chars = max(1, min(3000, int(field_spec.get("max_chars") or _MAX_HINT_VALUE_CHARS)))
            labels = field_spec.get("labels") if isinstance(field_spec.get("labels"), dict) else {}
            fields = _response_hint_string_list(field_spec, "fields")
            single_field = str(field_spec.get("field") or "").strip()
            if single_field and single_field not in fields:
                fields = (*fields, single_field)
            if isinstance(source, dict):
                ordered_fields = _prioritized_response_hint_metadata_fields(
                    fields,
                    query=query,
                    policy_plugin_refs=policy_plugin_refs,
                    enabled=field_spec.get("prioritize_query_fields") is True,
                )
                requested_labels = _requested_response_hint_metadata_labels(
                    ordered_fields,
                    query=query,
                    policy_plugin_refs=policy_plugin_refs,
                    enabled=field_spec.get("prioritize_query_fields") is True,
                )
                requested_prefix = str(field_spec.get("requested_labels_prefix") or "").strip()
                if requested_prefix and requested_labels:
                    separator = str(field_spec.get("requested_labels_separator") or "、")
                    add(f"{requested_prefix}：{separator.join(requested_labels)}")
                for field in ordered_fields:
                    label = str(labels.get(field) or field).strip()
                    if not label:
                        continue
                    for value in _metadata_terms(source.get(field)):
                        add(f"{label}：{_clamp_hint_value(value, limit=max_chars)}")
                continue

            label = str(field_spec.get("label") or metadata_key).strip()
            if not label:
                continue
            for value in _metadata_terms(source):
                add(f"{label}：{_clamp_hint_value(value, limit=max_chars)}")
    return highlights


def _normalize_match_term(value: Any) -> str:
    text = str(value or "").strip().casefold()
    out: list[str] = []
    for char in text:
        if char.isspace():
            continue
        if re.match(r"[\W_]", char, flags=re.UNICODE):
            continue
        out.append(char)
    return "".join(out)


def _longest_common_substring_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0] * (len(right) + 1)
        for index, right_char in enumerate(right, start=1):
            if left_char != right_char:
                continue
            current[index] = previous[index - 1] + 1
            best = max(best, current[index])
        previous = current
    return best


def _near_question_anchor_match(query_term: str, candidate: str) -> bool:
    if (
        len(query_term) < _QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS
        or len(candidate) < _QUESTION_ANCHOR_NEAR_MATCH_MIN_CHARS
    ):
        return False
    ratio = SequenceMatcher(a=query_term, b=candidate, autojunk=False).ratio()
    return ratio >= _QUESTION_ANCHOR_NEAR_MATCH_MIN_RATIO


def _cjk_bigrams(value: str) -> set[str]:
    text = "".join(char for char in str(value or "") if _CJK_RE.match(char))
    if len(text) < 2:
        return set()
    return {text[index : index + 2] for index in range(0, len(text) - 1)}


def _cjk_bigram_overlap_count(left: str, right: str) -> int:
    return len(_cjk_bigrams(left) & _cjk_bigrams(right))


def _cjk_bigram_overlap_ratio(left: str, right: str) -> float:
    left_bigrams = _cjk_bigrams(left)
    right_bigrams = _cjk_bigrams(right)
    if not left_bigrams or not right_bigrams:
        return 0.0
    return len(left_bigrams & right_bigrams) / max(1, min(len(left_bigrams), len(right_bigrams)))


def _question_anchor_intent_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in _response_hint_string_list(policy, "question_intent_terms"):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _query_prefers_question_anchor(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _QUESTION_ANCHOR_QUERY_MARKERS):
        return True
    return bool(
        _query_intent_terms(
            text,
            intent_terms=_question_anchor_intent_terms_for_policy_refs(policy_plugin_refs),
        )
        or _query_is_short_question_anchor_candidate(text, policy_plugin_refs=policy_plugin_refs)
    )


def _query_is_short_question_anchor_candidate(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    if not policy_plugin_refs:
        return False
    normalized = _normalize_match_term(query)
    return _QUESTION_ANCHOR_SHORT_QUERY_MIN_CHARS <= len(normalized) <= _QUESTION_ANCHOR_SHORT_QUERY_MAX_CHARS


def _query_prefers_service_anchor(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return False
    if _query_has_quoted_anchor_candidate(query):
        return True
    for term in _service_anchor_priority_terms_for_policy_refs(policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) < 3:
            continue
        if normalized in query_term:
            return True
    entity_terms = tuple(
        _normalize_match_term(term)
        for term in _service_anchor_entity_terms_for_policy_refs(policy_plugin_refs)
        if _normalize_match_term(term)
    )
    if entity_terms and any(marker in query_term for marker in entity_terms):
        for term in _metadata_anchor_service_name_query_terms(query, policy_plugin_refs=policy_plugin_refs)[:6]:
            if len(_normalize_match_term(term)) >= _MIN_SPECIFIC_INTENT_CHARS:
                return True
    return False


def _query_has_mixed_intent(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _MIXED_INTENT_QUERY_MARKERS):
        return True
    return len(_mixed_intent_segment_parts(text)) >= 2 and bool(re.search(r"[？?。.]?$", text))


def _query_has_mixed_intent_for_policy(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    if _query_has_mixed_intent(query):
        return True
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    return len({(field, value) for field, value in requested_slots}) >= 2


def _query_has_explicit_question_form(query: str) -> bool:
    text = str(query or "").strip()
    return bool(text) and any(marker in text for marker in _EXPLICIT_QUESTION_FORM_MARKERS)


def _query_has_quoted_anchor_candidate(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    for match in _QUOTED_ANCHOR_RE.finditer(text):
        if len(_normalize_match_term(_quoted_anchor_match_text(match))) >= 4:
            return True
    return False


def _quoted_anchor_match_text(match: re.Match[str]) -> str:
    for group in match.groups():
        text = str(group or "").strip()
        if text:
            return text
    return ""


def _quoted_query_anchor_display_terms(query: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_ANCHOR_RE.finditer(str(query or "")):
        text = match.group(0).strip()
        normalized = _normalize_match_term(_quoted_anchor_match_text(match))
        if len(normalized) >= 4 and normalized not in seen:
            seen.add(normalized)
            out.append(text)
    return tuple(out)


def _quoted_query_anchor_terms(query: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _QUOTED_ANCHOR_RE.finditer(str(query or "")):
        normalized = _normalize_match_term(_quoted_anchor_match_text(match))
        if len(normalized) >= 4 and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


def _record_matches_quoted_query_anchor(record: dict[str, Any], *, query: str) -> bool:
    return _record_matches_quoted_query_anchor_for_policy(record, query=query)


def _record_matches_quoted_query_anchor_for_policy(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    anchors = _quoted_query_anchor_terms(query)
    if not anchors:
        return True
    values: list[str] = [str(record.get("content") or ""), str(record.get("title") or "")]
    anchor_fields = _exact_query_anchor_fields_for_policy_refs(policy_plugin_refs)
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            values.extend(_metadata_terms(metadata.get(field)))
    normalized_values = [_normalize_match_term(value) for value in values if value]
    return any(anchor in value or value in anchor for anchor in anchors for value in normalized_values if value)


def _anchor_binding_fields_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    fields: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        raw_binding = policy.get("anchor_binding")
        if isinstance(raw_binding, dict) and raw_binding.get("enabled") is True:
            for field in _metadata_terms(raw_binding.get("anchor_fields")):
                normalized = _normalize_match_term(field)
                if normalized and field not in seen:
                    seen.add(field)
                    fields.append(field)
        raw_anchor_fields = policy.get("anchor_fields")
        if isinstance(raw_anchor_fields, list | tuple):
            for raw in raw_anchor_fields:
                raw_dict = dict(raw) if isinstance(raw, dict) else {}
                field = str(raw_dict.get("metadata") or "").strip()
                normalized = _normalize_match_term(field)
                if normalized and field not in seen:
                    seen.add(field)
                    fields.append(field)
    return tuple(fields)


def _exact_query_anchor_fields_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    fields: list[str] = []
    seen: set[str] = set()
    anchor_fields = _anchor_binding_fields_for_policy_refs(policy_plugin_refs) or (
        "service_name",
        "case_title",
        "service_aliases",
    )
    for field in (*_EXACT_QUERY_ANCHOR_FIELDS, *anchor_fields):
        text = str(field or "").strip()
        if text and text not in seen:
            seen.add(text)
            fields.append(text)
    return tuple(fields)


def _policy_slot_intent_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            for raw_term in mapping.get("terms") or ():
                term = str(raw_term or "").strip()
                normalized = _normalize_match_term(term)
                if len(normalized) < 3 or normalized in seen:
                    continue
                seen.add(normalized)
                terms.append(term)
    return tuple(terms)


def _metadata_anchor_preflight_block_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_term in _response_hint_string_list(policy, "metadata_anchor_preflight_block_terms"):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _query_blocks_metadata_anchor_preflight(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    query_term = _normalize_match_term(query)
    if not query_term:
        return False
    return any(
        (normalized := _normalize_match_term(term)) and normalized in query_term
        for term in _metadata_anchor_preflight_block_terms_for_policy_refs(policy_plugin_refs)
    )


def _requested_policy_slot_values_for_query(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for _field, value in _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs):
        normalized_value = _normalize_match_term(value)
        if not value or not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        values.append(value)
    return tuple(values)


def _requested_policy_slot_specs_for_query(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[tuple[str, str], ...]:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return ()
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            field = str(mapping.get("metadata") or "").strip()
            if not field:
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            slot_values = raw_values or [mapping.get("value")]
            terms = tuple(_metadata_terms(mapping.get("terms")))
            if not terms:
                continue
            if not any((normalized := _normalize_match_term(term)) and normalized in query_term for term in terms):
                continue
            for raw_value in slot_values:
                value = str(raw_value or "").strip()
                normalized_value = _normalize_match_term(value)
                key = f"{field}\0{normalized_value}"
                if not value or not normalized_value or key in seen:
                    continue
                seen.add(key)
                specs.append((field, value))
    return tuple(specs)


def _query_has_policy_slot_intent(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return False
    for term in _policy_slot_intent_terms_for_policy_refs(policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) >= 3 and normalized in query_term:
            return True
    return False


def _query_allows_metadata_anchor_preflight(
    query: str,
    *,
    query_prefers_question_anchor: bool,
    query_prefers_service_anchor: bool,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_blocks_metadata_anchor_preflight(query, policy_plugin_refs=policy_plugin_refs):
        return False
    if _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        if (
            query_prefers_service_anchor
            and not _query_has_quoted_anchor_candidate(query)
            and any(
                marker in str(query or "")
                for marker in ("合并回答", "一并回答", "一起回答", "分别回答", "分开回答", "请合并", "请分别")
            )
        ):
            return False
        return bool(
            query_prefers_service_anchor
            or (
                _query_has_quoted_anchor_candidate(query)
                and _query_has_policy_slot_intent(query, policy_plugin_refs=policy_plugin_refs)
            )
        )
    if (
        query_prefers_question_anchor
        and not query_prefers_service_anchor
        and _query_has_policy_slot_intent(query, policy_plugin_refs=policy_plugin_refs)
        ):
        return False
    return bool(query_prefers_question_anchor or query_prefers_service_anchor)


def _metadata_anchor_should_query_question_first(
    query: str,
    *,
    query_prefers_question_anchor: bool,
    query_prefers_service_anchor: bool,
    prefer_question_anchor_first: bool,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if not query_prefers_question_anchor:
        return False
    if query_prefers_service_anchor and _query_has_quoted_anchor_candidate(query):
        return False
    if query_prefers_service_anchor and _requested_policy_slot_specs_for_query(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return True
    return bool(
        prefer_question_anchor_first
        or not query_prefers_service_anchor
        or _query_has_explicit_question_form(query)
    )


def _strip_mixed_intent_noise(value: str, *, terms: tuple[str, ...]) -> str:
    text = str(value or "").strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    previous = None
    while previous != text:
        previous = text
        for term in sorted(terms, key=len, reverse=True):
            if text.startswith(term):
                text = text[len(term) :].strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
                break
    return text


def _strip_mixed_intent_subject_instruction_tail(value: str) -> str:
    text = str(value or "").strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    previous = None
    while previous != text:
        previous = text
        text = _MIXED_INTENT_SUBJECT_TRAILING_INSTRUCTION_RE.sub("", text).strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    return text


def _mixed_intent_subject_anchor(segment: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> str:
    text = _strip_mixed_intent_noise(
        segment,
        terms=_mixed_intent_leading_noise_terms_for_policy_refs(policy_plugin_refs),
    )
    if not text:
        return ""
    best_index = len(text)
    intent_markers = _mixed_intent_subject_terms_for_policy_refs(policy_plugin_refs)
    for marker in sorted((str(item or "").strip() for item in intent_markers), key=len, reverse=True):
        if not marker:
            continue
        index = text.find(marker)
        if index >= 0:
            best_index = min(best_index, index)
    anchor = _strip_mixed_intent_subject_instruction_tail(text[:best_index])
    if any(marker in anchor for marker in ("/", "线上", "线下")):
        return ""
    return anchor if len(_normalize_match_term(anchor)) >= 3 else ""


def _clean_mixed_intent_query_segment(segment: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> str:
    return _strip_mixed_intent_noise(
        segment,
        terms=_mixed_intent_leading_noise_terms_for_policy_refs(policy_plugin_refs),
    )


def _mixed_intent_retrieval_queries(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    text = str(query or "").strip()
    if not _query_has_mixed_intent_for_policy(text, policy_plugin_refs=policy_plugin_refs):
        return ()

    max_queries = max(
        1,
        min(
            5,
            int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES", 4) or 4),
        ),
    )
    out: list[str] = []
    seen: set[str] = {_normalize_match_term(text)}
    quoted_subject_anchor = next(iter(_quoted_query_anchor_display_terms(text)), "")
    subject_anchor = quoted_subject_anchor
    for raw_segment in _MIXED_INTENT_SPLIT_RE.split(text):
        for raw_part in _mixed_intent_segment_parts(raw_segment):
            segment = _clean_mixed_intent_query_segment(raw_part, policy_plugin_refs=policy_plugin_refs)
            normalized_segment = _normalize_match_term(segment)
            if len(normalized_segment) < 3 and not (
                subject_anchor and _mixed_intent_segment_has_intent_marker(segment, policy_plugin_refs=policy_plugin_refs)
            ):
                continue
            segment_has_intent_marker = _mixed_intent_segment_has_intent_marker(
                segment,
                policy_plugin_refs=policy_plugin_refs,
            )
            segment_anchor = _mixed_intent_subject_anchor(segment, policy_plugin_refs=policy_plugin_refs)
            if segment_anchor and not quoted_subject_anchor:
                subject_anchor = segment_anchor
                if not segment_has_intent_marker:
                    continue
                candidate = segment
            elif subject_anchor:
                if not segment_has_intent_marker:
                    continue
                candidate = f"{subject_anchor}{segment}"
            else:
                candidate = segment
            normalized = _normalize_match_term(candidate)
            if len(normalized) < 4 or normalized in seen:
                continue
            seen.add(normalized)
            out.append(candidate)
            if len(out) >= max_queries:
                break
            for expanded_candidate in _mixed_intent_policy_slot_queries(
                segment=segment,
                subject_anchor=subject_anchor,
                policy_plugin_refs=policy_plugin_refs,
            ):
                normalized_expanded = _normalize_match_term(expanded_candidate)
                if len(normalized_expanded) < 4 or normalized_expanded in seen:
                    continue
                seen.add(normalized_expanded)
                out.append(expanded_candidate)
                if len(out) >= max_queries:
                    break
        if len(out) >= max_queries:
            break
    for fallback_query in _mixed_intent_policy_slot_queries_from_inferred_subject(
        text,
        policy_plugin_refs=policy_plugin_refs,
    ):
        normalized_fallback = _normalize_match_term(fallback_query)
        if len(normalized_fallback) < 4 or normalized_fallback in seen:
            continue
        seen.add(normalized_fallback)
        out.append(fallback_query)
        if len(out) >= max_queries:
            break
    return tuple(out)


def _mixed_intent_policy_slot_queries_from_inferred_subject(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    if len({(field, value) for field, value in requested_slots}) < 2:
        return ()
    subject = _infer_mixed_intent_subject_anchor(query, policy_plugin_refs=policy_plugin_refs)
    if len(_normalize_match_term(subject)) < 3:
        return ()

    out: list[str] = []
    seen_values: set[tuple[str, str]] = set()
    for field, value in requested_slots:
        key = (field, value)
        if key in seen_values:
            continue
        seen_values.add(key)
        term = _policy_slot_canonical_query_term(field=field, value=value, policy_plugin_refs=policy_plugin_refs)
        if not term:
            continue
        out.append(f"{subject}{term}")
    return tuple(out)


def _infer_mixed_intent_subject_anchor(query: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> str:
    quoted_subject = next(iter(_quoted_query_anchor_display_terms(query)), "")
    if quoted_subject:
        return quoted_subject
    direct_subject = _mixed_intent_subject_anchor(query, policy_plugin_refs=policy_plugin_refs)
    if direct_subject:
        return direct_subject
    parts = _mixed_intent_segment_parts(query)
    for part in reversed(parts):
        cleaned = _clean_mixed_intent_query_segment(part, policy_plugin_refs=policy_plugin_refs)
        if not _mixed_intent_segment_has_intent_marker(cleaned, policy_plugin_refs=policy_plugin_refs):
            normalized = _normalize_match_term(cleaned)
            if len(normalized) >= 3:
                return cleaned.strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    return ""


def _policy_slot_canonical_query_term(
    *,
    field: str,
    value: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    normalized_field = str(field or "").strip()
    normalized_value = _normalize_match_term(value)
    if not normalized_field or not normalized_value:
        return ""
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        mappings = [
            dict(raw_mapping)
            for raw_mapping in policy.get("query_expansion_values") or ()
            if isinstance(raw_mapping, dict)
        ]
        mappings.sort(key=lambda mapping: 1 if isinstance(mapping.get("values"), list | tuple | set) else 0)
        for mapping in mappings:
            if str(mapping.get("metadata") or "").strip() != normalized_field:
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            values = raw_values or [mapping.get("value")]
            if normalized_value not in {_normalize_match_term(item) for item in values}:
                continue
            terms = tuple(_metadata_terms(mapping.get("terms")))
            return next((term for term in terms if len(_normalize_match_term(term)) >= 2), "")
    return str(value or "").strip()


def _policy_slot_query_terms(
    *,
    field: str,
    value: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    normalized_field = str(field or "").strip()
    normalized_value = _normalize_match_term(value)
    if not normalized_field or not normalized_value:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_mapping in policy.get("query_expansion_values") or ():
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            if str(mapping.get("metadata") or "").strip() != normalized_field:
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            values = raw_values or [mapping.get("value")]
            if normalized_value not in {_normalize_match_term(item) for item in values}:
                continue
            for raw_term in (*_metadata_terms(mapping.get("terms")), value):
                term = str(raw_term or "").strip()
                normalized = _normalize_match_term(term)
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                out.append(term)
    return tuple(out)


def _record_policy_slot_coverage_text(record: dict[str, Any]) -> str:
    parts: list[str] = [str(record.get("title") or ""), str(record.get("content") or "")]
    for metadata in _iter_record_metadata_layers(record):
        for value in metadata.values():
            parts.extend(str(term or "") for term in _metadata_terms(value))
    return _normalize_match_term("\n".join(part for part in parts if part))


def _record_covers_requested_policy_slots(
    record: dict[str, Any],
    requested_slot_specs: tuple[tuple[str, str], ...],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    requested_norms = tuple(
        dict.fromkeys(
            (field, _normalize_match_term(value))
            for field, value in requested_slot_specs
            if field and _normalize_match_term(value)
        )
    )
    if not requested_norms:
        return True
    record_text = _record_policy_slot_coverage_text(record)
    for field, normalized_value in requested_norms:
        value = next((raw_value for raw_field, raw_value in requested_slot_specs if raw_field == field and _normalize_match_term(raw_value) == normalized_value), "")
        if _record_matches_requested_slot(record, ((field, value),)):
            continue
        terms = _policy_slot_query_terms(field=field, value=value, policy_plugin_refs=policy_plugin_refs)
        if not any((normalized := _normalize_match_term(term)) and normalized in record_text for term in terms):
            return False
    return True


def _mixed_intent_policy_slot_queries(
    *,
    segment: str,
    subject_anchor: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    segment_term = _normalize_match_term(segment)
    subject = str(subject_anchor or "").strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    if len(segment_term) < 3 or len(_normalize_match_term(subject)) < 3:
        return ()

    out: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        mappings = [dict(item) for item in policy.get("query_expansion_values") or () if isinstance(item, dict)]
        canonical_terms_by_value: dict[str, list[str]] = {}
        for mapping in mappings:
            if "values" in mapping:
                continue
            value = str(mapping.get("value") or "").strip()
            if value:
                canonical_terms_by_value.setdefault(value, []).extend(_metadata_terms(mapping.get("terms")))
        for mapping in mappings:
            mapping_terms = tuple(_metadata_terms(mapping.get("terms")))
            if not any((normalized := _normalize_match_term(term)) and normalized in segment_term for term in mapping_terms):
                continue
            raw_values = mapping.get("values") if isinstance(mapping.get("values"), list | tuple | set) else None
            for raw_value in raw_values or [mapping.get("value")]:
                value = str(raw_value or "").strip()
                if not value:
                    continue
                if any(
                    (normalized := _normalize_match_term(term)) and normalized in segment_term
                    for term in canonical_terms_by_value.get(value, [])
                ):
                    continue
                canonical_term = next(
                    (
                        term
                        for term in canonical_terms_by_value.get(value, [])
                        if (normalized := _normalize_match_term(term)) and normalized not in segment_term
                    ),
                    "",
                )
                normalized_canonical = _normalize_match_term(canonical_term)
                if len(normalized_canonical) < 2 or normalized_canonical in seen:
                    continue
                seen.add(normalized_canonical)
                out.append(f"{subject}{canonical_term}")
    return tuple(out)


def _mixed_intent_segment_parts(segment: str) -> tuple[str, ...]:
    text = str(segment or "").strip()
    if not text:
        return ()
    return tuple(part.strip() for part in _MIXED_INTENT_LIST_SPLIT_RE.split(text) if part.strip())


def _mixed_intent_segment_has_intent_marker(segment: str, *, policy_plugin_refs: tuple[str, ...] = ()) -> bool:
    text = str(segment or "").strip()
    if not text:
        return False
    markers = _mixed_intent_subject_terms_for_policy_refs(policy_plugin_refs)
    if not markers:
        return True
    return any(marker and marker in text for marker in markers)


def _filter_records_by_mixed_intent_subject_anchor(
    records: list[dict[str, Any]],
    *,
    subquery: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    subject_anchor = _mixed_intent_subject_anchor(subquery, policy_plugin_refs=policy_plugin_refs)
    normalized_anchor = _normalize_match_term(subject_anchor)
    if len(normalized_anchor) < 3:
        return records
    anchored: list[dict[str, Any]] = []
    for record in records or []:
        for metadata in _iter_record_metadata_layers(record):
            values: list[str] = []
            for key in _exact_query_anchor_fields_for_policy_refs(policy_plugin_refs):
                values.extend(_metadata_terms(metadata.get(key)))
            if any(normalized_anchor in _normalize_match_term(value) for value in values):
                anchored.append(record)
                break
    return anchored or records


def _question_marker_overlap_bonus(query_term: str, candidate: str) -> float:
    query_has_marker = False
    for marker in _QUESTION_ANCHOR_QUERY_MARKERS:
        normalized_marker = _normalize_match_term(marker)
        if not normalized_marker:
            continue
        query_has_marker = query_has_marker or normalized_marker in query_term
        if normalized_marker in query_term and normalized_marker in candidate:
            return 0.08
    if not query_has_marker and any(
        normalized_marker and normalized_marker in candidate
        for normalized_marker in (_normalize_match_term(marker) for marker in _QUESTION_ANCHOR_QUERY_MARKERS)
    ):
        return 0.08
    return 0.0


def _record_region_terms(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for metadata in _iter_record_metadata_layers(record):
        for key in _REGION_ANCHOR_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                normalized = _normalize_match_term(term)
                if len(normalized) < 2 or normalized in seen:
                    continue
                seen.add(normalized)
                out.append(normalized)
    return out


def _record_has_query_region_anchor(record: dict[str, Any], *, query_term: str) -> bool:
    if not query_term:
        return False
    for region in _record_region_terms(record):
        if region in query_term:
            return True
        if _longest_common_substring_length(region, query_term) >= _MIN_REGION_ANCHOR_OVERLAP_CHARS:
            return True
    return False


def _response_hint_candidate_terms(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    group: dict[str, Any],
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    gate = _response_hint_dict(group, "query_gate")
    for label in _response_hint_string_list(gate, "content_labels"):
        for value in _metadata_terms(fields.get(label)):
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
    for layer in [metadata, *[metadata.get(key) for key in _PUBLIC_METADATA_VIEW_KEYS]]:
        if not isinstance(layer, dict):
            continue
        for key in _response_hint_string_list(gate, "metadata"):
            for value in _metadata_terms(layer.get(key)):
                if value in seen:
                    continue
                seen.add(value)
                out.append(value)
    return out


def _response_hint_group_matches_query(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    group: dict[str, Any],
    query: str,
) -> bool:
    gate = _response_hint_dict(group, "query_gate")
    if not gate:
        return True
    query_term = _normalize_match_term(query)
    if not query_term:
        return True
    min_chars = max(1, int(gate.get("min_chars") or 4))
    min_common_chars = max(0, int(gate.get("min_common_chars") or 0))
    for candidate in _response_hint_candidate_terms(fields, metadata, group=group):
        term = _normalize_match_term(candidate)
        if len(term) >= min_chars and (term in query_term or query_term in term):
            return True
        if min_common_chars and min(len(term), len(query_term)) >= min_common_chars:
            if _longest_common_substring_length(query_term, term) >= min_common_chars:
                return True
    return False


def _response_hint_group_has_required_fields(fields: dict[str, str], *, group: dict[str, Any]) -> bool:
    required = _response_hint_string_list(group, "required_any_labels")
    if not required:
        return False
    return any(label in fields for label in required)


def _matching_response_hint_group(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    response_hints: dict[str, Any],
    query: str = "",
) -> dict[str, Any] | None:
    for group in _response_hint_groups(response_hints):
        if not _response_hint_group_has_required_fields(fields, group=group):
            continue
        if not _response_hint_group_matches_query(fields, metadata, group=group, query=query):
            continue
        return group
    return None


def _answer_hints_from_fields(
    fields: dict[str, str],
    metadata: dict[str, Any],
    *,
    response_hints: dict[str, Any],
    query: str = "",
) -> list[str]:
    group = _matching_response_hint_group(fields, metadata, response_hints=response_hints, query=query)
    if group is not None:
        labels = _response_hint_string_list(group, "hint_labels")
        bits = [f"{label}：{fields[label]}" for label in labels if fields.get(label)]
        question = str(query or "").strip()
        question_label = str(group.get("question_from_query_label") or "").strip()
        answer_label = str(group.get("answer_label") or "").strip()
        if question and question_label and answer_label and bits:
            return [f"{question_label}：{question}", f"{answer_label}：{'；'.join(bits)}"]
        return bits
    return [f"{label}：{value}" for label, value in fields.items()]


def _find_numbered_marker(
    text: str,
    number: int,
    *,
    start: int,
    named_markers: dict[str, Any] | None = None,
) -> tuple[int, str]:
    markers = [
        f"{number}.",
        f"{number}、",
        f"{number}．",
        f"{number})",
        f"{number}）",
        f"({number})",
        f"（{number}）",
    ]
    named_marker = str((named_markers or {}).get(str(number)) or "").strip()
    if named_marker:
        markers.append(named_marker)
    best_index = -1
    best_marker = ""
    for marker in markers:
        index = text.find(marker, start)
        if index < 0:
            continue
        if best_index < 0 or index < best_index:
            best_index = index
            best_marker = marker
    return best_index, best_marker


def _extract_numbered_option_terms(
    text: str,
    *,
    max_terms: int = 4,
    named_markers: dict[str, Any] | None = None,
) -> list[str]:
    normalized = " ".join(str(text or "").split())
    named_marker_values = {str(value or "").strip() for value in (named_markers or {}).values() if str(value or "").strip()}
    terms: list[str] = []
    cursor = 0
    for number in range(1, max_terms + 1):
        marker_index, marker = _find_numbered_marker(normalized, number, start=cursor, named_markers=named_markers)
        if marker_index < 0:
            break
        start = marker_index + len(marker)
        while start < len(normalized) and (normalized[start].isspace() or normalized[start] in "，、,:："):
            start += 1
        end = start
        stop_chars = "（(：:；;。"
        if marker in named_marker_values:
            stop_chars += "，,"
        while end < len(normalized) and normalized[end] not in stop_chars:
            end += 1
        term = normalized[start:end].strip()
        if 2 <= len(term) <= 40:
            terms.append(term)
        cursor = end
    return terms


def _enumerated_answer_hints(content: str, *, query: str = "", response_hints: dict[str, Any]) -> list[str]:
    enumeration = _response_hint_dict(response_hints, "enumeration")
    if enumeration.get("enabled") is not True:
        return []
    text = str(content or "").strip()
    if not text:
        return []
    named_markers = _response_hint_dict(enumeration, "named_markers")
    first_marker_index, marker = _find_numbered_marker(" ".join(text.split()), 1, start=0, named_markers=named_markers)
    if first_marker_index < 0:
        return []
    prefix = " ".join(text.split())[:first_marker_index][-90:]
    query_text = str(query or "").strip()
    intro_terms = _response_hint_string_list(enumeration, "intro_terms")
    query_terms = _response_hint_string_list(enumeration, "query_terms")
    if not intro_terms:
        return []
    if not any(term in prefix for term in intro_terms) and not any(marker.startswith(term) for term in intro_terms):
        return []
    if query_text and query_terms and not any(term in query_text for term in query_terms):
        return []
    max_terms = max(1, int(enumeration.get("max_terms") or 4))
    terms = _extract_numbered_option_terms(text, max_terms=max_terms, named_markers=named_markers)
    if len(terms) < 2:
        return []
    separator = str(enumeration.get("term_separator") or ", ")
    terms_text = separator.join(terms)
    template = str(enumeration.get("message_template") or "Preserve these option names: {terms}")
    message = template.format(terms=terms_text)
    message_prefix = str(enumeration.get("prefix") or "").strip()
    return [f"{message_prefix}：{message}" if message_prefix else message]


def _content_starts_with_response_hint(content: str, *, response_hints: dict[str, Any]) -> bool:
    prefixes = list(_response_hint_string_list(response_hints, "existing_hint_prefixes"))
    answer_prefix = _response_hint_text(
        response_hints,
        "answer_prefix",
        default=_DEFAULT_RESPONSE_HINT_ANSWER_PREFIX,
    )
    if answer_prefix:
        prefixes.append(answer_prefix)
    normalized = str(content or "").lstrip()
    return any(normalized.startswith(prefix) for prefix in prefixes if prefix)


def _content_with_answer_hints(
    content: str,
    metadata: dict[str, Any],
    *,
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    body = str(content or "").strip()
    if not body:
        return body
    response_hints = _response_hints_for_metadata(metadata, policy_plugin_refs=policy_plugin_refs)
    enumerated_hints = _enumerated_answer_hints(body, query=query, response_hints=response_hints)
    enumerated_prefix = "；".join(enumerated_hints)
    if _content_starts_with_response_hint(body, response_hints=response_hints):
        if enumerated_prefix and not body.startswith(enumerated_prefix):
            return f"{enumerated_prefix}\n\n{body}"
        return body
    metadata_hints = _metadata_answer_highlights(
        metadata,
        response_hints=response_hints,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    fields = _structured_fields_from_content(body, response_hints=response_hints)
    if (
        fields
        and not metadata_hints
        and not _matching_response_hint_group(fields, metadata, response_hints=response_hints, query=query)
    ):
        return body
    hints = metadata_hints or _answer_hints_from_fields(
        fields,
        metadata,
        response_hints=response_hints,
        query=query,
    )
    if not hints and not enumerated_prefix:
        return body
    answer_prefix = _response_hint_text(
        response_hints,
        "answer_prefix",
        default=_DEFAULT_RESPONSE_HINT_ANSWER_PREFIX,
    )
    source_prefix = _response_hint_text(
        response_hints,
        "source_prefix",
        default=_DEFAULT_RESPONSE_HINT_SOURCE_PREFIX,
    )
    if enumerated_prefix and not hints:
        return f"{enumerated_prefix}\n\n{source_prefix}：\n{body}"
    if enumerated_prefix:
        return f"{enumerated_prefix}\n\n{answer_prefix}：{'；'.join(hints)}\n\n{source_prefix}：\n{body}"
    return f"{answer_prefix}：{'；'.join(hints)}\n\n{source_prefix}：\n{body}"


def _record_retrieval_intents(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    metadata_layers = _iter_record_metadata_layers(record)
    for metadata in metadata_layers:
        for key in _RETRIEVAL_INTENT_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                if term in seen:
                    continue
                seen.add(term)
                out.append(term)
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    policy = _retrieval_policy_for_plugin_ref(plugin_ref)
    for term in retrieval_policy_query_terms(policy, metadata_layers=metadata_layers):
        if term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out


def _is_specific_intent_term(term: str) -> bool:
    text = str(term or "").strip()
    return len(text) >= _MIN_SPECIFIC_INTENT_CHARS


def _record_intent_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    query_text = str(query or "").casefold()
    if not query_text:
        return 0.0
    matches = 0
    for term in _record_retrieval_intents(record, policy_plugin_refs=policy_plugin_refs):
        if not _is_specific_intent_term(term):
            continue
        folded = term.casefold()
        if folded and (folded in query_text or query_text in folded):
            matches += 1
    return min(_INTENT_MATCH_BONUS * matches, _INTENT_MATCH_BONUS_MAX)


def _record_mixed_intent_subquery_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    if not _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        return 0.0
    query_term = _normalize_match_term(query)
    best = 0.0
    for metadata in _iter_record_metadata_layers(record):
        subquery = str(metadata.get("dify_mixed_intent_subquery") or "").strip()
        if not subquery:
            continue
        subquery_term = _normalize_match_term(subquery)
        if not subquery_term or subquery_term == query_term:
            continue
        question_bonus = _record_question_intent_bonus(
            record,
            query=subquery,
            policy_plugin_refs=policy_plugin_refs,
        )
        subquery_bonus = (
            0.1
            + _record_metadata_anchor_bonus(record, query=subquery)
            + _record_intent_bonus(record, query=subquery, policy_plugin_refs=policy_plugin_refs)
            + question_bonus
        )
        subquery_cap = 1.4 if question_bonus > 0 else 0.24
        best = max(
            best,
            min(subquery_bonus, subquery_cap),
        )
    return min(best, 1.4)


def _record_metadata_anchor_bonus(record: dict[str, Any], *, query: str) -> float:
    query_term = _normalize_match_term(query)
    if len(query_term) < 4:
        return 0.0
    best = 0.0
    has_query_region = _record_has_query_region_anchor(record, query_term=query_term)
    for metadata in _iter_record_metadata_layers(record):
        for key in _METADATA_ANCHOR_KEYS:
            for term in _metadata_terms(metadata.get(key)):
                candidate = _normalize_match_term(term)
                if len(candidate) < 4:
                    continue
                if candidate == query_term:
                    best = max(best, 0.14)
                elif candidate in query_term or query_term in candidate:
                    best = max(best, 0.1 if key in _FUZZY_METADATA_ANCHOR_KEYS else 0.08)
                elif key in _FUZZY_METADATA_ANCHOR_KEYS and _cjk_bigram_overlap_count(query_term, candidate) >= 2:
                    best = max(best, 0.1)
                elif key == "question" and has_query_region:
                    overlap = _longest_common_substring_length(query_term, candidate)
                    if overlap >= _MIN_REGIONAL_QUESTION_OVERLAP_CHARS:
                        best = max(best, 0.12)
    if best > 0 and has_query_region:
        best += 0.02
    return best


def _record_plugin_ref(record: dict[str, Any], *, fallback_plugin_refs: tuple[str, ...] = ()) -> str:
    for metadata in _iter_record_metadata_layers(record):
        for key in ("chunk_python_plugin", "governance_python_plugin"):
            value = str(metadata.get(key) or "").strip()
            if value:
                return value
    for fallback in fallback_plugin_refs or ():
        value = str(fallback or "").strip()
        if value:
            return value
    return ""


@lru_cache(maxsize=128)
def _retrieval_policy_for_plugin_ref(plugin_ref: str) -> dict[str, Any]:
    ref = str(plugin_ref or "").strip()
    if not ref.startswith("plugin:"):
        return {}
    try:
        from app.rag.pipeline_plugins.registry import resolve_registered_plugin_descriptor

        descriptor = resolve_registered_plugin_descriptor(ref)
    except Exception:  # noqa: BLE001
        return {}
    policy = getattr(descriptor, "retrieval_policy", None)
    if isinstance(policy, dict) and policy.get("schema") == "mimirq.retrieval_policy.v1":
        return dict(policy)
    return {}


def _policy_string_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...], key: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_term in _metadata_terms(policy.get(key)):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _service_anchor_entity_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    return _policy_string_terms_for_policy_refs(policy_plugin_refs, "service_anchor_entity_terms")


def _service_anchor_leading_noise_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    return _policy_string_terms_for_policy_refs(policy_plugin_refs, "service_anchor_leading_noise_terms")


def _service_anchor_cutoff_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    return _policy_string_terms_for_policy_refs(policy_plugin_refs, "service_anchor_cutoff_terms")


def _service_anchor_admin_aliases_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_field in policy.get("anchor_fields") or ():
            field = dict(raw_field) if isinstance(raw_field, dict) else {}
            if str(field.get("role") or "").strip() != "administrative_area":
                continue
            raw_aliases = field.get("aliases")
            if not isinstance(raw_aliases, dict):
                continue
            for canonical, values in raw_aliases.items():
                for raw_value in (canonical, *_metadata_terms(values)):
                    value = str(raw_value or "").strip()
                    normalized = _normalize_match_term(value)
                    if not value or not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    aliases.append(value)
    return tuple(aliases)


def _question_anchor_generic_subject_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    return _policy_string_terms_for_policy_refs(policy_plugin_refs, "question_anchor_generic_subject_terms")


def _fast_response_always_labels_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    return _policy_string_terms_for_policy_refs(policy_plugin_refs, "fast_response_always_labels")


def _fast_response_field_rules_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    rules: list[tuple[str, tuple[str, ...]]] = []
    seen_labels: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        for raw_rule in policy.get("fast_response_field_rules") or ():
            rule = dict(raw_rule) if isinstance(raw_rule, dict) else {}
            label = str(rule.get("label") or "").strip()
            if not label or label in seen_labels:
                continue
            markers = tuple(
                marker
                for marker in _metadata_terms(rule.get("markers"))
                if str(marker or "").strip()
            )
            if not markers:
                continue
            seen_labels.add(label)
            rules.append((label, markers))
    return tuple(rules)


def _requested_label_prefixes_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    prefixes: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        if not isinstance(policy, dict) or policy.get("schema") != "mimirq.retrieval_policy.v1":
            continue
        response_hints = policy.get("response_hints")
        if not isinstance(response_hints, dict):
            continue
        for field_spec in _response_hint_dict_list(response_hints, "answer_highlight_metadata_fields"):
            prefix = str(field_spec.get("requested_labels_prefix") or "").strip()
            if not prefix or prefix in seen:
                continue
            seen.add(prefix)
            prefixes.append(prefix)
    return tuple(prefixes)


def _service_anchor_noise_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in retrieval_policy_service_anchor_noise_terms(policy):
            term = str(raw_term or "").strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return tuple(terms)


def _service_anchor_priority_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in retrieval_policy_service_anchor_priority_terms(policy):
            term = str(raw_term or "").strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
    return tuple(terms)


def _service_anchor_query_rewrite_terms_for_policy_refs(query: str, policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in retrieval_policy_service_anchor_query_rewrite_terms(policy, query=query):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _mixed_intent_leading_noise_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw_term in _MIXED_INTENT_DEFAULT_LEADING_NOISE_TERMS:
        term = str(raw_term or "").strip()
        normalized = _normalize_match_term(term)
        if not term or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in retrieval_policy_mixed_intent_leading_noise_terms(policy):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _mixed_intent_subject_terms_for_policy_refs(policy_plugin_refs: tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for plugin_ref in policy_plugin_refs or ():
        policy = _retrieval_policy_for_plugin_ref(plugin_ref)
        for raw_term in retrieval_policy_mixed_intent_subject_terms(policy):
            term = str(raw_term or "").strip()
            normalized = _normalize_match_term(term)
            if not term or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(term)
    return tuple(terms)


def _records_retrieval_policy_diagnostics(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    return records_retrieval_policy_diagnostics(
        records,
        query=query,
        plugin_ref_for_record=lambda record: _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=_retrieval_policy_for_plugin_ref,
    )


def _response_compaction_for_records(
    records: list[dict[str, Any]],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    refs: list[str] = []
    seen: set[str] = set()
    for ref in policy_plugin_refs:
        text = str(ref or "").strip()
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for record in records or ():
        text = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
        if text and text not in seen:
            seen.add(text)
            refs.append(text)
    for ref in refs:
        compaction = retrieval_policy_response_compaction(_retrieval_policy_for_plugin_ref(ref))
        if bool(compaction.get("enabled")):
            return compaction
    return {"enabled": False}


def _sort_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> None:
    anchor_binding_scores = record_retrieval_policy_anchor_binding_scores(
        records,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=_retrieval_policy_for_plugin_ref,
    )
    exact_anchor_scores = _record_exact_anchor_protection_scores(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    records.sort(
        key=lambda item: _record_rank_score(item, query=query, policy_plugin_refs=policy_plugin_refs)
        + anchor_binding_scores.get(id(item), 0.0)
        + exact_anchor_scores.get(id(item), 0.0),
        reverse=True,
    )


def _record_exact_anchor_protection_scores(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[int, float]:
    if not records:
        return {}
    if _strong_question_anchor_records(records, query=query, policy_plugin_refs=policy_plugin_refs):
        return {}
    exact_anchor_records = [
        record
        for record in records
        if _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
    ]
    if not exact_anchor_records:
        return {}
    return {id(record): 1.2 for record in exact_anchor_records}


def _dify_external_reranker_enabled() -> bool:
    return bool(getattr(settings, "ENABLE_RERANKER", False)) and bool(
        getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED", True)
    )


def _record_needs_final_rerank(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return not bool(record.get("reranker_provider") or metadata.get("reranker_provider"))


def _record_final_rerank_candidate_id(record: dict[str, Any], *, index: int, used: set[str]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    candidates = [
        _record_source_identity_key(record),
        str(metadata.get("chunk_id") or "").strip(),
        str(metadata.get("document_id") or "").strip(),
        str(record.get("title") or "").strip(),
    ]
    base = next((item for item in candidates if item), "")
    if not base:
        payload = f"{record.get('title') or ''}\n{record.get('content') or ''}"
        base = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]
    candidate_id = base
    suffix = 1
    while candidate_id in used:
        suffix += 1
        candidate_id = f"{base}#{suffix}"
    used.add(candidate_id)
    return candidate_id or f"idx:{index}"


def _record_final_rerank_text(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        parts.append(text)

    add(record.get("title"))
    add(record.get("content"))
    metadata_fields = (*_EXACT_QUERY_ANCHOR_FIELDS, "answer", "summary", *_anchor_binding_fields_for_policy_refs(policy_plugin_refs))
    for metadata in _iter_record_metadata_layers(record):
        for field in metadata_fields:
            for value in _metadata_terms(metadata.get(field)):
                add(value)
    return "\n".join(parts)


async def _final_rerank_records_for_query(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if len(records or []) <= 1:
        return records
    if not any(_record_needs_final_rerank(record) for record in records):
        return records
    if not _dify_external_reranker_enabled():
        return records

    provider = str(getattr(settings, "RERANKER_PROVIDER", "llm") or "llm").strip().lower()
    if provider in {"none", "off", "false", "0"}:
        return records

    try:
        configured_top_n = int(getattr(settings, "RERANKER_TOP_N", top_k) or top_k)
    except (TypeError, ValueError):
        configured_top_n = int(top_k or 1)
    candidate_count = min(len(records), max(1, int(top_k or 1), configured_top_n))

    used_ids: set[str] = set()
    id_to_record: dict[str, dict[str, Any]] = {}
    candidates: list[RerankCandidate] = []
    for index, record in enumerate(records[:candidate_count]):
        text = _record_final_rerank_text(record, policy_plugin_refs=policy_plugin_refs)
        if not text:
            continue
        candidate_id = _record_final_rerank_candidate_id(record, index=index, used=used_ids)
        metadata = dict(record.get("metadata") if isinstance(record.get("metadata"), dict) else {})
        metadata["score"] = float(record.get("score") or 0.0)
        metadata["title"] = str(record.get("title") or "")
        candidates.append(RerankCandidate(id=candidate_id, text=text, metadata=metadata))
        id_to_record[candidate_id] = record

    if len(candidates) <= 1:
        return records

    try:
        reranker = get_reranker(provider)
        start = time.perf_counter()
        result = await run_blocking_retrieval_call(
            reranker.rerank,
            query,
            candidates,
            top_n=len(candidates),
            tenant_id=None,
            query_type=None,
        )
        elapsed_sec = result.elapsed_sec if result.elapsed_sec is not None else time.perf_counter() - start
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dify external final reranker failed (%s): %s", provider, exc)
        return records

    rerank_provider = result.provider or provider
    ordered: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for candidate_id in result.ordered_ids:
        record = id_to_record.get(str(candidate_id))
        if record is None or candidate_id in consumed:
            continue
        consumed.add(str(candidate_id))
        next_record = dict(record)
        metadata = dict(next_record.get("metadata") if isinstance(next_record.get("metadata"), dict) else {})
        metadata["reranker_provider"] = rerank_provider
        metadata["rerank_elapsed_sec"] = round(float(elapsed_sec or 0.0), 3)
        metadata["rerank_model_used"] = result.model_used
        metadata["dify_final_rerank"] = True
        if candidate_id in result.score_map:
            rerank_score = _clamp_score(result.score_map[candidate_id])
            metadata["rerank_score"] = rerank_score
            next_record["score"] = rerank_score
        next_record["metadata"] = metadata
        ordered.append(next_record)

    for candidate in candidates:
        if candidate.id in consumed:
            continue
        record = id_to_record.get(candidate.id)
        if record is not None:
            ordered.append(record)

    if not ordered:
        return records
    reranked_records = ordered + records[candidate_count:]
    _sort_records_for_query(reranked_records, query=query, policy_plugin_refs=policy_plugin_refs)
    return reranked_records


def _record_rank_score(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    return (
        float(record.get("score") or 0.0)
        + _record_metadata_anchor_bonus(record, query=query)
        + _record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + _record_exact_primary_alias_bonus(record, query=query)
        + _record_url_evidence_bonus(record, query=query)
        + _record_question_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + _record_answerfulness_score(record, policy_plugin_refs=policy_plugin_refs)
        + _record_mixed_intent_subquery_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
        + record_retrieval_policy_bonus(
            record,
            query=query,
            plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
            metadata_layers_for_record=_iter_record_metadata_layers,
            policy_resolver=_retrieval_policy_for_plugin_ref,
        )
    )


def _record_exact_primary_alias_bonus(record: dict[str, Any], *, query: str) -> float:
    query_term = _normalize_match_term(query)
    if len(query_term) < 3:
        return 0.0
    for metadata in _iter_record_metadata_layers(record):
        for term in _metadata_terms(metadata.get("primary_alias")):
            if _normalize_match_term(term) == query_term:
                return _EXACT_PRIMARY_ALIAS_MATCH_BONUS
    return 0.0


_URL_EVIDENCE_QUERY_MARKERS = (
    "入口",
    "链接",
    "网址",
    "网站",
    "网页",
    "在线",
    "线上",
    "网上",
    "app",
    "小程序",
    "二维码",
    "url",
    "http",
)


def _query_requests_url_evidence(query: str) -> bool:
    text = str(query or "").casefold()
    if not text:
        return False
    normalized = _normalize_match_term(text)
    return any(marker in text or _normalize_match_term(marker) in normalized for marker in _URL_EVIDENCE_QUERY_MARKERS)


def _record_url_evidence_bonus(record: dict[str, Any], *, query: str = "") -> float:
    if not _query_requests_url_evidence(query):
        return 0.0
    urls = 0
    for metadata in _iter_record_metadata_layers(record):
        urls += len(_metadata_terms(metadata.get("urls")))
    return min(_URL_EVIDENCE_BONUS_MAX, _URL_EVIDENCE_BONUS * urls)


def _dify_fast_candidate_top_k(top_k: int) -> int:
    configured = max(1, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX", 3) or 3))
    return max(1, min(max(1, int(top_k or 1)), configured))


def _dify_fast_response_top_k(top_k: int) -> int:
    configured = max(1, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX", 2) or 2))
    return max(1, min(max(1, int(top_k or 1)), configured))


def _dify_fast_content_max_chars() -> int:
    return max(200, min(10000, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 1400) or 1400)))


def _dify_fast_total_content_max_chars() -> int:
    return max(
        200,
        min(
            50000,
            int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 2200) or 2200),
        ),
    )


def _structured_label_values_from_content(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_label = ""
    for segment in re.split(r"\s*\|\s*|\n+", str(content or "")):
        text = segment.strip()
        if not text:
            continue
        parts = _field_line_parts(text)
        if parts is None:
            if current_label and len(fields[current_label]) < _dify_fast_content_max_chars():
                fields[current_label] = f"{fields[current_label]}；{text}"
            continue
        label, value = parts
        current_label = label
        fields.setdefault(label, value)
    return fields


def _requested_fast_response_labels(
    query: str,
    fields: dict[str, str],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    query_text = str(query or "")
    labels: list[str] = []
    seen: set[str] = set()

    def add(label: str) -> None:
        if label in seen or label not in fields:
            return
        seen.add(label)
        labels.append(label)

    if "答案" in fields:
        add("问题")
        add("答案")
        return tuple(labels)

    rules = _fast_response_field_rules_for_policy_refs(policy_plugin_refs)
    exact_labels: set[str] = set()
    for label in _fast_response_always_labels_for_policy_refs(policy_plugin_refs):
        add(label)
    for label, _markers in rules:
        if label in query_text:
            exact_labels.add(label)
            add(label)
    normalized_exact_labels = tuple(
        normalized for normalized in (_normalize_match_term(label) for label in exact_labels) if normalized
    )
    for label, markers in rules:
        if label in exact_labels:
            continue
        matched_markers = tuple(marker for marker in markers if marker in query_text)
        if not matched_markers:
            continue
        if normalized_exact_labels:
            shadowed = True
            for marker in matched_markers:
                normalized_marker = _normalize_match_term(marker)
                if not normalized_marker:
                    continue
                if not any(
                    normalized_marker != exact_label and normalized_marker in exact_label
                    for exact_label in normalized_exact_labels
                ):
                    shadowed = False
                    break
            if shadowed:
                continue
        add(label)
    return tuple(labels)


def _requested_response_hint_metadata_labels(
    fields: tuple[str, ...],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    enabled: bool,
) -> tuple[str, ...]:
    if not enabled:
        return ()
    query_text = str(query or "")
    if not query_text:
        return ()
    available = set(fields)
    labels: list[str] = []
    seen: set[str] = set()
    for label, markers in _fast_response_field_rules_for_policy_refs(policy_plugin_refs):
        if label not in available or label in seen:
            continue
        if not any(marker in query_text for marker in markers):
            continue
        seen.add(label)
        labels.append(label)
    return tuple(labels)


def _prioritized_response_hint_metadata_fields(
    fields: tuple[str, ...],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    enabled: bool,
) -> tuple[str, ...]:
    if not enabled:
        return fields
    requested = _requested_response_hint_metadata_labels(
        fields,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        enabled=True,
    )
    if not requested:
        return fields
    ordered: list[str] = []
    seen: set[str] = set()
    for field in (*requested, *fields):
        if field in seen:
            continue
        seen.add(field)
        ordered.append(field)
    return tuple(ordered)


_FAST_ANSWER_QUERY_STOP_TERMS = {
    "什么",
    "哪些",
    "怎么",
    "如何",
    "申请",
    "办理",
    "查询",
    "帮我",
    "核对",
    "依据",
    "最好",
    "是不是能办",
}


def _fast_answer_query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        term = str(value or "").strip(" \t\r\n，。；;、：:？?！!（）()“”\"'《》「」")
        normalized = _normalize_match_term(term)
        if len(normalized) < 2 or normalized in seen or normalized in _FAST_ANSWER_QUERY_STOP_TERMS:
            return
        seen.add(normalized)
        terms.append(term)

    for anchor in _quoted_query_anchor_terms(query):
        add(anchor)
    for segment in _iter_anchor_word_segments(query):
        add(segment)
        for suffix in ("怎么申请", "如何申请", "怎么办理", "如何办理", "怎么查", "如何查", "是什么"):
            if segment.endswith(suffix):
                add(segment[: -len(suffix)])
                break
    terms.sort(key=lambda item: len(_normalize_match_term(item)), reverse=True)
    return tuple(terms)


def _fast_answer_snippet_segments(answer: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(answer or "")).strip()
    if not text:
        return []
    return [
        segment.strip()
        for segment in re.split(r"(?<=[。；;！？!?])\s*|\n+|(?<!\d)(?=[1-9][.)）])", text)
        if segment.strip()
    ]


def _compact_fast_answer_value(answer: str, *, query: str, limit: int) -> str:
    text = str(answer or "").strip()
    if len(text) <= limit:
        return text
    normalized_terms = tuple(
        _normalize_match_term(term)
        for term in _fast_answer_query_terms(query)
        if _normalize_match_term(term)
    )
    if not normalized_terms:
        return _clamp_hint_value(text, limit=limit)
    scored: list[tuple[int, int, str]] = []
    for index, segment in enumerate(_fast_answer_snippet_segments(text)):
        normalized_segment = _normalize_match_term(segment)
        matched = {term for term in normalized_terms if term and term in normalized_segment}
        if not matched:
            continue
        scored.append((index, sum(len(term) for term in matched), segment))
    if not scored:
        return _clamp_hint_value(text, limit=limit)
    target_limit = max(240, min(limit, 700))
    selected_indices = {
        index
        for index, _score, _segment in sorted(scored, key=lambda item: (-item[1], item[0]))[:6]
    }
    snippet = "".join(segment for index, _score, segment in scored if index in selected_indices).strip()
    if not snippet:
        return _clamp_hint_value(text, limit=limit)
    return _clamp_hint_value(snippet, limit=target_limit)


def _compact_fast_record_content(
    content: str,
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> str:
    body = str(content or "").strip()
    if not body:
        return body
    max_chars = _dify_fast_content_max_chars()
    fields = _structured_label_values_from_content(body)
    metadata_hint_text = ""
    metadata_fields: dict[str, str] = {}
    if isinstance(metadata, dict) and metadata:
        response_hints = _response_hints_for_metadata(metadata, policy_plugin_refs=policy_plugin_refs)
        metadata_hints = _metadata_answer_highlights(
            metadata,
            response_hints=response_hints,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if metadata_hints:
            metadata_hint_text = "\n".join(metadata_hints)
            metadata_fields = _structured_label_values_from_content(metadata_hint_text)
    if metadata_fields:
        combined_fields = dict(fields)
        combined_fields.update(metadata_fields)
        fields = combined_fields
    labels = _requested_fast_response_labels(query, fields, policy_plugin_refs=policy_plugin_refs)
    if labels:
        if "答案" in labels and fields.get("答案"):
            fields = dict(fields)
            fields["答案"] = _compact_fast_answer_value(fields["答案"], query=query, limit=max_chars)
        lines: list[str] = []
        seen_lines: set[str] = set()

        def add_line(line: str) -> None:
            value = str(line or "").strip()
            if not value or value in seen_lines:
                return
            seen_lines.add(value)
            lines.append(value)

        always_labels = set(_fast_response_always_labels_for_policy_refs(policy_plugin_refs))
        requested_labels = [
            label
            for label in labels
            if label not in always_labels and label not in {"问题", "答案"} and fields.get(label)
        ]
        for prefix in _requested_label_prefixes_for_policy_refs(policy_plugin_refs):
            value = metadata_fields.get(prefix)
            if not value and requested_labels:
                value = "、".join(requested_labels)
            if value:
                add_line(f"{prefix}：{_clamp_hint_value(value, limit=max_chars)}")
        for label in labels:
            if fields.get(label):
                add_line(f"{label}：{_clamp_hint_value(fields[label], limit=max_chars)}")
        compacted = "\n".join(lines).strip()
        if compacted:
            return _clamp_hint_value(compacted, limit=max_chars)
    if metadata_hint_text:
        return _clamp_hint_value(metadata_hint_text, limit=max_chars)
    return _clamp_hint_value(body, limit=max_chars)


def _compact_fast_records_for_response(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total_budget = _dify_fast_total_content_max_chars()
    used_chars = 0
    for record in list(records or [])[: _dify_fast_response_top_k(top_k)]:
        next_record = dict(record)
        metadata = dict(next_record.get("metadata") if isinstance(next_record.get("metadata"), dict) else {})
        original_content = str(next_record.get("content") or "")
        compacted_content = _compact_fast_record_content(
            original_content,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
            metadata=metadata,
        )
        remaining = total_budget - used_chars
        if remaining <= 0:
            break
        budget_trimmed = False
        if len(compacted_content) > remaining:
            if out:
                break
            compacted_content = _clamp_hint_value(compacted_content, limit=remaining)
            budget_trimmed = compacted_content != original_content
        if compacted_content != original_content:
            metadata["dify_fast_compacted"] = True
            metadata["dify_original_content_chars"] = len(original_content)
        if budget_trimmed or used_chars + len(compacted_content) >= total_budget:
            metadata["dify_fast_context_budget_applied"] = True
        metadata["dify_fast_total_context_budget_chars"] = total_budget
        metadata["dify_fast_context_chars"] = len(compacted_content)
        next_record["content"] = compacted_content
        next_record["metadata"] = metadata
        used_chars += len(compacted_content)
        out.append(next_record)
    return out


def _compact_records_for_response(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    mixed_intent_query = _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs)
    if mixed_intent_query:
        exact_anchor_compacted = _compact_mixed_intent_exact_anchor_records(
            list(records or []),
            query=query,
            top_k=top_k,
            policy_plugin_refs=policy_plugin_refs,
        )
        if exact_anchor_compacted:
            strong_question_supplements = [
                record
                for record in _strong_question_anchor_records(
                    list(records or []),
                    query=query,
                    policy_plugin_refs=policy_plugin_refs,
                )
                if record not in exact_anchor_compacted
            ]
            if len(exact_anchor_compacted) == 1 and strong_question_supplements and not _query_has_quoted_anchor_candidate(query):
                exact_anchor_compacted = []
            else:
                return exact_anchor_compacted

    limited = list(records or [])[: max(1, int(top_k or 1))]
    if not limited:
        return []
    if mixed_intent_query:
        return limited
    strong_question_records = _strong_question_anchor_records(
        limited,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if any(record is limited[0] for record in strong_question_records):
        return strong_question_records[: max(1, int(top_k or 1))]
    exact_anchor_answer = _compact_exact_anchor_answer_record(
        limited,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if exact_anchor_answer:
        return exact_anchor_answer
    compaction_enabled = bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_HIGH_CONFIDENCE_ENABLED", True))
    policy_compaction = _response_compaction_for_records(limited, policy_plugin_refs=policy_plugin_refs)
    if compaction_enabled and bool(policy_compaction.get("enabled")):
        if _record_has_strong_question_anchor(
            limited[0],
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ):
            limited = _compact_by_strong_question_anchor(limited, query=query, policy_plugin_refs=policy_plugin_refs)
        else:
            limited = filter_records_by_retrieval_policy_alignment(
                limited,
                query=query,
                plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
                metadata_layers_for_record=_iter_record_metadata_layers,
                policy_resolver=_retrieval_policy_for_plugin_ref,
            )
            limited = _compact_by_strong_question_anchor(limited, query=query, policy_plugin_refs=policy_plugin_refs)
    if not limited:
        return []
    compaction_scores = (
        [_record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs) for record in limited]
        if bool(policy_compaction.get("enabled"))
        else [float(record.get("score") or 0.0) for record in limited]
    )
    compacted = compact_high_confidence_items(
        limited,
        scores=compaction_scores,
        top_k=top_k,
        enabled=compaction_enabled,
        min_top_score=float(
            policy_compaction.get("min_top_score")
            if bool(policy_compaction.get("enabled"))
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE", 0.7)
            or 0.7
        ),
        relative_score_floor=float(
            policy_compaction.get("relative_score_floor")
            if bool(policy_compaction.get("enabled"))
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR", 0.65)
            or 0.65
        ),
        min_items=int(
            policy_compaction.get("min_records")
            if bool(policy_compaction.get("enabled"))
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS", 1)
            or 1
        ),
    )
    return list(compacted)


def _strong_question_anchor_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    return [
        record
        for record in records or []
        if _record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
    ]


def _compact_exact_anchor_answer_record(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    candidates = [
        record
        for record in records or []
        if _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
        and _record_covers_requested_policy_slots(
            record,
            _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs),
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    if not candidates:
        return []
    _sort_records_for_query(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    return [candidates[0]]


def _record_exact_query_anchor_terms(
    record: dict[str, Any],
    *,
    query: str,
    anchor_fields: tuple[str, ...] | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    query_term = _normalize_match_term(query)
    if len(query_term) < 4:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    effective_anchor_fields = anchor_fields or _exact_query_anchor_fields_for_policy_refs(policy_plugin_refs)
    for metadata in _iter_record_metadata_layers(record):
        for field in effective_anchor_fields:
            for term in _metadata_terms(metadata.get(field)):
                normalized = _normalize_match_term(term)
                if len(normalized) < 4 or normalized in seen:
                    continue
                if normalized in query_term:
                    seen.add(normalized)
                    out.append(normalized)
    return tuple(out)


def _record_section_type_values(record: dict[str, Any]) -> tuple[str, ...]:
    return _record_slot_field_values(record, "section_type")


def _record_slot_field_values(record: dict[str, Any], field: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    field_name = str(field or "").strip()
    if not field_name:
        return ()
    for metadata in _iter_record_metadata_layers(record):
        for value in _metadata_terms(metadata.get(field_name)):
            text = str(value or "").strip()
            normalized = _normalize_match_term(text)
            if not text or not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(text)
    if field_name == "section_type":
        for metadata in _iter_record_metadata_layers(record):
            for value in _metadata_terms(metadata.get("section")):
                text = str(value or "").strip()
                normalized = _normalize_match_term(text)
                if not text or not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                out.append(text)
    return tuple(out)


def _record_matches_requested_slot(record: dict[str, Any], requested_slot_specs: tuple[tuple[str, str], ...]) -> bool:
    if not requested_slot_specs:
        return False
    for field, value in requested_slot_specs:
        requested_value = _normalize_match_term(value)
        if not field or not requested_value:
            continue
        record_values = {_normalize_match_term(item) for item in _record_slot_field_values(record, field)}
        record_values.discard("")
        if requested_value in record_values:
            return True
    return False


def _record_has_any_requested_slot_field(
    record: dict[str, Any],
    requested_slot_specs: tuple[tuple[str, str], ...],
) -> bool:
    fields = tuple(dict.fromkeys(field for field, _value in requested_slot_specs if str(field or "").strip()))
    return any(_record_slot_field_values(record, field) for field in fields)


def _record_content_is_answerful(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    content = str(record.get("content") or "").strip()
    return bool(content) and _record_has_answer_evidence(
        record,
        content=content,
        policy_plugin_refs=policy_plugin_refs,
    )


def _record_is_full_answer_chunk(record: dict[str, Any]) -> bool:
    for metadata in _iter_record_metadata_layers(record):
        chunk_kind = str(metadata.get("chunk_kind") or "").strip().lower()
        answer_kind = str(metadata.get("answer_kind") or "").strip().lower()
        if answer_kind in {"full_record", "record_full"}:
            return True
        if chunk_kind in {"full_record", "record_full"}:
            return True
        if chunk_kind.endswith("_full") or chunk_kind.endswith("_record_full"):
            return True
    return False


def _record_is_composite_exact_anchor_answer(record: dict[str, Any]) -> bool:
    return any(
        bool(metadata.get("dify_composite_exact_anchor_slots"))
        for metadata in _iter_record_metadata_layers(record)
    )


def _compact_mixed_intent_exact_anchor_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not records:
        return []
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)

    if requested_slots:
        composite = _composite_record_for_exact_anchor_slots(
            records,
            query=query,
            requested_slot_specs=requested_slots,
            policy_plugin_refs=policy_plugin_refs,
        )
        if composite is not None:
            return [composite]

    if _query_has_quoted_anchor_candidate(query):
        anchored_answer_records = [
            record
            for record in records
            if _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
            and (
                _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
                or _records_have_confident_metadata_anchor([record], query=query, policy_plugin_refs=policy_plugin_refs)
            )
        ]
        if anchored_answer_records:
            return anchored_answer_records[: max(1, int(top_k or 1))]

    has_requested_slot_records = any(_record_has_any_requested_slot_field(record, requested_slots) for record in records)
    if not has_requested_slot_records:
        exact_anchor_answer = _compact_exact_anchor_answer_record(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if exact_anchor_answer:
            return exact_anchor_answer[: max(1, int(top_k or 1))]

    top_record = records[0]
    if has_requested_slot_records:
        return []
    if _record_has_any_requested_slot_field(top_record, requested_slots):
        return []
    if not _record_exact_query_anchor_terms(top_record, query=query, policy_plugin_refs=policy_plugin_refs):
        return []
    if not (
        _record_content_is_answerful(top_record, policy_plugin_refs=policy_plugin_refs)
        or _records_have_confident_metadata_anchor([top_record], query=query, policy_plugin_refs=policy_plugin_refs)
    ):
        return []
    return [top_record][: max(1, int(top_k or 1))]


def _records_have_exact_anchor_full_answer(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
    quoted_anchor_query = _query_has_quoted_anchor_candidate(query)
    for record in records or []:
        if not _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs):
            continue
        if _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs):
            if requested_slots and not (
                quoted_anchor_query
                or _record_is_full_answer_chunk(record)
                or _record_is_composite_exact_anchor_answer(record)
            ):
                continue
            return True
    return False


def _composite_record_for_exact_anchor_slots(
    records: list[dict[str, Any]],
    *,
    query: str,
    requested_slot_specs: tuple[tuple[str, str], ...],
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not _record_matches_requested_slot(record, requested_slot_specs):
            continue
        for anchor in _record_exact_query_anchor_terms(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ):
            groups.setdefault(anchor, []).append(record)

    best_records: list[dict[str, Any]] = []
    best_covered: set[tuple[str, str]] = set()
    requested_norms = tuple(
        (field, _normalize_match_term(value))
        for field, value in requested_slot_specs
        if field and _normalize_match_term(value)
    )
    for candidates in groups.values():
        selected: list[dict[str, Any]] = []
        covered: set[tuple[str, str]] = set()
        seen_records: set[int] = set()
        for requested_field, requested_norm in requested_norms:
            requested_key = (requested_field, requested_norm)
            if not requested_norm or requested_key in covered:
                continue
            matching_records = [
                record
                for record in candidates
                if requested_norm in {
                    _normalize_match_term(value)
                    for value in _record_slot_field_values(record, requested_field)
                }
                and id(record) not in seen_records
            ]
            if not matching_records:
                continue
            for record in _ordered_section_sibling_records(matching_records):
                if id(record) in seen_records:
                    continue
                selected.append(record)
                seen_records.add(id(record))
            covered.add(requested_key)
        if len(covered) > len(best_covered):
            best_records = selected
            best_covered = covered

    if len(best_records) < 2:
        return None

    first = best_records[0]
    metadata = dict(first.get("metadata") if isinstance(first.get("metadata"), dict) else {})
    source_chunk_ids: list[str] = []
    source_document_ids: list[str] = []
    for record in best_records:
        record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        chunk_id = str(record_metadata.get("chunk_id") or "").strip()
        document_id = str(record_metadata.get("document_id") or "").strip()
        if chunk_id and chunk_id not in source_chunk_ids:
            source_chunk_ids.append(chunk_id)
        if document_id and document_id not in source_document_ids:
            source_document_ids.append(document_id)
    covered_specs = [
        {"metadata": field, "value": value}
        for field, value in requested_slot_specs
        if (field, _normalize_match_term(value)) in best_covered
    ]
    composite_metadata = {
        "dify_composite_exact_anchor_slots": True,
        "dify_composite_slot_specs": covered_specs,
        "dify_composite_source_chunk_ids": source_chunk_ids,
        "dify_composite_source_document_ids": source_document_ids,
    }
    section_types = [spec["value"] for spec in covered_specs if spec.get("metadata") == "section_type"]
    if section_types:
        composite_metadata["section_type"] = "composite"
        composite_metadata["dify_composite_section_types"] = section_types
    metadata.update(composite_metadata)
    score = min(1.0, max((float(record.get("score") or 0.0) for record in best_records), default=0.0) + 0.01)
    content_parts = [
        part
        for part in (
            _composite_stitched_section_text(best_records),
            "\n\n".join(str(record.get("content") or "").strip() for record in best_records if record.get("content")),
        )
        if part
    ]
    content = "\n\n".join(content_parts)
    return {
        "content": content,
        "score": score,
        "title": str(first.get("title") or "composite-anchor-evidence"),
        "metadata": metadata,
    }


def _composite_stitched_section_text(records: list[dict[str, Any]]) -> str:
    section_texts = [
        text
        for text in (_composite_section_text(record) for record in records or [])
        if text
    ]
    if not section_texts:
        return ""
    return "合并章节原文：\n" + "\n".join(section_texts)


def _composite_section_text(record: dict[str, Any]) -> str:
    content = str(record.get("content") or "").strip()
    if not content:
        return ""
    source_text = content.split("原始证据：", 1)[-1].strip() if "原始证据：" in content else content
    lines = [line.strip() for line in source_text.splitlines() if line.strip()]
    if not lines:
        return ""
    for index, line in enumerate(lines):
        if not line.startswith("章节："):
            continue
        label = line.split("：", 1)[1].strip() or line
        body = lines[index + 1 :]
        return "\n".join([label, *body]).strip()
    return "\n".join(lines).strip()


def _ordered_section_sibling_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sequence_key(record: dict[str, Any]) -> tuple[str, str, int, int, int, float]:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_record_id = str(metadata.get("source_record_id") or "").strip()
        section_type = str(metadata.get("section_type") or "").strip()
        return (
            source_record_id,
            section_type,
            _safe_int(metadata.get("source_chunk_index"), default=1_000_000),
            _safe_int(metadata.get("chunk_part_index"), default=1_000_000),
            _safe_int(metadata.get("chunk_index"), default=1_000_000),
            -float(record.get("score") or 0.0),
        )

    return sorted(records, key=sequence_key)


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _record_answerfulness_score(record: dict[str, Any], *, policy_plugin_refs: tuple[str, ...] = ()) -> float:
    content = str(record.get("content") or "").strip()
    if not content:
        return 0.0
    if _record_has_answer_evidence(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return _ANSWERFUL_RECORD_BONUS
    if _record_is_anchor_only_qa(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return -_ANCHOR_ONLY_QA_RECORD_PENALTY
    return 0.0


def _record_has_answer_evidence(
    record: dict[str, Any],
    *,
    content: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    response_hints = _response_hints_for_record(record, policy_plugin_refs=policy_plugin_refs)
    fields = _structured_fields_from_content(content, response_hints=response_hints)
    answer_labels = _response_hint_string_list(response_hints, "answer_labels")
    if answer_labels and any(fields.get(label) for label in answer_labels):
        return True
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    if _matching_response_hint_group(fields, metadata, response_hints=response_hints) is not None:
        return True
    answer_keywords = _response_hint_string_list(response_hints, "answer_keywords")
    if _content_starts_with_response_hint(content, response_hints=response_hints) and (
        not answer_keywords or any(keyword in content[:_MAX_QA_HINT_VALUE_CHARS] for keyword in answer_keywords)
    ):
        return True

    raw_metadata = record.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    if _metadata_answer_highlights(metadata, response_hints=response_hints):
        return True
    return False


def _record_is_anchor_only_qa(
    record: dict[str, Any],
    *,
    content: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    response_hints = _response_hints_for_record(record, policy_plugin_refs=policy_plugin_refs)
    normalized = str(content or "").strip()
    answer_labels = _response_hint_string_list(response_hints, "answer_labels")
    answer_keywords = _response_hint_string_list(response_hints, "answer_keywords")
    if any(label and label in normalized for label in (*answer_labels, *answer_keywords)):
        return False
    chunk_kinds = set(_response_hint_string_list(response_hints, "anchor_only_chunk_kinds"))
    if not chunk_kinds:
        return False
    is_qa_record = any(
        str(metadata.get("chunk_kind") or "").strip() in chunk_kinds for metadata in _iter_record_metadata_layers(record)
    )
    if not is_qa_record:
        return False
    markers = _response_hint_string_list(response_hints, "anchor_only_markers")
    return any(marker and marker in normalized for marker in markers)


def _query_intent_terms(query: str, *, intent_terms: tuple[str, ...]) -> tuple[str, ...]:
    query_term = _normalize_match_term(query)
    if not query_term:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for term in intent_terms:
        normalized = _normalize_match_term(term)
        if normalized and normalized in query_term and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


def _record_question_intent_terms(record: dict[str, Any], *, policy_plugin_refs: tuple[str, ...] = ()) -> tuple[str, ...]:
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    if not plugin_ref:
        return ()
    policy = _retrieval_policy_for_plugin_ref(plugin_ref)
    return _response_hint_string_list(policy, "question_intent_terms")


def _record_question_anchor_bonus_value(
    record: dict[str, Any],
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    plugin_ref = _record_plugin_ref(record, fallback_plugin_refs=policy_plugin_refs)
    if not plugin_ref:
        return _QUESTION_INTENT_MATCH_BONUS
    policy = _retrieval_policy_for_plugin_ref(plugin_ref)
    try:
        value = float(policy.get("question_anchor_bonus"))
    except (TypeError, ValueError):
        return _QUESTION_INTENT_MATCH_BONUS
    return max(0.0, min(2.0, value))


_QUESTION_ANCHOR_INTENT_GROUPS = (
    ("application", ("申请", "申报", "办理", "申领", "领取", "怎么领", "怎么申请", "如何申请", "流程", "步骤")),
    ("amount", ("怎么算", "计算", "多少钱", "多少", "补贴多少", "标准", "金额")),
    ("timing", ("多久", "多久到账", "何时", "什么时候", "时间", "进度")),
)
_QUESTION_ANCHOR_SUBJECT_NOISE_TERMS = (
    "办理",
    "办",
    "事项",
    "这个事项",
    "这个",
    "请问",
    "可以",
    "能否",
    "是否",
    "怎么",
    "如何",
    "是什么",
    "什么",
    "帮我",
    "直接说清楚",
    "麻烦查一下",
    "麻烦帮我查一下",
    "主要想确认",
)
def _question_anchor_intent_groups(text: str) -> set[str]:
    normalized = _normalize_match_term(text)
    if not normalized:
        return set()
    groups: set[str] = set()
    for group, terms in _QUESTION_ANCHOR_INTENT_GROUPS:
        if any((term_text := _normalize_match_term(term)) and term_text in normalized for term in terms):
            groups.add(group)
    return groups


def _record_question_anchor_has_intent_conflict(
    record: dict[str, Any],
    *,
    query: str,
    anchor_fields: tuple[str, ...],
) -> bool:
    query_groups = _question_anchor_intent_groups(query)
    if not query_groups:
        return False
    matching_groups: set[str] = set()
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            for anchor_value in _metadata_terms(metadata.get(field)):
                candidate_groups = _question_anchor_intent_groups(anchor_value)
                if candidate_groups:
                    matching_groups.update(candidate_groups)
    return bool(matching_groups and not query_groups.intersection(matching_groups))


def _record_question_anchor_lacks_specific_query_subject(
    record: dict[str, Any],
    *,
    query: str,
    anchor_fields: tuple[str, ...],
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if not _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs):
        return False
    generic_terms = {
        _normalize_match_term(term)
        for term in _question_anchor_generic_subject_terms_for_policy_refs(policy_plugin_refs)
    }
    query_subject_terms: list[str] = []
    seen_terms: set[str] = set()
    for term in _metadata_anchor_title_query_terms(query, policy_plugin_refs=policy_plugin_refs):
        normalized = _normalize_match_term(term)
        if len(normalized) < 4 or normalized in seen_terms or normalized in generic_terms:
            continue
        seen_terms.add(normalized)
        query_subject_terms.append(normalized)
    if not query_subject_terms:
        return False

    record_subject_parts: list[str] = []
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            record_subject_parts.extend(_normalize_match_term(value) for value in _metadata_terms(metadata.get(field)))
    record_subject = "\n".join(part for part in record_subject_parts if part)
    if not record_subject:
        return False
    return not any(term in record_subject for term in query_subject_terms)


def _question_anchor_subject_text(value: str, *, intent_terms: tuple[str, ...]) -> str:
    text = _normalize_match_term(value)
    if not text:
        return ""
    noise_terms = [
        *(_normalize_match_term(term) for term in intent_terms),
        *(_normalize_match_term(term) for term in _QUESTION_ANCHOR_SUBJECT_NOISE_TERMS),
    ]
    for term in sorted((term for term in noise_terms if term), key=len, reverse=True):
        text = text.replace(term, "")
    return text


def _record_question_intent_bonus(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    primary_anchor_fields = ("question", "primary_alias")
    if _record_question_anchor_strength(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        anchor_fields=primary_anchor_fields,
    ) >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH and not _record_question_anchor_has_intent_conflict(
        record,
        query=query,
        anchor_fields=primary_anchor_fields,
    ) and not _record_question_anchor_lacks_specific_query_subject(
        record,
        query=query,
        anchor_fields=primary_anchor_fields,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _record_question_anchor_bonus_value(record, policy_plugin_refs=policy_plugin_refs)
    if _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs) or _query_intent_terms(
        query,
        intent_terms=_record_question_intent_terms(record, policy_plugin_refs=policy_plugin_refs),
    ):
        return 0.0
    alias_anchor_fields = ("aliases",)
    if _record_question_anchor_strength(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
        anchor_fields=alias_anchor_fields,
    ) >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH and not _record_question_anchor_has_intent_conflict(
        record,
        query=query,
        anchor_fields=alias_anchor_fields,
    ) and not _record_question_anchor_lacks_specific_query_subject(
        record,
        query=query,
        anchor_fields=alias_anchor_fields,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _record_question_anchor_bonus_value(record, policy_plugin_refs=policy_plugin_refs)
    return 0.0


def _record_question_anchor_strength(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
    anchor_fields: tuple[str, ...] = ("question", "primary_alias", "aliases"),
) -> float:
    query_term = _normalize_match_term(query)
    if len(query_term) < 4:
        return 0.0
    intent_terms = _query_intent_terms(
        query,
        intent_terms=_record_question_intent_terms(record, policy_plugin_refs=policy_plugin_refs),
    )
    best = 0.0
    for metadata in _iter_record_metadata_layers(record):
        for field in anchor_fields:
            for anchor_value in _metadata_terms(metadata.get(field)):
                candidate = _normalize_match_term(anchor_value)
                if len(candidate) < 3:
                    continue
                if candidate == query_term or candidate in query_term or query_term in candidate:
                    best = max(best, 1.0)
                    continue
                if _near_question_anchor_match(query_term, candidate):
                    best = max(best, 0.9)
                    continue
                lcs = _longest_common_substring_length(query_term, candidate)
                lcs_ratio = lcs / max(1, min(len(query_term), len(candidate)))
                if field == "aliases" and lcs >= 6 and lcs_ratio >= 0.68:
                    best = max(best, 0.86)
                    continue
                if (
                    _cjk_bigram_overlap_count(query_term, candidate) >= _QUESTION_ANCHOR_BIGRAM_MIN_OVERLAP
                    and _cjk_bigram_overlap_ratio(query_term, candidate) >= _QUESTION_ANCHOR_BIGRAM_MIN_RATIO
                ):
                    overlap_count = _cjk_bigram_overlap_count(query_term, candidate)
                    overlap_ratio = _cjk_bigram_overlap_ratio(query_term, candidate)
                    marker_bonus = _question_marker_overlap_bonus(query_term, candidate)
                    strength = 0.66 + min(0.09, overlap_ratio * 0.09) + min(0.07, lcs_ratio * 0.07) + marker_bonus
                    if overlap_count >= 8 and overlap_ratio >= 0.7:
                        strength = max(strength, 0.82)
                    best = max(best, min(0.96, strength))
                    continue
                if intent_terms and any(term in candidate for term in intent_terms):
                    overlap = _longest_common_substring_length(
                        _question_anchor_subject_text(query_term, intent_terms=intent_terms),
                        _question_anchor_subject_text(candidate, intent_terms=intent_terms),
                    )
                    if overlap >= _MIN_QUERY_INTENT_SUBJECT_OVERLAP_CHARS:
                        best = max(best, 0.8)
    return best


def _record_has_strong_question_anchor(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    return bool(
        _record_question_anchor_strength(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH
        and not _record_question_anchor_has_intent_conflict(
            record,
            query=query,
            anchor_fields=("question", "primary_alias"),
        )
    )


def _compact_by_strong_question_anchor(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not records:
        return []
    if not _record_has_strong_question_anchor(
        records[0],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return records
    anchored = [
        record
        for record in records
        if _record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    return anchored or records


def _records_can_skip_kg_on_demand(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_prefers_service_anchor(query, policy_plugin_refs=policy_plugin_refs):
        return _records_have_confident_metadata_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ) or _records_meet_primary_scope(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    if _query_prefers_question_anchor(query, policy_plugin_refs=policy_plugin_refs) and not _query_prefers_service_anchor(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _records_have_strong_question_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    return _records_have_confident_metadata_anchor(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _load_dify_kg_chunk_rows(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    return (
        db.query(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id.label("document_id"),
            DocumentChunk.chunk_index.label("chunk_index"),
            DocumentChunk.page_number.label("page_number"),
            DocumentChunk.content.label("content"),
            DocumentChunk.doc_metadata.label("metadata"),
            Document.dataset_id.label("dataset_id"),
            Document.filename.label("filename"),
        )
        .join(Document, DocumentChunk.document_id == Document.id)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.id.in_(chunk_ids),
            DocumentChunk.disabled_at.is_(None),
            Document.tenant_id == tenant_id,
            Document.dataset_id.in_(dataset_ids),
            Document.disabled_at.is_(None),
        )
        .all()
    )


def _load_dify_kg_chunk_rows_with_managed_session(
    *,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    worker_db = SessionLocal()
    try:
        return _load_dify_kg_chunk_rows(
            db=worker_db,
            tenant_id=tenant_id,
            dataset_ids=dataset_ids,
            chunk_ids=chunk_ids,
        )
    finally:
        worker_db.close()


async def _offload_dify_kg_chunk_rows(
    *,
    request_db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    chunk_ids: list[UUID],
) -> list[Any]:
    rollback = getattr(request_db, "rollback", None)
    if callable(rollback):
        with contextlib.suppress(Exception):
            rollback()
    return await run_blocking_retrieval_call(
        _load_dify_kg_chunk_rows_with_managed_session,
        tenant_id=tenant_id,
        dataset_ids=dataset_ids,
        chunk_ids=chunk_ids,
    )


async def _dify_kg_on_demand_records(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    requested_kg_flags: _DifyKGFlags,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    if not requested_kg_flags.enabled:
        return []
    if not (bool(getattr(settings, "KG_ENABLED", False)) and bool(getattr(settings, "KG_CHAT_ENABLED", False))):
        return []
    scoped_dataset_ids = _dedupe_dataset_ids(list(dataset_ids or []))
    if not scoped_dataset_ids:
        return []

    try:
        from app.rag.kg.pipeline import kg_search

        kg_result = await kg_search(
            query=query,
            tenant_id=tenant_id,
            dataset_ids=scoped_dataset_ids,
            account_id=account_id,
        )
    except Exception:
        logger.debug("Dify KG on-demand search failed", exc_info=True)
        return []

    events = kg_result.get("events") if isinstance(kg_result, dict) else []
    events = events if isinstance(events, list) else []
    if not events:
        return []

    max_records = max(
        int(requested_kg_flags.chunk_injection_max_chunks if requested_kg_flags.enable_chunk_injection else 0),
        int(requested_kg_flags.chunk_boost_max_promoted if requested_kg_flags.enable_chunk_boost else 0),
        1,
    )
    chunk_events: list[tuple[UUID, dict[str, Any]]] = []
    seen_chunk_ids: set[UUID] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_chunk_id = str(event.get("chunk_id") or "").strip()
        if not raw_chunk_id:
            continue
        try:
            chunk_id = UUID(raw_chunk_id)
        except ValueError:
            continue
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        chunk_events.append((chunk_id, event))
        if len(chunk_events) >= max_records:
            break
    if not chunk_events:
        return []

    event_by_chunk_id = {chunk_id: event for chunk_id, event in chunk_events}
    try:
        rows = await _offload_dify_kg_chunk_rows(
            request_db=db,
            tenant_id=tenant_id,
            dataset_ids=scoped_dataset_ids,
            chunk_ids=list(event_by_chunk_id),
        )
    except Exception:
        logger.debug("Dify KG on-demand chunk hydration failed", exc_info=True)
        return []

    row_by_chunk_id = {UUID(str(_row_value(row, "chunk_id"))): row for row in rows}
    records: list[dict[str, Any]] = []
    for chunk_id, event in chunk_events:
        row = row_by_chunk_id.get(chunk_id)
        if row is None:
            continue
        metadata = _row_value(row, "metadata") or {}
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata.update(
            {
                "kg_on_demand": True,
                "kg_event_id": str(event.get("id") or event.get("event_id") or ""),
                "kg_score": _clamp_score(event.get("score") or event.get("weight") or event.get("relevance_score")),
                "chunk_id": str(chunk_id),
                "document_id": str(_row_value(row, "document_id") or ""),
                "chunk_index": _row_value(row, "chunk_index"),
                "page_number": _row_value(row, "page_number"),
            }
        )
        citation = {
            "content": str(_row_value(row, "content") or ""),
            "relevance_score": metadata["kg_score"],
            "document_name": str(_row_value(row, "filename") or "kg-on-demand"),
            "chunk_id": str(chunk_id),
            "dataset_id": str(_row_value(row, "dataset_id") or ""),
            "metadata": metadata,
        }
        record = _citation_to_dify_record(
            citation,
            dataset_id=_row_value(row, "dataset_id"),
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if str(record.get("content") or "").strip():
            records.append(record)
    return records


def _dify_kg_bool(name: str, default: bool) -> bool:
    return bool(getattr(settings, name, default))


def _dify_kg_int(name: str, default: int, *, minimum: int = 0, maximum: int = 50) -> int:
    try:
        value = int(getattr(settings, name, default) or 0)
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), min(int(maximum), int(value)))


def _dify_kg_float(name: str, default: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        value = float(getattr(settings, name, default) or 0.0)
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(float(maximum), float(value)))


def _record_dedupe_key(record: dict[str, Any]) -> tuple[str, str, str]:
    source_identity = _record_source_identity_key(record)
    if source_identity:
        return ("source_record", source_identity, "")

    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    chunk_id = str(metadata.get("chunk_id") or "").strip()
    document_id = str(metadata.get("document_id") or "").strip()
    content = str(record.get("content") or "").strip()
    title = str(record.get("title") or "").strip()
    return (chunk_id, document_id, content or title)


def _record_source_identity_key(record: dict[str, Any]) -> str:
    for metadata in _iter_record_metadata_layers(record):
        identity = metadata.get("_record_identity")
        if isinstance(identity, dict):
            key = str(identity.get("key") or "").strip()
            if key:
                return key

    for metadata in _iter_record_metadata_layers(record):
        source_record_id = ""
        for key in _SOURCE_RECORD_ID_KEYS:
            source_record_id = str(metadata.get(key) or "").strip()
            if source_record_id:
                break
        if not source_record_id:
            continue
        scope_parts: list[str] = []
        for key in _SOURCE_RECORD_SCOPE_KEYS:
            value = str(metadata.get(key) or "").strip()
            if value:
                scope_parts.append(f"{key}={value}")
        scope = "|".join(scope_parts)
        return f"{scope}|source_record_id={source_record_id}" if scope else f"source_record_id={source_record_id}"
    return ""


def _dedupe_records(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in records:
        key = _record_dedupe_key(record)
        if not any(key):
            continue
        current = best_by_key.get(key)
        if current is None or _record_rank_score(
            record, query=query, policy_plugin_refs=policy_plugin_refs
        ) > _record_rank_score(current, query=query, policy_plugin_refs=policy_plugin_refs):
            best_by_key[key] = record
    return list(best_by_key.values())


def _records_meet_primary_scope(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    min_records = max(1, int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS", 1) or 1))
    if len(records) < min_records:
        return False
    min_top_score = float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE", 0.45) or 0.0)
    if min_top_score <= 0:
        return True
    top_score = max(
        (_record_rank_score(record, query=query, policy_plugin_refs=policy_plugin_refs) for record in records),
        default=0.0,
    )
    return top_score >= min_top_score


def _citation_needs_slot_content_hydration(
    citation: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    content = _first_non_empty(citation, _CONTENT_KEYS)
    if not content:
        return True
    if "..." not in content and "…" not in content:
        return False
    requested_slots = _requested_policy_slot_specs_for_query(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if not requested_slots:
        return False
    record = {
        "content": content,
        "title": _first_non_empty(citation, _TITLE_KEYS),
        "metadata": dict(citation.get("metadata") or {}) if isinstance(citation.get("metadata"), dict) else {},
    }
    return _record_matches_requested_slot(record, requested_slots)


def _records_from_citations(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
    hydration_query: str | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
    hydrated_chunk_content_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    slot_hydration_query = hydration_query or query
    citations_needing_hydration = [
        citation
        for citation in citations or []
        if _citation_needs_slot_content_hydration(
            citation,
            query=slot_hydration_query,
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    if hydrated_chunk_content_map is None:
        chunk_content_map = (
            _load_chunk_content_map(db=db, tenant_id=tenant_id, citations=citations_needing_hydration)
            if citations_needing_hydration
            else {}
        )
    else:
        chunk_content_map = hydrated_chunk_content_map
    records: list[dict[str, Any]] = []
    for citation in citations:
        chunk_id = _citation_chunk_id(citation)
        if chunk_id and chunk_content_map.get(chunk_id) and citation in citations_needing_hydration:
            citation = {**citation, "content": chunk_content_map[chunk_id]}
        record = _citation_to_dify_record(
            citation,
            dataset_id=fallback_dataset_id,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if str(record.get("content") or "").strip():
            records.append(record)
    return records


async def _records_from_citations_with_managed_hydration(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
    hydration_query: str | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    slot_hydration_query = hydration_query or query
    citations_needing_hydration = [
        citation
        for citation in citations or []
        if _citation_needs_slot_content_hydration(
            citation,
            query=slot_hydration_query,
            policy_plugin_refs=policy_plugin_refs,
        )
    ]
    chunk_content_map: dict[str, str] = {}
    if citations_needing_hydration:
        try:
            chunk_content_map = await _offload_chunk_content_hydration(
                request_db=db,
                tenant_id=tenant_id,
                citations=citations_needing_hydration,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to hydrate Dify chunk content; falling back to citation snippets", exc_info=True)

    return _records_from_citations(
        db=db,
        tenant_id=tenant_id,
        citations=citations,
        fallback_dataset_id=fallback_dataset_id,
        query=query,
        hydration_query=hydration_query,
        policy_plugin_refs=policy_plugin_refs,
        hydrated_chunk_content_map=chunk_content_map,
    )


def _tag_mixed_intent_records(records: list[dict[str, Any]], *, subquery: str) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for record in records:
        metadata = dict(record.get("metadata") if isinstance(record.get("metadata"), dict) else {})
        metadata["dify_mixed_intent_subquery"] = subquery
        tagged.append({**record, "metadata": metadata})
    return tagged


def _citation_to_dify_record(
    citation: dict[str, Any],
    *,
    dataset_id: UUID | None,
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    content = _first_non_empty(citation, _CONTENT_KEYS)
    title = _first_non_empty(citation, _TITLE_KEYS) or "Untitled"

    raw_metadata = citation.get("metadata")
    metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    resolved_dataset_id = _citation_dataset_id(citation, fallback_dataset_id=dataset_id)
    if resolved_dataset_id is not None:
        metadata["dataset_id"] = str(resolved_dataset_id)
    for key in _METADATA_KEYS:
        value = citation.get(key)
        if value is not None and value != "":
            metadata[key] = value
    content = _content_with_answer_hints(content, metadata, query=query, policy_plugin_refs=policy_plugin_refs)

    return {
        "content": content,
        "score": _citation_score(citation),
        "title": title,
        "metadata": metadata,
    }


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(key, default)
    return getattr(row, key, default)


def _coerce_uuid_text(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return ""


def _records_have_strong_question_anchor(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    return any(
        _record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        and _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs)
        for record in records or []
    )


def _records_have_confident_metadata_anchor(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    for record in records or []:
        if _record_metadata_anchor_bonus(record, query=query) >= 0.1:
            return True
        if not _record_content_is_answerful(record, policy_plugin_refs=policy_plugin_refs):
            continue
        if _record_has_strong_question_anchor(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        ):
            return True
    return False


def _records_can_skip_metadata_anchor_fallback(
    records: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_has_specific_service_anchor_candidate(query, policy_plugin_refs=policy_plugin_refs):
        return any(
            _record_exact_query_anchor_terms(record, query=query, policy_plugin_refs=policy_plugin_refs)
            and _records_have_confident_metadata_anchor([record], query=query, policy_plugin_refs=policy_plugin_refs)
            for record in records or []
        )
    if _query_prefers_question_anchor(query, policy_plugin_refs=policy_plugin_refs) and not _query_prefers_service_anchor(
        query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return _records_have_strong_question_anchor(
            records,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
    return _records_have_confident_metadata_anchor(
        records,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _metadata_anchor_fallback_query_terms(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        term = str(raw or "").strip()
        normalized = _normalize_match_term(term)
        if len(normalized) < 4 or normalized in seen:
            return
        seen.add(normalized)
        terms.append(term)

    for segment in _iter_anchor_word_segments(text):
        add(segment)
        if not _contains_cjk(segment):
            continue
        for start in range(0, len(segment)):
            for size in (6, 4):
                if start + size > len(segment):
                    continue
                add(segment[start : start + size])
                if len(terms) >= _METADATA_ANCHOR_DB_FALLBACK_MAX_QUERY_TERMS:
                    return terms
    return terms[:_METADATA_ANCHOR_DB_FALLBACK_MAX_QUERY_TERMS]


def _strip_service_anchor_query_noise(
    query: str,
    *,
    noise_terms: tuple[str, ...] = (),
    leading_noise_terms: tuple[str, ...] = (),
    cutoff_terms: tuple[str, ...] = (),
    admin_aliases: tuple[str, ...] = (),
) -> str:
    text = str(query or "").strip()
    if not text:
        return ""
    for phrase in sorted((str(term or "").strip() for term in leading_noise_terms), key=len, reverse=True):
        if not phrase:
            continue
        if text.startswith(phrase):
            text = text[len(phrase) :].strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
            break
    declared_admin_aliases = tuple(
        sorted(
            {str(alias or "").strip() for alias in admin_aliases if str(alias or "").strip()},
            key=len,
            reverse=True,
        )
    )
    for _ in range(2):
        prefix = next((alias for alias in declared_admin_aliases if text.startswith(alias)), None)
        if prefix is None:
            break
        text = text[len(prefix) :].strip(_SERVICE_ANCHOR_QUERY_TRAILING_CHARS)
    cutoff_indexes = [
        index
        for marker in sorted((str(term or "").strip() for term in cutoff_terms), key=len, reverse=True)
        if marker and (index := text.find(marker)) > 0
    ]
    if cutoff_indexes:
        text = text[: min(cutoff_indexes)].strip()
    for phrase in sorted((str(term or "").strip() for term in noise_terms), key=len, reverse=True):
        if not phrase:
            continue
        text = text.replace(phrase, "")
    text = _rstrip_service_anchor_query_noise(text)
    previous = None
    while previous != text:
        previous = text
        text = _strip_trailing_service_anchor_admin(
            text,
            admin_aliases=declared_admin_aliases,
        )
        text = _rstrip_service_anchor_query_noise(text)
    return text


def _service_anchor_query_noise_variants(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> tuple[str, ...]:
    common_kwargs = {
        "noise_terms": _service_anchor_noise_terms_for_policy_refs(policy_plugin_refs),
        "leading_noise_terms": _service_anchor_leading_noise_terms_for_policy_refs(policy_plugin_refs),
        "cutoff_terms": _service_anchor_cutoff_terms_for_policy_refs(policy_plugin_refs),
    }
    candidates = (
        _strip_service_anchor_query_noise(query, **common_kwargs),
        _strip_service_anchor_query_noise(
            query,
            **common_kwargs,
            admin_aliases=_service_anchor_admin_aliases_for_policy_refs(policy_plugin_refs),
        ),
    )
    variants: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_match_term(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        variants.append(candidate)
    return tuple(variants)


def _metadata_anchor_service_name_query_terms(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    cleaned_variants = _service_anchor_query_noise_variants(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if not cleaned_variants:
        return []

    terms: list[str] = []
    seen: set[str] = set()
    seen_text: set[str] = set()

    def add(raw: str) -> None:
        term = str(raw or "").strip()
        normalized = _normalize_match_term(term)
        text_key = term.casefold()
        if len(normalized) < 4 or normalized in seen or text_key in seen_text:
            return
        seen.add(normalized)
        seen_text.add(text_key)
        terms.append(term)

    for match in _QUOTED_ANCHOR_RE.finditer(str(query or "")):
        literal = _quoted_anchor_match_text(match)
        normalized = _normalize_match_term(literal)
        text_key = literal.casefold()
        if len(normalized) >= 4 and text_key not in seen_text:
            seen_text.add(text_key)
            terms.append(literal)
    for quoted_anchor in _quoted_query_anchor_terms(query):
        add(quoted_anchor)
    for cleaned in cleaned_variants:
        add(cleaned)
    for rewritten in _service_anchor_query_rewrite_terms_for_policy_refs(query, policy_plugin_refs):
        add(rewritten)
    for cleaned in cleaned_variants:
        for segment in _iter_anchor_word_segments(cleaned):
            add(segment)
            if not _contains_cjk(segment):
                continue
            for size in (12, 10, 8, 6, 4):
                if len(segment) < size:
                    continue
                for start in range(0, len(segment) - size + 1):
                    add(segment[start : start + size])
                    if len(terms) >= _METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS:
                        return terms
    return terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]


def _query_has_specific_service_anchor_candidate(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    for term in _metadata_anchor_service_name_query_terms(query, policy_plugin_refs=policy_plugin_refs)[:3]:
        normalized = _normalize_match_term(term)
        if not _CJK_RE.search(normalized):
            continue
        if len(normalized) < _MIN_SPECIFIC_INTENT_CHARS or len(normalized) > 30:
            continue
        entity_terms = tuple(
            _normalize_match_term(term)
            for term in _service_anchor_entity_terms_for_policy_refs(policy_plugin_refs)
            if _normalize_match_term(term)
        )
        if entity_terms and any(marker in normalized for marker in entity_terms):
            return True
    return False


def _query_has_specific_fast_metadata_anchor_candidate(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> bool:
    if _query_has_specific_service_anchor_candidate(query, policy_plugin_refs=policy_plugin_refs):
        return True
    if not _query_has_quoted_anchor_candidate(query):
        return False
    for term in _quoted_query_anchor_terms(query):
        normalized = _normalize_match_term(term)
        if not _CJK_RE.search(normalized):
            continue
        if _MIN_SPECIFIC_INTENT_CHARS <= len(normalized) <= 50:
            return True
    return False


def _metadata_anchor_title_query_terms(
    query: str,
    *,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[str]:
    cleaned_variants = _service_anchor_query_noise_variants(
        query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if not cleaned_variants:
        return []

    terms: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        term = str(raw or "").strip()
        normalized = _normalize_match_term(term)
        min_chars = 3 if _contains_cjk(normalized) else 4
        if len(normalized) < min_chars or normalized in seen:
            return
        seen.add(normalized)
        terms.append(term)

    for cleaned in cleaned_variants:
        add(cleaned)
    for cleaned in cleaned_variants:
        for segment in _iter_anchor_word_segments(cleaned):
            add(segment)
            if not _contains_cjk(segment):
                continue
            for size in (8, 6, 4, 3):
                if len(segment) < size:
                    continue
                for start in range(0, len(segment) - size + 1):
                    add(segment[start : start + size])
                    if len(terms) >= _METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS:
                        return terms
    return terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]


def _metadata_anchor_fallback_record_score(
    record: dict[str, Any],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...] = (),
) -> float:
    content = str(record.get("content") or "").strip()
    if content and _record_is_anchor_only_qa(record, content=content, policy_plugin_refs=policy_plugin_refs):
        return 0.0
    question_strength = _record_question_anchor_strength(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    anchor_bonus = _record_metadata_anchor_bonus(record, query=query)
    intent_bonus = _record_intent_bonus(record, query=query, policy_plugin_refs=policy_plugin_refs)
    policy_bonus = record_retrieval_policy_bonus(
        record,
        query=query,
        plugin_ref_for_record=lambda item: _record_plugin_ref(item, fallback_plugin_refs=policy_plugin_refs),
        metadata_layers_for_record=_iter_record_metadata_layers,
        policy_resolver=_retrieval_policy_for_plugin_ref,
    )
    has_strong_question_anchor = _record_has_strong_question_anchor(
        record,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )
    if question_strength >= _QUESTION_ANCHOR_COMPACTION_MIN_STRENGTH and not has_strong_question_anchor:
        return 0.0
    if has_strong_question_anchor:
        base = 0.86 + min(0.1, question_strength * 0.1)
    elif anchor_bonus >= 0.08:
        base = _METADATA_ANCHOR_DB_FALLBACK_DEFAULT_SCORE
    else:
        return 0.0
    score = base + max(0.0, anchor_bonus) + max(0.0, intent_bonus) + max(0.0, policy_bonus)
    return round(min(0.99, max(_METADATA_ANCHOR_DB_FALLBACK_MIN_SCORE, score)), 6)


def _metadata_anchor_fallback_records_from_rows(
    rows: list[Any] | tuple[Any, ...],
    *,
    dataset_ids: list[UUID] | tuple[UUID, ...],
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    existing_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if _records_can_skip_metadata_anchor_fallback(
        existing_records or [],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return []

    scoped_dataset_ids = {_coerce_uuid_text(dataset_id) for dataset_id in dataset_ids or []}
    scoped_dataset_ids.discard("")
    if not scoped_dataset_ids:
        return []

    candidates: list[dict[str, Any]] = []
    for row in rows or ():
        dataset_id = _coerce_uuid_text(_row_value(row, "dataset_id"))
        if dataset_id not in scoped_dataset_ids:
            continue
        content = str(_row_value(row, "content") or "").strip()
        if not content:
            continue
        raw_metadata = _row_value(row, "metadata")
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        chunk_id = _coerce_uuid_text(_row_value(row, "chunk_id") or _row_value(row, "id"))
        document_id = _coerce_uuid_text(_row_value(row, "document_id"))
        if chunk_id:
            metadata["chunk_id"] = chunk_id
        if document_id:
            metadata["document_id"] = document_id
        metadata["dataset_id"] = dataset_id
        metadata["dify_metadata_anchor_fallback"] = True
        chunk_index = _row_value(row, "chunk_index")
        if chunk_index is not None:
            metadata["chunk_index"] = chunk_index
        page_number = _row_value(row, "page_number")
        if page_number is not None:
            metadata["page_number"] = page_number

        record = {
            "content": _content_with_answer_hints(
                content,
                metadata,
                query=query,
                policy_plugin_refs=policy_plugin_refs,
            ),
            "score": 0.0,
            "title": str(_row_value(row, "filename") or metadata.get("title") or "metadata-anchor-match").strip(),
            "metadata": metadata,
        }
        score = _metadata_anchor_fallback_record_score(
            record,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if score <= 0:
            continue
        record["score"] = score
        candidates.append(record)

    if not candidates:
        return []
    _sort_records_for_query(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    if _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs):
        requested_slots = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
        if requested_slots:
            composite = _composite_record_for_exact_anchor_slots(
                candidates,
                query=query,
                requested_slot_specs=requested_slots,
                policy_plugin_refs=policy_plugin_refs,
            )
            if composite is not None:
                return [composite]
    merged = _dedupe_records(candidates, query=query, policy_plugin_refs=policy_plugin_refs)
    _sort_records_for_query(merged, query=query, policy_plugin_refs=policy_plugin_refs)
    limit = max(1, min(max(1, int(top_k or 1)), int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS", 4) or 4)))
    return merged[:limit]


def _metadata_anchor_db_fallback_records(
    *,
    db: Session,
    tenant_id: UUID,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    policy_plugin_refs: tuple[str, ...] = (),
    existing_records: list[dict[str, Any]] | None = None,
    metadata_filter: dict[str, Any] | None = None,
    prefer_question_anchor_first: bool = False,
    statement_timeout_ms_override: int | None = None,
    max_elapsed_ms: int | None = None,
) -> list[dict[str, Any]]:
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", False)):
        return []
    if metadata_filter:
        return []
    if _records_can_skip_metadata_anchor_fallback(
        existing_records or [],
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    ):
        return []

    scoped_dataset_ids = _dedupe_dataset_ids(list(dataset_ids or []))
    if not scoped_dataset_ids:
        return []
    terms = _metadata_anchor_fallback_query_terms(query)
    if not terms:
        return []

    max_scan = max(
        1,
        min(
            500,
            int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN", 80) or 80),
        ),
    )
    started = time.perf_counter()
    max_elapsed_ms_value = max(0, min(30000, int(max_elapsed_ms or 0)))

    class MetadataAnchorBudgetExceededError(Exception):
        pass

    def budget_exceeded() -> bool:
        return bool(max_elapsed_ms_value) and ((time.perf_counter() - started) * 1000 >= max_elapsed_ms_value)

    def is_statement_timeout_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "statement timeout" in text or "querycanceled" in text or "canceling statement due to statement timeout" in text

    rows: list[Any] = []
    seen_chunk_ids: set[str] = set()

    try:
        configured_statement_timeout = (
            statement_timeout_ms_override
            if statement_timeout_ms_override is not None
            else getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_STATEMENT_TIMEOUT_MS", 2500)
        )
        statement_timeout_ms = max(0, min(30000, int(configured_statement_timeout or 0)))
        if not max_elapsed_ms_value and statement_timeout_ms:
            db.execute(sql_text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))

        def append_unique(batch: list[Any] | tuple[Any, ...]) -> None:
            for row in batch:
                chunk_id = _coerce_uuid_text(_row_value(row, "chunk_id"))
                if not chunk_id or chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                rows.append(row)

        def query_matching_rows(condition: Any, *, limit: int) -> list[Any]:
            nonlocal statement_timeout_ms
            if budget_exceeded():
                raise MetadataAnchorBudgetExceededError
            if max_elapsed_ms_value:
                elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
                remaining_ms = max(1, max_elapsed_ms_value - elapsed_ms)
                statement_timeout_ms = (
                    min(statement_timeout_ms, remaining_ms) if statement_timeout_ms else remaining_ms
                )
                db.execute(sql_text(f"SET LOCAL statement_timeout = {statement_timeout_ms}"))
                if budget_exceeded():
                    raise MetadataAnchorBudgetExceededError
            return (
                db.query(
                    DocumentChunk.id.label("chunk_id"),
                    DocumentChunk.document_id.label("document_id"),
                    DocumentChunk.chunk_index.label("chunk_index"),
                    DocumentChunk.page_number.label("page_number"),
                    DocumentChunk.content.label("content"),
                    DocumentChunk.doc_metadata.label("metadata"),
                    Document.dataset_id.label("dataset_id"),
                    Document.filename.label("filename"),
                )
                .join(Document, DocumentChunk.document_id == Document.id)
                .filter(
                    DocumentChunk.tenant_id == tenant_id,
                    Document.tenant_id == tenant_id,
                    Document.dataset_id.in_(scoped_dataset_ids),
                    Document.status == "completed",
                    Document.publication_status == "published",
                    Document.archived_at.is_(None),
                    DocumentChunk.disabled_at.is_(None),
                    Document.disabled_at.is_(None),
                    condition,
                )
                .order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc())
                .limit(max(1, int(limit or 1)))
                .all()
            )

        def matched_records() -> list[dict[str, Any]]:
            return _metadata_anchor_fallback_records_from_rows(
                rows,
                dataset_ids=scoped_dataset_ids,
                query=query,
                top_k=top_k,
                policy_plugin_refs=policy_plugin_refs,
                existing_records=existing_records,
            )

        primary_term = terms[0]
        question_anchor_preferred = _query_prefers_question_anchor(query, policy_plugin_refs=policy_plugin_refs)
        service_anchor_preferred = _query_prefers_service_anchor(query, policy_plugin_refs=policy_plugin_refs)
        query_has_slot_question_intent = bool(
            _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
            or _query_intent_terms(
                query,
                intent_terms=_question_anchor_intent_terms_for_policy_refs(policy_plugin_refs),
            )
        )
        question_anchor_first = _metadata_anchor_should_query_question_first(
            query,
            query_prefers_question_anchor=question_anchor_preferred,
            query_prefers_service_anchor=service_anchor_preferred,
            prefer_question_anchor_first=bool(prefer_question_anchor_first),
            policy_plugin_refs=policy_plugin_refs,
        )
        requested_slot_specs = _requested_policy_slot_specs_for_query(query, policy_plugin_refs=policy_plugin_refs)
        service_name_terms = _metadata_anchor_service_name_query_terms(
            query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if not service_name_terms:
            service_name_terms = terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]
        service_anchor_fields = _anchor_binding_fields_for_policy_refs(policy_plugin_refs) or ("service_name",)
        mixed_intent_retrieval_queries = _mixed_intent_retrieval_queries(query, policy_plugin_refs=policy_plugin_refs)
        if (
            service_anchor_preferred
            and (
                not (question_anchor_first and query_has_slot_question_intent)
                or len(mixed_intent_retrieval_queries) >= 2
            )
        ):
            for service_name_term in service_name_terms:
                exact_service_name = service_name_term.replace("%", "").replace("_", "").strip()
                if not exact_service_name:
                    continue
                append_unique(
                    query_matching_rows(
                        DocumentChunk.doc_metadata["service_name"].astext == exact_service_name,
                        limit=max_scan,
                    )
                )
                current_matches = matched_records()
                if current_matches:
                    return current_matches
        primary_pattern = f"%{primary_term.replace('%', '').replace('_', '').strip()}%"
        if (
            _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs)
            and requested_slot_specs
            and _query_has_quoted_anchor_candidate(query)
        ):
            anchor_fields = _anchor_binding_fields_for_policy_refs(policy_plugin_refs) or ("service_name",)
            exact_anchor_terms = list(_quoted_query_anchor_terms(query))
            seen_exact_anchor_terms = {_normalize_match_term(term) for term in exact_anchor_terms}
            for term in _metadata_anchor_title_query_terms(
                query,
                policy_plugin_refs=policy_plugin_refs,
            )[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]:
                normalized = _normalize_match_term(term)
                if len(normalized) < 4 or normalized in seen_exact_anchor_terms:
                    continue
                seen_exact_anchor_terms.add(normalized)
                exact_anchor_terms.append(term)
            anchor_conditions = []
            for anchor_term in exact_anchor_terms:
                cleaned_anchor = anchor_term.replace("%", "").replace("_", "").strip()
                if len(_normalize_match_term(cleaned_anchor)) < 4:
                    continue
                pattern = f"%{cleaned_anchor}%"
                anchor_conditions.extend(
                    DocumentChunk.doc_metadata[field].astext.ilike(pattern)
                    for field in anchor_fields
                )
            slot_conditions = [
                DocumentChunk.doc_metadata[field].astext == str(slot_value).strip()
                for field, slot_value in requested_slot_specs
                if str(field).strip() and str(slot_value).strip()
            ]
            if anchor_conditions and slot_conditions:
                rows_before_exact_slot_scan = len(rows)
                seen_before_exact_slot_scan = set(seen_chunk_ids)
                append_unique(
                    query_matching_rows(
                        and_(or_(*anchor_conditions), or_(*slot_conditions)),
                        limit=max_scan,
                    )
                )
                current_matches = matched_records()
                if any(_record_is_composite_exact_anchor_answer(record) for record in current_matches):
                    return current_matches
                del rows[rows_before_exact_slot_scan:]
                seen_chunk_ids.clear()
                seen_chunk_ids.update(seen_before_exact_slot_scan)

        if question_anchor_first:
            append_unique(
                query_matching_rows(DocumentChunk.doc_metadata["question"].astext.ilike(primary_pattern), limit=max_scan)
            )
            append_unique(
                query_matching_rows(
                    or_(
                        DocumentChunk.doc_metadata["primary_alias"].astext.ilike(primary_pattern),
                        DocumentChunk.doc_metadata["aliases"].astext.ilike(primary_pattern),
                        DocumentChunk.doc_metadata.contains({"aliases": [primary_term]}),
                    ),
                    limit=max_scan,
                )
            )
            current_matches = matched_records()
            if current_matches and not query_has_slot_question_intent:
                return current_matches

        if question_anchor_first and query_has_slot_question_intent:
            alias_scan_terms = _metadata_anchor_title_query_terms(
                query,
                policy_plugin_refs=policy_plugin_refs,
            )[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]
            alias_scan_conditions = []
            for alias_term in alias_scan_terms:
                cleaned_alias_term = alias_term.replace("%", "").replace("_", "").strip()
                if not cleaned_alias_term:
                    continue
                pattern = f"%{cleaned_alias_term}%"
                alias_scan_conditions.append(
                    or_(
                        DocumentChunk.doc_metadata["question"].astext.ilike(pattern),
                        DocumentChunk.doc_metadata["primary_alias"].astext.ilike(pattern),
                        DocumentChunk.doc_metadata["aliases"].astext.ilike(pattern),
                        DocumentChunk.doc_metadata.contains({"aliases": [alias_term]}),
                    )
                )
            if alias_scan_conditions:
                rows_before_alias_scan = len(rows)
                append_unique(query_matching_rows(or_(*alias_scan_conditions), limit=max_scan))
                if len(rows) > rows_before_alias_scan:
                    current_matches = matched_records()
                    if current_matches:
                        return current_matches

        question_conditions = []
        for term in terms[1:]:
            cleaned_term = term.replace("%", "").replace("_", "").strip()
            if not cleaned_term:
                continue
            pattern = f"%{cleaned_term}%"
            question_conditions.append(
                or_(
                    DocumentChunk.doc_metadata["question"].astext.ilike(pattern),
                    DocumentChunk.doc_metadata["primary_alias"].astext.ilike(pattern),
                )
            )
        if (
            question_anchor_first
            and question_conditions
        ):
            append_unique(query_matching_rows(or_(*question_conditions), limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches

        if (
            _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs)
            and _query_has_quoted_anchor_candidate(query)
            and question_anchor_preferred
        ):
            rows_before_exact_question = len(rows)
            seen_before_exact_question = set(seen_chunk_ids)
            quoted_anchor_norms = tuple(_quoted_query_anchor_terms(query))
            exact_question_terms = list(quoted_anchor_norms)
            seen_exact_question_terms = set(exact_question_terms)
            for term in terms:
                normalized_term = _normalize_match_term(term)
                if (
                    len(normalized_term) >= 4
                    and normalized_term not in seen_exact_question_terms
                    and any(normalized_term in anchor or anchor in normalized_term for anchor in quoted_anchor_norms)
                ):
                    seen_exact_question_terms.add(normalized_term)
                    exact_question_terms.append(term)
            exact_question_conditions = [
                DocumentChunk.doc_metadata["question"].astext.ilike(
                    f"%{anchor_term.replace('%', '').replace('_', '').strip()}%"
                )
                for anchor_term in exact_question_terms
                if anchor_term.replace("%", "").replace("_", "").strip()
            ]
            if exact_question_conditions:
                append_unique(query_matching_rows(or_(*exact_question_conditions), limit=max_scan))
                current_matches = matched_records()
                if _compact_mixed_intent_exact_anchor_records(
                    current_matches,
                    query=query,
                    top_k=top_k,
                    policy_plugin_refs=policy_plugin_refs,
                ):
                    return current_matches
                del rows[rows_before_exact_question:]
                seen_chunk_ids.clear()
                seen_chunk_ids.update(seen_before_exact_question)

        if (
            _query_has_mixed_intent_for_policy(query, policy_plugin_refs=policy_plugin_refs)
            and _query_has_quoted_anchor_candidate(query)
            and requested_slot_specs
        ):
            anchor_fields = _anchor_binding_fields_for_policy_refs(policy_plugin_refs)
            anchor_conditions = []
            if anchor_fields:
                for anchor_term in _quoted_query_anchor_terms(query):
                    cleaned_anchor = anchor_term.replace("%", "").replace("_", "").strip()
                    if len(_normalize_match_term(cleaned_anchor)) < 4:
                        continue
                    pattern = f"%{cleaned_anchor}%"
                    anchor_conditions.extend(
                        DocumentChunk.doc_metadata[field].astext.ilike(pattern)
                        for field in anchor_fields
                    )
            slot_conditions = [
                DocumentChunk.doc_metadata[field].astext == str(slot_value).strip()
                for field, slot_value in requested_slot_specs
                if str(field).strip() and str(slot_value).strip()
            ]
            if anchor_conditions and slot_conditions:
                append_unique(
                    query_matching_rows(
                        and_(or_(*anchor_conditions), or_(*slot_conditions)),
                        limit=max_scan,
                    )
                )
                current_matches = matched_records()
                if _compact_mixed_intent_exact_anchor_records(
                    current_matches,
                    query=query,
                    top_k=top_k,
                    policy_plugin_refs=policy_plugin_refs,
                ):
                    return current_matches
        if question_anchor_preferred and not service_anchor_preferred:
            return []

        exact_service_name_conditions = [
            DocumentChunk.doc_metadata[field].astext == term.replace("%", "").replace("_", "").strip()
            for term in service_name_terms[:_METADATA_ANCHOR_DB_FALLBACK_SERVICE_NAME_MAX_TERMS]
            for field in service_anchor_fields
            if term.replace("%", "").replace("_", "").strip()
        ]
        if exact_service_name_conditions:
            append_unique(query_matching_rows(or_(*exact_service_name_conditions), limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches
        service_name_conditions = [
            DocumentChunk.doc_metadata[field].astext.ilike(
                f"%{term.replace('%', '').replace('_', '').strip()}%"
            )
            for term in service_name_terms
            for field in service_anchor_fields
            if term.replace("%", "").replace("_", "").strip()
        ]
        for service_name_condition in service_name_conditions:
            append_unique(query_matching_rows(service_name_condition, limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches

        title_terms = _metadata_anchor_title_query_terms(
            query,
            policy_plugin_refs=policy_plugin_refs,
        )
        for title_term in title_terms:
            cleaned_term = title_term.replace("%", "").replace("_", "").strip()
            if not cleaned_term:
                continue
            pattern = f"%{cleaned_term}%"
            title_conditions = [
                DocumentChunk.doc_metadata[field].astext.ilike(pattern)
                for field in _METADATA_ANCHOR_DB_FALLBACK_TITLE_FIELDS
            ]
            append_unique(query_matching_rows(or_(*title_conditions), limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches

        service_name_near_conditions = []
        for term in service_name_terms:
            normalized = _normalize_match_term(term)
            if len(normalized) < 4 or not _CJK_RE.search(normalized):
                continue
            left = normalized[:2]
            right = normalized[-2:]
            if left == right:
                continue
            for field in service_anchor_fields:
                service_name_near_conditions.append(
                    and_(
                        DocumentChunk.doc_metadata[field].astext.ilike(f"%{left}%"),
                        DocumentChunk.doc_metadata[field].astext.ilike(f"%{right}%"),
                    )
                )
        for service_name_near_condition in service_name_near_conditions:
            append_unique(query_matching_rows(service_name_near_condition, limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches

        if question_conditions:
            append_unique(query_matching_rows(or_(*question_conditions), limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches

        for field in ("retrieval_intents", "query_intents", "intent_terms"):
            append_unique(
                query_matching_rows(
                    DocumentChunk.doc_metadata.contains({field: [primary_term]}),
                    limit=max_scan,
                )
            )
            current_matches = matched_records()
            if current_matches:
                return current_matches

        for term in terms:
            cleaned_term = term.replace("%", "").replace("_", "").strip()
            if not cleaned_term:
                continue
            pattern = f"%{cleaned_term}%"

            append_unique(query_matching_rows(DocumentChunk.doc_metadata["question"].astext.ilike(pattern), limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches

            for field in ("retrieval_intents", "query_intents", "intent_terms"):
                append_unique(
                    query_matching_rows(
                        DocumentChunk.doc_metadata.contains({field: [cleaned_term]}),
                        limit=max_scan,
                    )
                )
                current_matches = matched_records()
                if current_matches:
                    return current_matches
            scalar_conditions = [
                DocumentChunk.doc_metadata[field].astext.ilike(pattern)
                for field in _METADATA_ANCHOR_DB_FALLBACK_SCALAR_FIELDS
                if field != "question"
            ]
            append_unique(query_matching_rows(or_(*scalar_conditions), limit=max_scan))
            current_matches = matched_records()
            if current_matches:
                return current_matches
            for field in _METADATA_ANCHOR_DB_FALLBACK_ARRAY_FIELDS:
                if field in {"retrieval_intents", "query_intents", "intent_terms"}:
                    continue
                append_unique(
                    query_matching_rows(
                        DocumentChunk.doc_metadata.contains({field: [cleaned_term]}),
                        limit=max_scan,
                    )
                )
                current_matches = matched_records()
                if current_matches:
                    return current_matches
            if len(rows) >= max_scan:
                break
        if bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_TEXT_SCAN_ENABLED", False)):
            metadata_text = sql_cast(DocumentChunk.doc_metadata, SQLText)
            for term in terms[:3]:
                cleaned_term = term.replace("%", "").replace("_", "").strip()
                if not cleaned_term:
                    continue
                append_unique(query_matching_rows(metadata_text.ilike(f"%{cleaned_term}%"), limit=max_scan))
                current_matches = matched_records()
                if current_matches:
                    return current_matches
    except MetadataAnchorBudgetExceededError:
        logger.info(
            "Dify metadata anchor fallback budget exhausted query_hash=%s elapsed_ms=%s max_elapsed_ms=%s rows=%s",
            _diagnostic_query_hash(query),
            round((time.perf_counter() - started) * 1000, 2),
            max_elapsed_ms_value,
            len(rows),
            extra={
                "event": "dify_metadata_anchor_budget_exhausted",
                "query_hash": _diagnostic_query_hash(query),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "max_elapsed_ms": max_elapsed_ms_value,
            },
        )
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("Failed to rollback Dify metadata anchor fallback transaction", exc_info=True)
        if is_statement_timeout_error(exc):
            logger.info(
                "Dify metadata anchor fallback budget exhausted query_hash=%s elapsed_ms=%s statement_timeout_ms=%s rows=%s",
                _diagnostic_query_hash(query),
                round((time.perf_counter() - started) * 1000, 2),
                statement_timeout_ms if "statement_timeout_ms" in locals() else None,
                len(rows),
                extra={
                    "event": "dify_metadata_anchor_budget_exhausted",
                    "query_hash": _diagnostic_query_hash(query),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "statement_timeout_ms": statement_timeout_ms if "statement_timeout_ms" in locals() else None,
                    "row_count": len(rows),
                },
            )
        else:
            logger.warning("Failed to run Dify metadata anchor fallback", exc_info=True)
            return []
    finally:
        if max_elapsed_ms_value:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to reset Dify metadata anchor fallback transaction", exc_info=True)

    return _metadata_anchor_fallback_records_from_rows(
        rows,
        dataset_ids=scoped_dataset_ids,
        query=query,
        top_k=top_k,
        policy_plugin_refs=policy_plugin_refs,
        existing_records=existing_records,
    )


def _metadata_anchor_db_fallback_records_with_managed_session(
    *,
    budget_deadline: float | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    if budget_deadline is not None:
        remaining_ms = max(0, int((budget_deadline - time.perf_counter()) * 1000))
        if remaining_ms <= 0:
            return []
        configured_budget = int(kwargs.get("max_elapsed_ms") or 0)
        kwargs["max_elapsed_ms"] = min(remaining_ms, configured_budget) if configured_budget > 0 else remaining_ms
    worker_db = SessionLocal()
    try:
        return _metadata_anchor_db_fallback_records(db=worker_db, **kwargs)
    finally:
        worker_db.close()


async def _retrieve_dataset_citations(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float,
    metadata_filter: dict[str, Any] | None = None,
    requested_top_k: int | None = None,
    enable_kg_query_expansion: bool | None = None,
    enable_kg_chunk_injection: bool | None = None,
    kg_chunk_injection_max_chunks: int | None = None,
    enable_kg_chunk_boost: bool | None = None,
    kg_chunk_boost_weight: float | None = None,
    kg_chunk_boost_max_promoted: int | None = None,
    enable_reranker: bool | None = None,
    retrieval_mode: str = "hybrid",
) -> list[dict[str, Any]]:
    from app.api.v1.rag import EvidenceRetrieveRequest, retrieve_evidence

    started = time.perf_counter()
    evidence_top_k = max(1, int(top_k or 1))
    if requested_top_k is None:
        evidence_top_k = _resolve_internal_candidate_top_k(evidence_top_k)

    kg_query_expansion_enabled = (
        _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", False)
        if enable_kg_query_expansion is None
        else bool(enable_kg_query_expansion)
    )
    kg_chunk_injection_enabled = (
        _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", False)
        if enable_kg_chunk_injection is None
        else bool(enable_kg_chunk_injection)
    )
    kg_chunk_boost_enabled = (
        _dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)
        if enable_kg_chunk_boost is None
        else bool(enable_kg_chunk_boost)
    )
    overfetch_multiplier = max(
        1,
        int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1),
    )
    overfetch_max_k = max(
        0,
        int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K", 0) or 0),
    )
    if overfetch_max_k <= 0:
        overfetch_max_k = evidence_top_k

    reranker_enabled = _dify_external_reranker_enabled() if enable_reranker is None else bool(enable_reranker)
    reranker_top_n = max(
        1,
        int(getattr(settings, "RERANKER_TOP_N", evidence_top_k) or evidence_top_k),
        int(evidence_top_k or 1),
    )
    rag_config = ChatRAGConfig(
        top_k=evidence_top_k,
        score_threshold=score_threshold,
        retrieval_mode=str(retrieval_mode or "hybrid"),
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=reranker_enabled,
        reranker_provider=str(getattr(settings, "RERANKER_PROVIDER", "llm") or "llm") if reranker_enabled else "none",
        reranker_top_n=reranker_top_n,
        lexical_db_hybrid_fallback_only=bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_DB_HYBRID_FALLBACK_ONLY", False)
        ),
        lexical_db_hybrid_metadata_exact_fallback_enabled=bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED", False)
        ),
        metadata_exact_db_fallback_enabled=bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED", False)
        ),
        retrieval_overfetch_multiplier=overfetch_multiplier,
        retrieval_overfetch_max_k=overfetch_max_k,
        enable_kg_query_expansion=kg_query_expansion_enabled,
        enable_kg_chunk_injection=kg_chunk_injection_enabled,
        kg_chunk_injection_max_chunks=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3)
            if kg_chunk_injection_max_chunks is None
            else int(kg_chunk_injection_max_chunks)
        ),
        enable_kg_chunk_boost=kg_chunk_boost_enabled,
        kg_chunk_boost_weight=(
            _dify_kg_float("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25)
            if kg_chunk_boost_weight is None
            else float(kg_chunk_boost_weight)
        ),
        kg_chunk_boost_max_promoted=(
            _dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2)
            if kg_chunk_boost_max_promoted is None
            else int(kg_chunk_boost_max_promoted)
        ),
    )

    scoped_dataset_ids = _dedupe_dataset_ids(list(dataset_ids or []))
    evidence_request_kwargs: dict[str, Any] = {"query": query, "rag_config": rag_config}
    evidence_request_kwargs["dataset_ids"] = scoped_dataset_ids

    response = await retrieve_evidence(
        body=EvidenceRetrieveRequest(**evidence_request_kwargs),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response_metrics = getattr(response, "metrics", None)
    response_trace = getattr(response, "retrieval_trace", None)
    metrics = response_metrics if isinstance(response_metrics, dict) else {}
    trace = response_trace if isinstance(response_trace, dict) else {}
    logger.info(
        "Dify evidence retrieve completed query_hash=%s dataset_count=%s top_k=%s requested_top_k=%s "
        "citations=%s elapsed_ms=%s retrieval_elapsed_sec=%s vector_backend=%s retrieval_mode=%s "
        "post_rerank_elapsed_sec=%s hard_fallback_elapsed_sec=%s trace_passes=%s",
        _diagnostic_query_hash(query),
        len(scoped_dataset_ids),
        evidence_top_k,
        requested_top_k,
        len(getattr(response, "citations", None) or []),
        elapsed_ms,
        metrics.get("retrieval_elapsed_sec"),
        metrics.get("vector_backend"),
        metrics.get("retrieval_mode") or metrics.get("requested_retrieval_mode"),
        metrics.get("evidence_post_rerank_elapsed_sec"),
        metrics.get("hard_fallback_elapsed_sec"),
        len(trace.get("passes") or []) if isinstance(trace, dict) else 0,
    )
    return list(getattr(response, "citations", None) or [])


def _resolve_dify_warmup_tenant_id() -> UUID | None:
    raw_tenant = str(
        getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "")
        or getattr(settings, "DEFAULT_TENANT_ID", "")
    ).strip()
    if not raw_tenant:
        return None
    try:
        return UUID(raw_tenant)
    except ValueError:
        logger.warning("Skipping Dify external warmup: tenant id is invalid")
        return None


def _resolve_dify_warmup_query() -> str:
    query = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY", "") or "").strip()
    return query or _DIFY_WARMUP_DEFAULT_QUERY


def _resolve_dify_warmup_top_k() -> int:
    try:
        configured_top_k = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K", 1) or 1)
    except (TypeError, ValueError):
        configured_top_k = 1
    try:
        configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 5)
    except (TypeError, ValueError):
        configured_max = 5
    return max(1, min(configured_top_k, max(1, configured_max)))


def _resolve_dify_warmup_timeout_sec() -> float:
    try:
        timeout_sec = float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC", 60.0) or 60.0)
    except (TypeError, ValueError):
        timeout_sec = 60.0
    return max(1.0, timeout_sec)


def _resolve_dify_warmup_start_delay_sec() -> float:
    try:
        delay_sec = float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC", 1.0) or 0.0)
    except (TypeError, ValueError):
        delay_sec = 1.0
    return max(0.0, min(60.0, delay_sec))


async def warmup_dify_external_knowledge(
    *,
    db_factory: Callable[[], Session] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        _set_dify_external_warmup_status(
            enabled=False,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0,
        )
        return {"enabled": False, "reason": "external_knowledge_disabled", "attempted": 0, "completed": 0, "failed": 0}
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED", True)):
        _set_dify_external_warmup_status(
            enabled=True,
            status="disabled",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=0,
        )
        return {"enabled": False, "reason": "warmup_disabled", "attempted": 0, "completed": 0, "failed": 0}
    _set_dify_external_warmup_status(
        enabled=True,
        status="running",
        attempted=0,
        completed=0,
        failed=0,
        elapsed_ms=None,
    )

    try:
        knowledge_map = _load_knowledge_map()
    except Exception:  # noqa: BLE001
        logger.warning("Skipping Dify external warmup: knowledge map is invalid", exc_info=True)
        _set_dify_external_warmup_status(
            enabled=True,
            status="failed",
            attempted=0,
            completed=0,
            failed=1,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return {"enabled": True, "reason": "invalid_knowledge_map", "attempted": 0, "completed": 0, "failed": 1}

    knowledge_ids = _resolve_dify_warmup_knowledge_ids(knowledge_map)
    tenant_id = _resolve_dify_warmup_tenant_id()
    if tenant_id is None:
        _set_dify_external_warmup_status(
            enabled=True,
            status="skipped",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return {"enabled": True, "reason": "tenant_not_configured", "attempted": 0, "completed": 0, "failed": 0}
    if not knowledge_ids:
        _set_dify_external_warmup_status(
            enabled=True,
            status="skipped",
            attempted=0,
            completed=0,
            failed=0,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return {"enabled": True, "reason": "no_knowledge_ids", "attempted": 0, "completed": 0, "failed": 0}
    _set_dify_external_warmup_status(enabled=True, status="running", attempted=len(knowledge_ids))

    factory = db_factory or SessionLocal
    account_id = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "") or "system:dify").strip()
    query = _resolve_dify_warmup_query()
    top_k = _resolve_dify_warmup_top_k()
    score_threshold = 0.0
    timeout_sec = _resolve_dify_warmup_timeout_sec()
    completed = 0
    failed = 0

    for knowledge_id in knowledge_ids:
        item_started = time.perf_counter()
        db = None
        try:
            scope_plan = _resolve_knowledge_dataset_scope(knowledge_id, query=query)
            primary_scope_enabled = bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True))
            dataset_ids = list(scope_plan.primary_dataset_ids if primary_scope_enabled else scope_plan.dataset_ids)
            if not dataset_ids:
                dataset_ids = list(scope_plan.dataset_ids)
            db = factory()
            await asyncio.wait_for(
                _retrieve_dataset_citations(
                    db=db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    dataset_ids=dataset_ids,
                    query=query,
                    top_k=top_k,
                    requested_top_k=top_k,
                    score_threshold=score_threshold,
                    enable_kg_query_expansion=False,
                    enable_kg_chunk_injection=False,
                    enable_kg_chunk_boost=False,
                    enable_reranker=False,
                ),
                timeout=timeout_sec,
            )
            completed += 1
            item_elapsed_ms = round((time.perf_counter() - item_started) * 1000, 2)
            logger.info(
                "Dify external warmup completed knowledge_id_hash=%s dataset_count=%s elapsed_ms=%s",
                _diagnostic_value_hash(knowledge_id),
                len(dataset_ids),
                item_elapsed_ms,
                extra={
                    "event": "dify_external_warmup",
                    "phase": "knowledge_completed",
                    "knowledge_id_hash": _diagnostic_value_hash(knowledge_id),
                    "dataset_count": len(dataset_ids),
                    "elapsed_ms": item_elapsed_ms,
                },
            )
        except Exception:  # noqa: BLE001
            failed += 1
            item_elapsed_ms = round((time.perf_counter() - item_started) * 1000, 2)
            logger.warning(
                "Dify external warmup failed knowledge_id_hash=%s elapsed_ms=%s",
                _diagnostic_value_hash(knowledge_id),
                item_elapsed_ms,
                exc_info=True,
                extra={
                    "event": "dify_external_warmup",
                    "phase": "knowledge_failed",
                    "knowledge_id_hash": _diagnostic_value_hash(knowledge_id),
                    "elapsed_ms": item_elapsed_ms,
                },
            )
        finally:
            if db is not None:
                close = getattr(db, "close", None)
                if callable(close):
                    close()

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    result = {
        "enabled": True,
        "reason": "completed",
        "attempted": len(knowledge_ids),
        "completed": completed,
        "failed": failed,
        "elapsed_ms": elapsed_ms,
    }
    _set_dify_external_warmup_status(
        enabled=True,
        status="completed" if failed == 0 else "failed",
        attempted=len(knowledge_ids),
        completed=completed,
        failed=failed,
        elapsed_ms=elapsed_ms,
    )
    logger.info(
        "Dify external warmup finished attempted=%s completed=%s failed=%s elapsed_ms=%s",
        result["attempted"],
        completed,
        failed,
        elapsed_ms,
        extra={"event": "dify_external_warmup", "phase": "finished", **result},
    )
    return result


async def _delayed_warmup_dify_external_knowledge() -> dict[str, Any]:
    delay_sec = _resolve_dify_warmup_start_delay_sec()
    if delay_sec > 0:
        await asyncio.sleep(delay_sec)
    else:
        # Yield once so lifespan can return before any cold retrieval work runs.
        await asyncio.sleep(0)
    return await warmup_dify_external_knowledge()


def _log_dify_warmup_task_result(task: Any) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Dify external warmup task cancelled")
    except Exception:  # noqa: BLE001
        logger.warning("Dify external warmup task failed", exc_info=True)


def start_dify_external_knowledge_warmup(
    *,
    create_task: Callable[[Any], Any] | None = None,
) -> Any | None:
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        _set_dify_external_warmup_status(enabled=False, status="disabled")
        return None
    if not bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED", True)):
        _set_dify_external_warmup_status(enabled=True, status="disabled")
        return None

    delay_sec = _resolve_dify_warmup_start_delay_sec()
    _set_dify_external_warmup_status(enabled=True, status="scheduled", start_delay_sec=delay_sec)
    coro = _delayed_warmup_dify_external_knowledge()
    try:
        task = create_task(coro) if create_task is not None else asyncio.create_task(coro)
    except RuntimeError:
        coro.close()
        logger.warning("Dify external warmup was not scheduled: no running event loop")
        return None
    except Exception:  # noqa: BLE001
        coro.close()
        logger.warning("Dify external warmup was not scheduled", exc_info=True)
        return None

    add_done_callback = getattr(task, "add_done_callback", None)
    if callable(add_done_callback):
        add_done_callback(_log_dify_warmup_task_result)
    logger.info("Dify external warmup scheduled start_delay_sec=%s", delay_sec)
    return task


@router.post(
    "/conversation-turns",
    response_model=DifyConversationTurnResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def persist_dify_conversation_turn(
    body: DifyConversationTurnRequest,
    actor: Annotated[_DifyActor, Depends(_require_dify_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> DifyConversationTurnResponse:
    return await run_blocking_call_with_managed_session(
        lambda worker_db: _persist_dify_conversation_turn(
            db=worker_db,
            tenant_id=actor.tenant_id,
            account_id=actor.account_id,
            query=body.query,
            answer=body.answer,
            trace_request_id=body.trace_request_id,
            source_conversation_id=_dify_turn_source_conversation_id(body),
            source_message_id=_dify_turn_source_message_id(body),
            source_run_id=_dify_turn_source_run_id(body),
            citations=body.citations,
            metadata=body.metadata,
            conversation_id=_uuid_or_none(body.conversation_id),
        ),
        request_db=db,
    )


@router.post("/retrieval", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retrieve_external_knowledge(
    request: Request,
    body: DifyExternalKnowledgeRequest,
    actor: Annotated[_DifyActor, Depends(_require_dify_actor)],
    db: Annotated[Session, Depends(get_db)],
) -> DifyExternalKnowledgeResponse:
    return await _retrieve_external_knowledge(request=request, body=body, actor=actor, db=db)


async def _retrieve_external_knowledge(
    *,
    request: Request,
    body: DifyExternalKnowledgeRequest,
    actor: _DifyActor,
    db: Session,
) -> DifyExternalKnowledgeResponse:
    started = time.perf_counter()
    scope_plan = _resolve_knowledge_dataset_scope(body.knowledge_id, query=body.query)
    dataset_ids = list(scope_plan.dataset_ids)
    primary_scope_enabled = bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_SCOPE_ENABLED", True))
    primary_dataset_ids = list(scope_plan.primary_dataset_ids if primary_scope_enabled else scope_plan.dataset_ids)
    if not primary_dataset_ids:
        primary_dataset_ids = dataset_ids
    expansion_dataset_ids = list(scope_plan.expansion_dataset_ids if primary_scope_enabled else ())
    configured_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 5)
    top_k = max(1, min(int(body.retrieval_setting.top_k), configured_max))
    latency_profile = _resolve_dify_latency_profile(body.retrieval_setting)
    fast_latency_profile = latency_profile == "fast"
    candidate_top_k = _dify_fast_candidate_top_k(top_k) if fast_latency_profile else _resolve_internal_candidate_top_k(top_k)
    response_top_k = _dify_fast_response_top_k(top_k) if fast_latency_profile else top_k
    policy_fallback_multiplier = 1
    if not fast_latency_profile:
        policy_fallback_multiplier = _resolve_knowledge_policy_fallback_multiplier(body.knowledge_id)
        candidate_top_k = _apply_policy_fallback_candidate_multiplier(
            candidate_top_k,
            multiplier=policy_fallback_multiplier,
        )
    policy_plugin_refs = _resolve_knowledge_policy_plugin_refs(body.knowledge_id)
    external_reranker_enabled = False if fast_latency_profile else _dify_external_reranker_enabled()
    limit_mixed_intent_candidate_top_k = (
        not fast_latency_profile
        and
        _query_has_mixed_intent_for_policy(body.query, policy_plugin_refs=policy_plugin_refs)
        and external_reranker_enabled
    )
    if limit_mixed_intent_candidate_top_k:
        candidate_top_k = min(candidate_top_k, top_k)
    score_threshold = _clamp_score(body.retrieval_setting.score_threshold)
    policy_filter_fields = _resolve_knowledge_policy_filter_fields(body.knowledge_id)
    metadata_filter = _metadata_condition_to_filter(body.metadata_condition, allowed_fields=policy_filter_fields)
    metadata_anchor_dataset_ids = _metadata_anchor_dataset_ids_for_query(
        knowledge_id=body.knowledge_id,
        base_dataset_ids=primary_dataset_ids,
        query=body.query,
        policy_plugin_refs=policy_plugin_refs,
    )
    requested_kg_flags = _resolve_dify_kg_flags(body.retrieval_setting)
    kg_on_demand_enabled = (
        False
        if fast_latency_profile
        else bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED", True))
    )
    primary_kg_flags = (
        _disabled_dify_kg_flags()
        if fast_latency_profile
        else (
            _disabled_dify_kg_flags()
            if requested_kg_flags.enabled and kg_on_demand_enabled
            else requested_kg_flags
        )
    )
    log_extra_base = {
        "event": "dify_external_retrieval",
        "client_ip_hash": _diagnostic_value_hash(_request_client_ip(request)),
        "knowledge_id_hash": _diagnostic_value_hash(body.knowledge_id),
        "query_hash": _diagnostic_query_hash(body.query),
        "knowledge_id_chars": len(str(body.knowledge_id or "")),
        "query_chars": len(str(body.query or "")),
        "top_k": top_k,
        "candidate_top_k": candidate_top_k,
        "response_top_k": response_top_k,
        "latency_profile": latency_profile,
        "policy_fallback_multiplier": policy_fallback_multiplier,
        "score_threshold": score_threshold,
        "dataset_count": len(dataset_ids),
        "primary_dataset_count": len(primary_dataset_ids),
        "expansion_dataset_count": len(expansion_dataset_ids),
        "route_count": scope_plan.route_count,
        "matched_route_count": scope_plan.matched_route_count,
        "strict_scope": scope_plan.strict_scope,
        "metadata_filter": bool(metadata_filter),
        "kg_requested": requested_kg_flags.enabled,
        "kg_on_demand_enabled": kg_on_demand_enabled,
    }
    trace_conversation_id = _dify_trace_conversation_id(
        request,
        body,
        db=db,
        tenant_id=actor.tenant_id,
        account_id=actor.account_id,
    )
    trace_request_id = _dify_trace_request_id(request, body)

    response_cache_key: str | None = None
    response_cache_ttl_sec = max(
        0,
        int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC", 30) or 0),
    )
    response_cache_max_entries = max(
        0,
        int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES", 512) or 0),
    )
    response_cache_enabled = (
        bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED", True))
        and response_cache_ttl_sec > 0
        and response_cache_max_entries > 0
    )
    singleflight_enabled = bool(
        getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED", True)
    )
    stage_timings_ms: dict[str, Any] = {}
    if response_cache_enabled or singleflight_enabled:
        cache_token_started = time.perf_counter()
        try:
            corpus_token = _resolve_dify_response_cache_corpus_token(
                db=db,
                tenant_id=actor.tenant_id,
                dataset_ids=dataset_ids,
            )
        finally:
            with contextlib.suppress(Exception):
                db.rollback()
        stage_timings_ms["response_cache_corpus_token_ms"] = round(
            (time.perf_counter() - cache_token_started) * 1000,
            2,
        )
        if corpus_token:
            response_cache_key = _build_dify_response_cache_key(
                actor=actor,
                knowledge_id=body.knowledge_id,
                query=body.query,
                retrieval_setting=body.retrieval_setting,
                metadata_condition=body.metadata_condition,
                scope_plan=scope_plan,
                top_k=top_k,
                candidate_top_k=candidate_top_k,
                score_threshold=score_threshold,
                policy_plugin_refs=policy_plugin_refs,
                corpus_token=corpus_token,
            )
            cached_records = (
                _dify_response_cache.get(response_cache_key, ttl_sec=response_cache_ttl_sec)
                if response_cache_enabled
                else None
            )
            if cached_records is not None:
                elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
                response_records = [DifyExternalKnowledgeRecord(**record) for record in cached_records]
                logger.info(
                    "Dify external retrieval cache hit client_ip_hash=%s knowledge_id_hash=%s query_hash=%s "
                    "top_k=%s candidate_top_k=%s dataset_count=%s records=%s elapsed_ms=%s",
                    log_extra_base["client_ip_hash"],
                    log_extra_base["knowledge_id_hash"],
                    log_extra_base["query_hash"],
                    top_k,
                    candidate_top_k,
                    len(dataset_ids),
                    len(response_records),
                    elapsed_ms,
                    extra={
                        **log_extra_base,
                        "phase": "cache_hit",
                        "record_count": len(response_records),
                        "elapsed_ms": elapsed_ms,
                        "response_cache_hit": True,
                    },
                )
                _log_dify_external_rag_trace(
                    tenant_id=actor.tenant_id,
                    conversation_id=trace_conversation_id,
                    request_id=trace_request_id,
                    question=body.query,
                    response_records=response_records,
                    top_k=top_k,
                    candidate_top_k=candidate_top_k,
                    retrieval_path="cache_hit",
                    elapsed_ms=elapsed_ms,
                    metadata_anchor_fallback_count=0,
                    mixed_intent_query_count=0,
                    retrieval_queries=[{"kind": "main", "query": body.query, "path": "cache_hit", "ok": True}],
                    dify_message_id=body.dify_message_id,
                    dify_workflow_run_id=body.dify_workflow_run_id,
                )
                return DifyExternalKnowledgeResponse(records=response_records)

    singleflight_key = response_cache_key if singleflight_enabled else None
    singleflight_leader = False
    if singleflight_key:
        singleflight_wait_started = time.perf_counter()
        singleflight_leader, shared_payload = await _acquire_or_wait_for_inflight_response(singleflight_key)
        if not singleflight_leader:
            shared_payload = shared_payload or {}
            shared_records = shared_payload.get("records")
            response_records = [
                DifyExternalKnowledgeRecord(**record)
                for record in (shared_records if isinstance(shared_records, list) else [])
                if isinstance(record, dict)
            ]
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            stage_timings_ms["singleflight_wait_ms"] = round(
                (time.perf_counter() - singleflight_wait_started) * 1000,
                2,
            )
            logger.info(
                "Dify external retrieval singleflight hit client_ip_hash=%s knowledge_id_hash=%s "
                "query_hash=%s records=%s elapsed_ms=%s",
                log_extra_base["client_ip_hash"],
                log_extra_base["knowledge_id_hash"],
                log_extra_base["query_hash"],
                len(response_records),
                elapsed_ms,
                extra={
                    **log_extra_base,
                    "phase": "singleflight_hit",
                    "record_count": len(response_records),
                    "elapsed_ms": elapsed_ms,
                    "singleflight_hit": True,
                    "stage_timings_ms": stage_timings_ms,
                },
            )
            _log_dify_external_rag_trace(
                tenant_id=actor.tenant_id,
                conversation_id=trace_conversation_id,
                request_id=trace_request_id,
                question=body.query,
                response_records=response_records,
                top_k=top_k,
                candidate_top_k=candidate_top_k,
                retrieval_path="singleflight_hit",
                elapsed_ms=elapsed_ms,
                metadata_anchor_fallback_count=0,
                mixed_intent_query_count=0,
                retrieval_queries=[
                    {"kind": "main", "query": body.query, "path": "singleflight_hit", "ok": True}
                ],
                dify_message_id=body.dify_message_id,
                dify_workflow_run_id=body.dify_workflow_run_id,
            )
            return DifyExternalKnowledgeResponse(records=response_records)

    records: list[dict[str, Any]] = []
    citation_count = 0
    primary_citation_count = 0
    expansion_citation_count = 0
    mixed_intent_citation_count = 0
    mixed_intent_query_count = 0
    metadata_anchor_fallback_count = 0
    retrieval_path = "rag:primary_scope" if primary_scope_enabled else "rag"
    kg_on_demand_triggered = False
    kg_on_demand_skipped = False
    trace_queries: list[dict[str, Any]] = []

    def _set_main_trace_query(path: str, *, ok: bool = True) -> None:
        entry = {
            "kind": "main",
            "query": body.query,
            "path": path,
            "ok": ok,
        }
        if trace_queries and str(trace_queries[0].get("kind") or "") == "main":
            trace_queries[0] = entry
            return
        trace_queries.insert(0, entry)

    try:
        query_prefers_question_anchor = _query_prefers_question_anchor(
            body.query,
            policy_plugin_refs=policy_plugin_refs,
        )
        query_prefers_service_anchor = _query_prefers_service_anchor(
            body.query,
            policy_plugin_refs=policy_plugin_refs,
        )
        metadata_anchor_db_fallback_enabled = bool(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED", False)
        )
        metadata_anchor_total_budget_ms = max(
            0,
            int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS", 1500) or 0),
        )
        metadata_anchor_budget_spent_ms = 0.0

        async def _run_metadata_anchor_fallback(**kwargs: Any) -> list[dict[str, Any]]:
            nonlocal metadata_anchor_budget_spent_ms
            call_kwargs = dict(kwargs)
            call_kwargs.pop("db", None)
            fallback_started = time.perf_counter()
            budget_deadline: float | None = None
            if not fast_latency_profile and metadata_anchor_total_budget_ms:
                remaining_ms = metadata_anchor_total_budget_ms - int(metadata_anchor_budget_spent_ms)
                if remaining_ms <= 0:
                    return []
                configured_call_budget = call_kwargs.get("max_elapsed_ms")
                if configured_call_budget is not None and int(configured_call_budget or 0) > 0:
                    remaining_ms = min(remaining_ms, int(configured_call_budget))
                call_kwargs["max_elapsed_ms"] = remaining_ms
                budget_deadline = fallback_started + remaining_ms / 1000

            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            try:
                if budget_deadline is None:
                    return await run_blocking_retrieval_call(
                        _metadata_anchor_db_fallback_records_with_managed_session,
                        budget_deadline=None,
                        **call_kwargs,
                    )
                remaining_sec = budget_deadline - time.perf_counter()
                if remaining_sec <= 0:
                    return []
                try:
                    return await asyncio.wait_for(
                        run_blocking_retrieval_call(
                            _metadata_anchor_db_fallback_records_with_managed_session,
                            budget_deadline=budget_deadline,
                            **call_kwargs,
                        ),
                        timeout=remaining_sec,
                    )
                except TimeoutError:
                    logger.info(
                        "Dify metadata anchor fallback exceeded request budget query_hash=%s",
                        _diagnostic_query_hash(str(call_kwargs.get("query") or "")),
                    )
                    return []
            finally:
                metadata_anchor_budget_spent_ms += max(
                    0.0,
                    (time.perf_counter() - fallback_started) * 1000,
                )
                stage_timings_ms["metadata_anchor_budget_spent_ms"] = round(
                    metadata_anchor_budget_spent_ms,
                    2,
                )

        mixed_intent_supplement_enabled = (
            not fast_latency_profile
            and bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED", True))
        )
        metadata_anchor_preflight_enabled = (
            bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED", False))
            and metadata_anchor_db_fallback_enabled
            and (
                not fast_latency_profile
                or _query_has_specific_fast_metadata_anchor_candidate(body.query, policy_plugin_refs=policy_plugin_refs)
            )
            and not metadata_filter
            and _query_allows_metadata_anchor_preflight(
                body.query,
                query_prefers_question_anchor=query_prefers_question_anchor,
                query_prefers_service_anchor=query_prefers_service_anchor,
                policy_plugin_refs=policy_plugin_refs,
            )
        )
        if metadata_anchor_preflight_enabled:
            preflight_started = time.perf_counter()
            metadata_anchor_records = await _run_metadata_anchor_fallback(
                db=db,
                tenant_id=actor.tenant_id,
                dataset_ids=metadata_anchor_dataset_ids,
                query=body.query,
                top_k=top_k,
                policy_plugin_refs=policy_plugin_refs,
                existing_records=[],
                metadata_filter=metadata_filter,
                statement_timeout_ms_override=(
                    int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS", 600) or 0)
                    if fast_latency_profile
                    else None
                ),
                max_elapsed_ms=(
                    int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS", 900) or 0)
                    if fast_latency_profile
                    else None
                ),
            )
            if query_prefers_service_anchor and _query_has_quoted_anchor_candidate(body.query):
                metadata_anchor_records = [
                    record
                    for record in metadata_anchor_records
                    if _record_matches_quoted_query_anchor_for_policy(
                        record,
                        query=body.query,
                        policy_plugin_refs=policy_plugin_refs,
                    )
                ]
            if (
                _query_has_mixed_intent_for_policy(body.query, policy_plugin_refs=policy_plugin_refs)
                and _query_has_quoted_anchor_candidate(body.query)
            ):
                metadata_anchor_records = _compact_mixed_intent_exact_anchor_records(
                    metadata_anchor_records,
                    query=body.query,
                    top_k=top_k,
                    policy_plugin_refs=policy_plugin_refs,
                )
            if query_prefers_service_anchor:
                has_preflight_anchor = _records_have_confident_metadata_anchor(
                    metadata_anchor_records,
                    query=body.query,
                    policy_plugin_refs=policy_plugin_refs,
                )
            else:
                has_preflight_anchor = _records_have_strong_question_anchor(
                    metadata_anchor_records,
                    query=body.query,
                    policy_plugin_refs=policy_plugin_refs,
                )
            stage_timings_ms["metadata_preflight_ms"] = round(
                (time.perf_counter() - preflight_started) * 1000,
                2,
            )
            stage_timings_ms["metadata_preflight_records"] = len(metadata_anchor_records)
            stage_timings_ms["metadata_preflight_accepted"] = bool(has_preflight_anchor)
            if has_preflight_anchor:
                metadata_anchor_fallback_count = len(metadata_anchor_records)
                records.extend(metadata_anchor_records)
                retrieval_path = "metadata_anchor:preflight"
                _set_main_trace_query(retrieval_path)

        if (
            not records
            and mixed_intent_supplement_enabled
            and metadata_anchor_db_fallback_enabled
            and _query_has_mixed_intent_for_policy(body.query, policy_plugin_refs=policy_plugin_refs)
            and not _query_has_quoted_anchor_candidate(body.query)
        ):
            mixed_intent_queries = _mixed_intent_retrieval_queries(
                body.query,
                policy_plugin_refs=policy_plugin_refs,
            )
            mixed_preflight_records: list[dict[str, Any]] = []
            mixed_preflight_query_count = 0
            mixed_preflight_complete = True
            mixed_preflight_trace_queries: list[dict[str, Any]] = []
            mixed_intent_subquery_top_k = _resolve_mixed_intent_subquery_top_k(
                response_top_k=top_k,
                candidate_top_k=candidate_top_k,
            )
            for subquery in mixed_intent_queries:
                subquery_prefers_question_anchor = _query_prefers_question_anchor(
                    subquery,
                    policy_plugin_refs=policy_plugin_refs,
                )
                subquery_prefers_service_anchor = _query_prefers_service_anchor(
                    subquery,
                    policy_plugin_refs=policy_plugin_refs,
                )
                if not _query_allows_metadata_anchor_preflight(
                    subquery,
                    query_prefers_question_anchor=subquery_prefers_question_anchor,
                    query_prefers_service_anchor=subquery_prefers_service_anchor,
                    policy_plugin_refs=policy_plugin_refs,
                ):
                    mixed_preflight_complete = False
                    break
                subquery_anchor_records = await _run_metadata_anchor_fallback(
                    db=db,
                    tenant_id=actor.tenant_id,
                    dataset_ids=metadata_anchor_dataset_ids,
                    query=subquery,
                    top_k=mixed_intent_subquery_top_k,
                    policy_plugin_refs=policy_plugin_refs,
                    existing_records=[],
                    metadata_filter=metadata_filter,
                    prefer_question_anchor_first=True,
                )
                subquery_anchor_records = _filter_records_by_mixed_intent_subject_anchor(
                    subquery_anchor_records,
                    subquery=subquery,
                    policy_plugin_refs=policy_plugin_refs,
                )
                if not subquery_anchor_records:
                    mixed_preflight_complete = False
                    break
                mixed_preflight_query_count += 1
                mixed_preflight_trace_queries.append(
                    {
                        "kind": "subq",
                        "query": subquery,
                        "path": "metadata_anchor:mixed_preflight_subquery",
                        "ok": True,
                    }
                )
                mixed_preflight_records.extend(_tag_mixed_intent_records(subquery_anchor_records, subquery=subquery))
            if mixed_preflight_records and mixed_preflight_complete:
                mixed_intent_query_count += mixed_preflight_query_count
                metadata_anchor_fallback_count += len(mixed_preflight_records)
                records.extend(mixed_preflight_records)
                retrieval_path = "metadata_anchor:mixed_preflight"
                _set_main_trace_query(retrieval_path)
                trace_queries.extend(mixed_preflight_trace_queries)

        if not records:
            primary_retrieve_started = time.perf_counter()
            primary_citations = await _retrieve_dataset_citations(
                db=db,
                tenant_id=actor.tenant_id,
                account_id=actor.account_id,
                dataset_ids=primary_dataset_ids,
                query=body.query,
                top_k=candidate_top_k,
                requested_top_k=top_k,
                score_threshold=score_threshold,
                metadata_filter=metadata_filter,
                enable_kg_query_expansion=primary_kg_flags.enable_query_expansion,
                enable_kg_chunk_injection=primary_kg_flags.enable_chunk_injection,
                kg_chunk_injection_max_chunks=primary_kg_flags.chunk_injection_max_chunks,
                enable_kg_chunk_boost=primary_kg_flags.enable_chunk_boost,
                kg_chunk_boost_weight=primary_kg_flags.chunk_boost_weight,
                kg_chunk_boost_max_promoted=primary_kg_flags.chunk_boost_max_promoted,
                enable_reranker=external_reranker_enabled,
                retrieval_mode="vector" if fast_latency_profile else "hybrid",
            )
            stage_timings_ms["primary_retrieve_ms"] = round(
                (time.perf_counter() - primary_retrieve_started) * 1000,
                2,
            )
            primary_citation_count = len(primary_citations)
            _set_main_trace_query(retrieval_path, ok=bool(primary_citations))
            records_started = time.perf_counter()
            records.extend(
                await _records_from_citations_with_managed_hydration(
                    db=db,
                    tenant_id=actor.tenant_id,
                    citations=primary_citations,
                    fallback_dataset_id=primary_dataset_ids[0] if primary_dataset_ids else None,
                    query=body.query,
                    policy_plugin_refs=policy_plugin_refs,
                )
            )
            stage_timings_ms["primary_records_from_citations_ms"] = round(
                (time.perf_counter() - records_started) * 1000,
                2,
            )
            mixed_intent_supplement_skipped = _records_have_exact_anchor_full_answer(
                records,
                query=body.query,
                policy_plugin_refs=policy_plugin_refs,
            )
            if mixed_intent_supplement_skipped:
                retrieval_path = f"{retrieval_path}:mixed_intent_skip_exact_anchor"
            if (
                mixed_intent_supplement_enabled
                and not mixed_intent_supplement_skipped
            ):
                mixed_intent_queries = _mixed_intent_retrieval_queries(
                    body.query,
                    policy_plugin_refs=policy_plugin_refs,
                )
                mixed_intent_subquery_top_k = _resolve_mixed_intent_subquery_top_k(
                    response_top_k=top_k,
                    candidate_top_k=candidate_top_k,
                )
                for subquery in mixed_intent_queries:
                    subquery_prefers_question_anchor = _query_prefers_question_anchor(
                        subquery,
                        policy_plugin_refs=policy_plugin_refs,
                    )
                    subquery_prefers_service_anchor = _query_prefers_service_anchor(
                        subquery,
                        policy_plugin_refs=policy_plugin_refs,
                    )
                    subquery_anchor_records: list[dict[str, Any]] = []
                    subquery_metadata_preflight_enabled = bool(
                        metadata_anchor_db_fallback_enabled
                        and _query_allows_metadata_anchor_preflight(
                            subquery,
                            query_prefers_question_anchor=subquery_prefers_question_anchor,
                            query_prefers_service_anchor=subquery_prefers_service_anchor,
                            policy_plugin_refs=policy_plugin_refs,
                        )
                    )
                    if subquery_metadata_preflight_enabled:
                        subquery_anchor_records = await _run_metadata_anchor_fallback(
                            db=db,
                            tenant_id=actor.tenant_id,
                            dataset_ids=primary_dataset_ids,
                            query=subquery,
                            top_k=mixed_intent_subquery_top_k,
                            policy_plugin_refs=policy_plugin_refs,
                            existing_records=[],
                            metadata_filter=metadata_filter,
                            prefer_question_anchor_first=not _query_has_quoted_anchor_candidate(body.query),
                        )
                        subquery_anchor_records = _filter_records_by_mixed_intent_subject_anchor(
                            subquery_anchor_records,
                            subquery=subquery,
                            policy_plugin_refs=policy_plugin_refs,
                        )
                    if subquery_anchor_records:
                        mixed_intent_query_count += 1
                        metadata_anchor_fallback_count += len(subquery_anchor_records)
                        trace_queries.append(
                            {
                                "kind": "subq",
                                "query": subquery,
                                "path": "metadata_anchor:mixed_intent_subquery",
                                "ok": True,
                            }
                        )
                        records.extend(_tag_mixed_intent_records(subquery_anchor_records, subquery=subquery))
                        continue
                    subquery_citations = await _retrieve_dataset_citations(
                        db=db,
                        tenant_id=actor.tenant_id,
                        account_id=actor.account_id,
                        dataset_ids=primary_dataset_ids,
                        query=subquery,
                        top_k=mixed_intent_subquery_top_k,
                        requested_top_k=mixed_intent_subquery_top_k,
                        score_threshold=score_threshold,
                        metadata_filter=metadata_filter,
                        enable_kg_query_expansion=primary_kg_flags.enable_query_expansion,
                        enable_kg_chunk_injection=primary_kg_flags.enable_chunk_injection,
                        kg_chunk_injection_max_chunks=primary_kg_flags.chunk_injection_max_chunks,
                        enable_kg_chunk_boost=primary_kg_flags.enable_chunk_boost,
                        kg_chunk_boost_weight=primary_kg_flags.chunk_boost_weight,
                        kg_chunk_boost_max_promoted=primary_kg_flags.chunk_boost_max_promoted,
                        enable_reranker=False,
                    )
                    trace_queries.append(
                        {
                            "kind": "subq",
                            "query": subquery,
                            "path": "rag:mixed_intent_subquery",
                            "ok": bool(subquery_citations),
                        }
                    )
                    mixed_intent_query_count += 1
                    mixed_intent_citation_count += len(subquery_citations)
                    subquery_records = await _records_from_citations_with_managed_hydration(
                        db=db,
                        tenant_id=actor.tenant_id,
                        citations=subquery_citations,
                        fallback_dataset_id=primary_dataset_ids[0] if primary_dataset_ids else None,
                        query=subquery,
                        hydration_query=body.query,
                        policy_plugin_refs=policy_plugin_refs,
                    )
                    records.extend(_tag_mixed_intent_records(subquery_records, subquery=subquery))
                if mixed_intent_query_count:
                    retrieval_path = f"{retrieval_path}:mixed_intent"
            if requested_kg_flags.enabled and kg_on_demand_enabled:
                if _records_can_skip_kg_on_demand(
                    records,
                    query=body.query,
                    policy_plugin_refs=policy_plugin_refs,
                ):
                    kg_on_demand_skipped = True
                    retrieval_path = f"{retrieval_path}:kg_on_demand_skip"
                else:
                    kg_records = await _dify_kg_on_demand_records(
                        db=db,
                        tenant_id=actor.tenant_id,
                        account_id=actor.account_id,
                        dataset_ids=primary_dataset_ids,
                        query=body.query,
                        requested_kg_flags=requested_kg_flags,
                        policy_plugin_refs=policy_plugin_refs,
                    )
                    if kg_records:
                        kg_on_demand_triggered = True
                        retrieval_path = f"{retrieval_path}:kg_on_demand"
                        records.extend(kg_records)
                    else:
                        kg_on_demand_skipped = True
                        retrieval_path = f"{retrieval_path}:kg_on_demand_empty"

            if (not fast_latency_profile) and expansion_dataset_ids and not _records_meet_primary_scope(
                records,
                query=body.query,
                policy_plugin_refs=policy_plugin_refs,
            ):
                retrieval_path = "rag:primary_scope+expansion_scope"
                expansion_citations = await _retrieve_dataset_citations(
                    db=db,
                    tenant_id=actor.tenant_id,
                    account_id=actor.account_id,
                    dataset_ids=expansion_dataset_ids,
                    query=body.query,
                    top_k=candidate_top_k,
                    requested_top_k=top_k,
                    score_threshold=score_threshold,
                    metadata_filter=metadata_filter,
                    enable_kg_query_expansion=requested_kg_flags.enable_query_expansion,
                    enable_kg_chunk_injection=requested_kg_flags.enable_chunk_injection,
                    kg_chunk_injection_max_chunks=requested_kg_flags.chunk_injection_max_chunks,
                    enable_kg_chunk_boost=requested_kg_flags.enable_chunk_boost,
                    kg_chunk_boost_weight=requested_kg_flags.chunk_boost_weight,
                    kg_chunk_boost_max_promoted=requested_kg_flags.chunk_boost_max_promoted,
                    enable_reranker=external_reranker_enabled,
                )
                expansion_citation_count = len(expansion_citations)
                records.extend(
                    await _records_from_citations_with_managed_hydration(
                        db=db,
                        tenant_id=actor.tenant_id,
                        citations=expansion_citations,
                        fallback_dataset_id=expansion_dataset_ids[0] if expansion_dataset_ids else None,
                        query=body.query,
                        policy_plugin_refs=policy_plugin_refs,
                    )
                )

            if (not fast_latency_profile) and not _records_can_skip_metadata_anchor_fallback(
                records,
                query=body.query,
                policy_plugin_refs=policy_plugin_refs,
            ):
                metadata_anchor_records = await _run_metadata_anchor_fallback(
                    db=db,
                    tenant_id=actor.tenant_id,
                    dataset_ids=metadata_anchor_dataset_ids,
                    query=body.query,
                    top_k=top_k,
                    policy_plugin_refs=policy_plugin_refs,
                    existing_records=records,
                    metadata_filter=metadata_filter,
                )
                if metadata_anchor_records:
                    metadata_anchor_fallback_count = len(metadata_anchor_records)
                    records.extend(metadata_anchor_records)
                    retrieval_path = f"{retrieval_path}+metadata_anchor"

        citation_count = primary_citation_count + expansion_citation_count + mixed_intent_citation_count
        postprocess_started = time.perf_counter()
        records = _dedupe_records(records, query=body.query, policy_plugin_refs=policy_plugin_refs)
        _sort_records_for_query(records, query=body.query, policy_plugin_refs=policy_plugin_refs)
        if external_reranker_enabled:
            with contextlib.suppress(Exception):
                db.rollback()
            records = await _final_rerank_records_for_query(
                records,
                query=body.query,
                top_k=top_k,
                policy_plugin_refs=policy_plugin_refs,
            )
        policy_diagnostics = _records_retrieval_policy_diagnostics(
            records,
            query=body.query,
            policy_plugin_refs=policy_plugin_refs,
        )
        compacted_records = _compact_records_for_response(
            records,
            query=body.query,
            top_k=response_top_k,
            policy_plugin_refs=policy_plugin_refs,
        )
        if fast_latency_profile:
            compacted_records = _compact_fast_records_for_response(
                compacted_records,
                query=body.query,
                top_k=response_top_k,
                policy_plugin_refs=policy_plugin_refs,
            )
        response_records = [DifyExternalKnowledgeRecord(**record) for record in compacted_records]
        stage_timings_ms["postprocess_ms"] = round((time.perf_counter() - postprocess_started) * 1000, 2)
        serialized_response_records = [record.model_dump(mode="json") for record in response_records]
        if response_cache_enabled and response_cache_key is not None:
            _dify_response_cache.set(
                response_cache_key,
                serialized_response_records,
                ttl_sec=response_cache_ttl_sec,
                max_entries=response_cache_max_entries,
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        record_count = len(response_records)
        logger.info(
            "Dify external retrieval completed client_ip_hash=%s knowledge_id_hash=%s query_hash=%s "
            "top_k=%s candidate_top_k=%s score_threshold=%s dataset_count=%s "
            "primary_dataset_count=%s expansion_dataset_count=%s citations=%s primary_citations=%s "
            "expansion_citations=%s candidate_records=%s records=%s elapsed_ms=%s metadata_filter=%s "
            "retrieval_path=%s metadata_anchor_fallback_records=%s policy_records=%s "
            "policy_boosted_records=%s policy_boost_field_records=%s "
            "policy_query_expansion_records=%s policy_rerank_feature_records=%s "
            "policy_anchor_mismatch_records=%s stage_timings=%s",
            log_extra_base["client_ip_hash"],
            log_extra_base["knowledge_id_hash"],
            log_extra_base["query_hash"],
            top_k,
            candidate_top_k,
            score_threshold,
            len(dataset_ids),
            len(primary_dataset_ids),
            len(expansion_dataset_ids),
            citation_count,
            primary_citation_count,
            expansion_citation_count,
            len(records),
            record_count,
            elapsed_ms,
            bool(metadata_filter),
            retrieval_path,
            metadata_anchor_fallback_count,
            policy_diagnostics["retrieval_policy_record_count"],
            policy_diagnostics["retrieval_policy_boosted_record_count"],
            policy_diagnostics["retrieval_policy_boost_field_record_count"],
            policy_diagnostics["retrieval_policy_query_expansion_record_count"],
            policy_diagnostics["retrieval_policy_rerank_feature_record_count"],
            policy_diagnostics["retrieval_policy_anchor_mismatch_record_count"],
            stage_timings_ms,
            extra={
                **log_extra_base,
                "phase": "finished",
                "citation_count": citation_count,
                "primary_citation_count": primary_citation_count,
                "expansion_citation_count": expansion_citation_count,
                "mixed_intent_query_count": mixed_intent_query_count,
                "mixed_intent_citation_count": mixed_intent_citation_count,
                "candidate_record_count": len(records),
                "record_count": record_count,
                "elapsed_ms": elapsed_ms,
                "retrieval_path": retrieval_path,
                "metadata_anchor_fallback_count": metadata_anchor_fallback_count,
                "kg_on_demand_triggered": kg_on_demand_triggered,
                "kg_on_demand_skipped": kg_on_demand_skipped,
                **policy_diagnostics,
            },
        )
        _log_dify_external_rag_trace(
            tenant_id=actor.tenant_id,
            conversation_id=trace_conversation_id,
            request_id=trace_request_id,
            question=body.query,
            response_records=response_records,
            top_k=top_k,
            candidate_top_k=candidate_top_k,
            retrieval_path=retrieval_path,
            elapsed_ms=elapsed_ms,
            metadata_anchor_fallback_count=metadata_anchor_fallback_count,
            mixed_intent_query_count=mixed_intent_query_count,
            retrieval_queries=trace_queries,
            dify_message_id=body.dify_message_id,
            dify_workflow_run_id=body.dify_workflow_run_id,
        )
        if singleflight_key and singleflight_leader:
            resolve_inflight_response(
                singleflight_key,
                {"records": serialized_response_records},
            )
        return DifyExternalKnowledgeResponse(records=response_records)
    except asyncio.CancelledError:
        if singleflight_key and singleflight_leader:
            reject_inflight_response(
                singleflight_key,
                InflightResponseLeaderCancelledError("singleflight leader request cancelled"),
            )
        raise
    except Exception as exc:
        if singleflight_key and singleflight_leader:
            reject_inflight_response(singleflight_key, exc)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        policy_diagnostics = _records_retrieval_policy_diagnostics(
            records,
            query=body.query,
            policy_plugin_refs=policy_plugin_refs,
        )
        logger.exception(
            "Dify external retrieval failed client_ip_hash=%s knowledge_id_hash=%s query_hash=%s "
            "top_k=%s candidate_top_k=%s score_threshold=%s dataset_count=%s "
            "primary_dataset_count=%s expansion_dataset_count=%s citations=%s records=%s elapsed_ms=%s "
            "metadata_filter=%s retrieval_path=%s metadata_anchor_fallback_records=%s "
            "policy_records=%s policy_boosted_records=%s "
            "policy_boost_field_records=%s policy_query_expansion_records=%s "
            "policy_rerank_feature_records=%s policy_anchor_mismatch_records=%s",
            log_extra_base["client_ip_hash"],
            log_extra_base["knowledge_id_hash"],
            log_extra_base["query_hash"],
            top_k,
            candidate_top_k,
            score_threshold,
            len(dataset_ids),
            len(primary_dataset_ids),
            len(expansion_dataset_ids),
            citation_count,
            len(records),
            elapsed_ms,
            bool(metadata_filter),
            retrieval_path,
            metadata_anchor_fallback_count,
            policy_diagnostics["retrieval_policy_record_count"],
            policy_diagnostics["retrieval_policy_boosted_record_count"],
            policy_diagnostics["retrieval_policy_boost_field_record_count"],
            policy_diagnostics["retrieval_policy_query_expansion_record_count"],
            policy_diagnostics["retrieval_policy_rerank_feature_record_count"],
            policy_diagnostics["retrieval_policy_anchor_mismatch_record_count"],
            extra={
                **log_extra_base,
                "phase": "failed",
                "citation_count": citation_count,
                "mixed_intent_query_count": mixed_intent_query_count,
                "mixed_intent_citation_count": mixed_intent_citation_count,
                "record_count": len(records),
                "elapsed_ms": elapsed_ms,
                "retrieval_path": retrieval_path,
                "metadata_anchor_fallback_count": metadata_anchor_fallback_count,
                "kg_on_demand_triggered": kg_on_demand_triggered,
                "kg_on_demand_skipped": kg_on_demand_skipped,
                **policy_diagnostics,
            },
        )
        raise

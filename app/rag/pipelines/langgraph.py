"""
LangGraph pipeline for RAG (retrieve -> generate).

This module is the canonical home for the non-streaming LangGraph-based runner.
`app.rag.graph` remains as a backward-compatible import path.

Refactored to use LangGraph 1.0+ Functional API with @entrypoint and @task decorators.
"""


import concurrent.futures
import json
import logging
import time
from dataclasses import dataclass
from functools import partial
from typing import Any, Dict, List, Optional, TypedDict
from uuid import UUID, uuid4

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.config import get_stream_writer

# LangGraph 1.0+ Functional API imports
from langgraph.func import entrypoint, task
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import CachePolicy, RetryPolicy

from app.core.config import settings
from app.core.pii_redaction import pii_redaction_enabled, redact_text
from app.core.token_utils import num_tokens_from_string, truncate
from app.rag.checkpointer.factory import get_checkpointer
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.claim_evidence import build_claim_evidence_map
from app.rag.core.conversation import format_history_text
from app.rag.core.text import (
    build_abstain_followup,
    extract_evidence_text,
    guess_retrieval_mode,
    is_claim_supported,
    normalize_retrieval_mode,
    parse_json_from_text,
    should_rewrite_query,
    split_into_claims,
)
from app.rag.engine import get_rag_engine
from app.rag.retriever import hybrid_retriever
from app.rag.store.factory import get_langgraph_store
from app.services.prompt_resolver import resolve_prompt_template

logger = logging.getLogger(__name__)


@dataclass
class RAGRuntimeContext:
    """Runtime-only context passed to LangGraph nodes (not persisted in state)."""

    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    tenant_id: Optional[str] = None
    account_id: Optional[str] = None
    user_role: Optional[str] = None


class RAGState(TypedDict, total=False):
    """Graph state: question, history, docs, citations, answer, meta.

    Using TypedDict for better type hints and IDE support.
    """
    question: str
    history: List[Dict[str, str]]
    document_ids: Optional[List[UUID]]
    tenant_id: Optional[UUID]
    top_k: int
    score_threshold: float
    retrieval_mode: str
    alpha: float
    enable_weight_rerank: bool
    vector_weight: float
    keyword_weight: float
    mmr_lambda: float
    enable_reranker: bool
    reranker_provider: Optional[str]
    reranker_top_n: int
    metadata_filter: Optional[Dict[str, Any]]
    format_instructions: str
    structured_output: bool
    structured_preset: Optional[str]
    prompt_template_content: Optional[str]
    prompt_template_id: Optional[str]
    prompt_template_key: Optional[str]
    prompt_ab_experiment_key: Optional[str]
    prompt_ab_variant: Optional[str]
    # Optional: TAG injection (table_store query results) passed in by API layer.
    tag_docs: Optional[List[Document]]
    tag_meta: Optional[Dict[str, Any]]
    # Output fields
    query_for_retrieval: Optional[str]
    docs: Optional[List[Document]]
    citations: Optional[List[Dict[str, Any]]]
    answer: Optional[str]
    route: Optional[str]
    model_used: Optional[str]
    routing_reason: Optional[str]
    metrics: Optional[Dict[str, Any]]
    abstain_triggered: Optional[bool]
    abstain_reason: Optional[str]


_RAG_TASK_RETRY_POLICY = RetryPolicy(
    max_attempts=max(1, int(getattr(settings, "RAG_GRAPH_MAX_RETRIES", 0) or 0) + 1),
    retry_on=lambda exc: not isinstance(exc, (ValueError, TypeError, KeyError)),
)


_RAG_RETRIEVE_CACHE_TTL_SEC = max(0, int(getattr(settings, "RAG_GRAPH_CACHE_TTL_SEC", 0) or 0))


def _retrieve_cache_key(state: Dict[str, Any]) -> str:
    history_text = format_history_text(state.get("history") or [], window=settings.CHAT_HISTORY_WINDOW)
    history_text = history_text[:2000]
    doc_ids = state.get("document_ids") or []
    doc_ids_key = ",".join(sorted(str(x) for x in doc_ids))[:2000]
    # Security: retrieval is scoped by ACL and dataset; cache key MUST include account_id/dataset_id
    # to avoid cross-user leakage when cache is enabled.
    account_id = str(state.get("account_id") or "")[:200]
    dataset_id = str(state.get("dataset_id") or "")
    embedding_space = ""
    try:
        from app.rag.embedding.utils import current_embedding_space_hash

        embedding_space = current_embedding_space_hash()
    except Exception:
        embedding_space = ""
    key_obj = {
        "question": (state.get("question") or "")[:800],
        "history": history_text,
        "tenant_id": str(state.get("tenant_id") or ""),
        "account_id": account_id,
        "dataset_id": dataset_id,
        "document_ids": doc_ids_key,
        "embedding_space_hash": embedding_space,
        "top_k": int(state.get("top_k") or settings.RETRIEVAL_TOP_K),
        "score_threshold": float(state.get("score_threshold") or settings.SIMILARITY_THRESHOLD),
        "retrieval_mode": str(state.get("retrieval_mode") or ""),
        "alpha": float(state.get("alpha") or 0.0),
        "enable_weight_rerank": bool(state.get("enable_weight_rerank")),
        "vector_weight": float(state.get("vector_weight") or 0.0),
        "keyword_weight": float(state.get("keyword_weight") or 0.0),
        "mmr_lambda": float(state.get("mmr_lambda") or 0.0),
        "enable_reranker": bool(state.get("enable_reranker")),
        "reranker_provider": str(state.get("reranker_provider") or ""),
        "reranker_top_n": int(state.get("reranker_top_n") or 0),
        "metadata_filter": state.get("metadata_filter") or None,
    }
    return json.dumps(key_obj, ensure_ascii=False, sort_keys=True, default=str)


_RAG_RETRIEVE_CACHE_POLICY = (
    CachePolicy(key_func=_retrieve_cache_key, ttl=_RAG_RETRIEVE_CACHE_TTL_SEC)
    if _RAG_RETRIEVE_CACHE_TTL_SEC > 0
    else None
)


def _build_context(docs: List[Document], *, query: str | None = None) -> str:
    """Format retrieved document context."""
    if not docs:
        return "No relevant reference materials found."
    parts = []
    max_per_chunk_chars = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0))
    max_total_chars = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0))
    max_per_chunk_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0) or 0))
    max_total_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0) or 0))
    total_chars = 0
    total_tokens = 0
    for idx, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        source = meta.get("source", "Unknown")
        page_info = None
        page_raw = meta.get("page")
        try:
            page_int = int(page_raw) if page_raw is not None else None
            if page_int and page_int > 0:
                page_info = f"Page {page_int}"
        except Exception:
            page_info = None
        header = meta.get("header_path") or meta.get("header_context")
        retrieval_role = meta.get("retrieval_role")
        role_info = None
        if retrieval_role == "neighbor":
            role_info = "neighbor"
        elif retrieval_role:
            role_info = str(retrieval_role)
        raw_content = (doc.page_content or "").strip()
        content = raw_content
        if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) and query:
            content = extract_evidence_text(
                raw_content,
                str(query),
                max_chars=(max_per_chunk_chars if not max_per_chunk_tokens else 0),
                max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
                min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
            )
        elif max_per_chunk_tokens:
            content = truncate(content, max_per_chunk_tokens)
        elif max_per_chunk_chars and len(content) > max_per_chunk_chars:
            content = content[:max_per_chunk_chars] + "..."
        info_parts = [str(source)]
        if page_info:
            info_parts.append(page_info)
        if header:
            info_parts.append(str(header))
        if role_info:
            info_parts.append(str(role_info))
        part = f"[Source {idx}: {' | '.join(info_parts)}]\n{content}"
        if max_total_tokens:
            part_tokens = num_tokens_from_string(part)
            if parts and (total_tokens + part_tokens) > max_total_tokens:
                break
            parts.append(part)
            total_tokens += part_tokens
            continue
        if max_total_chars and parts and (total_chars + len(part)) > max_total_chars:
            break
        parts.append(part)
        total_chars += len(part)
        if max_total_chars and total_chars >= max_total_chars:
            break
    return "\n\n".join(parts)


def _build_history_text(history: Optional[List[Dict[str, str]]]) -> str:
    """Compress history to readable text, keep only within window."""
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _run_with_retry(node_name: str, func, state: RAGState) -> RAGState:
    """Node-level retry + timeout (seconds)."""
    timeout = max(settings.RAG_GRAPH_TIMEOUT_SEC, 0) or None
    metrics = dict(state.get("metrics") or {})
    attempts = int(metrics.get(f"{node_name}_attempts", 0) or 0) + 1

    try:
        if timeout:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(func, state)
                result = fut.result(timeout=timeout)
        else:
            result = func(state)

        merged = dict(metrics)
        merged.update(result.get("metrics") or {})
        merged[f"{node_name}_attempts"] = attempts
        merged[f"{node_name}_retries"] = max(attempts - 1, 0)
        result["metrics"] = merged
        return result
    except Exception as exc:  # noqa: BLE001
        metrics[f"{node_name}_attempts"] = attempts
        metrics[f"{node_name}_retries"] = max(attempts - 1, 0)
        metrics[f"{node_name}_last_error"] = str(exc)[:300]
        state["metrics"] = metrics
        raise


def _retrieve_node(state: RAGState) -> RAGState:
    question = state["question"]
    history_text = _build_history_text(state.get("history"))
    engine = get_rag_engine()
    query_for_retrieval = question
    rewrite_elapsed = 0.0
    rewrite_used = False
    rewrite_model_used = None

    if (
        settings.ENABLE_QUERY_REWRITE
        and history_text != "(No conversation history)"
        and len(question) <= settings.QUERY_REWRITE_MAX_CHARS
        and should_rewrite_query(question)
    ):
        rewrite_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        rewrite_model_used = getattr(rewrite_llm, "model_name", None) or getattr(rewrite_llm, "model", None)
        try:
            rewrite_chain = (
                engine.rewrite_prompt  # type: ignore[attr-defined]
                | rewrite_llm.bind(temperature=settings.QUERY_REWRITE_TEMPERATURE)
                | StrOutputParser()
            )
            rw_start = time.time()
            rewritten = rewrite_chain.invoke({"history": history_text, "question": question})
            rewrite_elapsed = time.time() - rw_start
            rewritten = (rewritten or "").strip().strip('"')
            if rewritten:
                query_for_retrieval = rewritten
        except Exception:  # noqa: BLE001
            query_for_retrieval = question
            rewrite_elapsed = 0.0

        rewrite_used = query_for_retrieval != question

    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    request_retrieval_mode = normalize_retrieval_mode(requested_retrieval_mode)
    retrieval_mode_routed = False
    mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm == "auto":
        request_retrieval_mode = guess_retrieval_mode(query_for_retrieval)
        retrieval_mode_routed = True
        mode_norm = str(request_retrieval_mode or "hybrid").lower().strip()
    if mode_norm not in ("hybrid", "vector", "keyword", "mmr"):
        request_retrieval_mode = "hybrid"
        mode_norm = "hybrid"

    retriever = hybrid_retriever.model_copy(
        update={
            "k": state.get("top_k", settings.RETRIEVAL_TOP_K),
            "score_threshold": state.get("score_threshold", settings.SIMILARITY_THRESHOLD),
            "alpha": state.get("alpha", 0.6),
            "retrieval_mode": request_retrieval_mode,
            "enable_weight_rerank": state.get("enable_weight_rerank", True),
            "vector_weight": state.get("vector_weight", 0.6),
            "keyword_weight": state.get("keyword_weight", 0.4),
            "mmr_lambda": state.get("mmr_lambda", settings.RETRIEVAL_MMR_LAMBDA),
            "enable_reranker": state.get("enable_reranker", settings.ENABLE_RERANKER),
            "reranker_provider": state.get("reranker_provider", settings.RERANKER_PROVIDER),
            "reranker_top_n": state.get("reranker_top_n", settings.RERANKER_TOP_N),
            "tenant_id": state.get("tenant_id"),
            "account_id": state.get("account_id"),
            "dataset_id": state.get("dataset_id"),
            "document_ids": state.get("document_ids"),
            "metadata_filter": state.get("metadata_filter"),
        }
    )
    # Query Expansion (Multi-Query / HyDE, optional)
    multi_query_elapsed = 0.0
    multi_query_used = False
    multi_query_model_used = None
    multi_query_parse_meta: Dict[str, Any] = {"ok": False, "method": None, "error": None}
    multi_queries: List[str] = []

    mq_n = max(0, min(int(settings.MULTI_QUERY_COUNT or 0), 8))
    mq_max_chars = max(0, int(settings.MULTI_QUERY_MAX_CHARS or 0))
    if bool(settings.ENABLE_MULTI_QUERY) and mq_n > 0 and mq_max_chars > 0 and len(query_for_retrieval) <= mq_max_chars:
        mq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        multi_query_model_used = getattr(mq_llm, "model_name", None) or getattr(mq_llm, "model", None)
        try:
            mq_chain = (
                engine.multi_query_prompt  # type: ignore[attr-defined]
                | mq_llm.bind(temperature=settings.MULTI_QUERY_TEMPERATURE)
                | StrOutputParser()
            )
            mq_start = time.time()
            mq_raw = mq_chain.invoke({"query": query_for_retrieval, "n": mq_n})
            multi_query_elapsed = time.time() - mq_start
            mq_data, multi_query_parse_meta = parse_json_from_text(mq_raw, expected="array")

            if isinstance(mq_data, list):
                seen: set[str] = set()
                for item in mq_data:
                    if not isinstance(item, str):
                        continue
                    q = (item or "").strip().strip('"').strip()
                    if not q:
                        continue
                    if q == query_for_retrieval:
                        continue
                    if q in seen:
                        continue
                    if len(q) > 400:
                        q = q[:400] + "..."
                    seen.add(q)
                    multi_queries.append(q)
                    if len(multi_queries) >= mq_n:
                        break
        except Exception as exc:  # noqa: BLE001
            multi_query_elapsed = 0.0
            multi_query_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
            multi_queries = []

    multi_query_used = bool(multi_queries)

    hyde_used = False
    hyde_elapsed = 0.0
    hyde_model_used = None
    hyde_text = ""
    hyde_max_chars = max(0, int(settings.HYDE_MAX_CHARS or 0))
    retrieval_mode_norm = str(request_retrieval_mode or "hybrid").lower()
    if bool(settings.ENABLE_HYDE) and retrieval_mode_norm not in ("keyword",) and hyde_max_chars > 0 and len(query_for_retrieval) <= hyde_max_chars:
        hyde_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        hyde_model_used = getattr(hyde_llm, "model_name", None) or getattr(hyde_llm, "model", None)
        try:
            hyde_chain = (
                engine.hyde_prompt  # type: ignore[attr-defined]
                | hyde_llm.bind(temperature=settings.HYDE_TEMPERATURE)
                | StrOutputParser()
            )
            hyde_start = time.time()
            hyde_text = hyde_chain.invoke({"query": query_for_retrieval})
            hyde_elapsed = time.time() - hyde_start
            hyde_text = (hyde_text or "").strip()
            out_max = max(0, int(settings.HYDE_OUTPUT_MAX_CHARS or 0))
            if out_max and len(hyde_text) > out_max:
                hyde_text = hyde_text[:out_max] + "..."
            hyde_used = bool(hyde_text)
        except Exception:  # noqa: BLE001
            hyde_text = ""
            hyde_elapsed = 0.0
            hyde_used = False

    decompose_elapsed = 0.0
    decompose_used = False
    decompose_model_used = None
    decompose_parse_meta: Dict[str, Any] = {"ok": False, "method": None, "error": None}
    sub_questions: List[str] = []

    dq_n = max(0, min(int(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS or 0), 8))
    dq_min_chars = max(0, int(settings.QUERY_DECOMPOSITION_MIN_CHARS or 0))
    dq_max_chars = max(0, int(settings.QUERY_DECOMPOSITION_MAX_CHARS or 0))
    if (
        bool(settings.ENABLE_QUERY_DECOMPOSITION)
        and dq_n > 0
        and len(query_for_retrieval) >= dq_min_chars
        and (dq_max_chars <= 0 or len(query_for_retrieval) <= dq_max_chars)
    ):
        dq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
        decompose_model_used = getattr(dq_llm, "model_name", None) or getattr(dq_llm, "model", None)
        try:
            dq_chain = (
                engine.decompose_prompt  # type: ignore[attr-defined]
                | dq_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
                | StrOutputParser()
            )
            dq_start = time.time()
            dq_raw = dq_chain.invoke({"query": query_for_retrieval, "n": dq_n})
            decompose_elapsed = time.time() - dq_start
            dq_data, decompose_parse_meta = parse_json_from_text(dq_raw, expected="array")

            if isinstance(dq_data, list):
                seen: set[str] = set()
                for item in dq_data:
                    if not isinstance(item, str):
                        continue
                    q = (item or "").strip().strip('"').strip()
                    if not q:
                        continue
                    if q == query_for_retrieval:
                        continue
                    if q in seen:
                        continue
                    if len(q) > 500:
                        q = q[:500] + "..."
                    seen.add(q)
                    sub_questions.append(q)
                    if len(sub_questions) >= dq_n:
                        break
        except Exception as exc:  # noqa: BLE001
            decompose_elapsed = 0.0
            decompose_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
            sub_questions = []

    decompose_used = bool(sub_questions)

    retrieval_queries: List[tuple[str, str]] = [("main", query_for_retrieval)]
    for q in multi_queries:
        retrieval_queries.append(("mq", q))
    for q in sub_questions:
        retrieval_queries.append(("subq", q))
    if hyde_used and hyde_text:
        retrieval_queries.append(("hyde", hyde_text))

    # Deduplicate query variants (avoid redundant retrieval calls).
    seen_queries: set[str] = set()
    deduped_queries: List[tuple[str, str]] = []
    for kind, q in retrieval_queries:
        norm = " ".join((q or "").strip().split())
        if not norm:
            continue
        key = norm.casefold() if norm.isascii() else norm
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped_queries.append((kind, norm))
    retrieval_queries = deduped_queries

    docs_by_query: List[List[Document]] = []
    retrieval_errors: List[str] = []
    retrieval_per_query: List[Dict[str, Any]] = []
    start = time.time()
    retrieval_parallelism = max(1, int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1))
    retrieval_plan: List[tuple[str, str, Any]] = []
    for kind, q in retrieval_queries:
        r = retriever
        if kind != "main":
            if kind == "hyde":
                r = retriever.model_copy(
                    update={
                        "enable_reranker": False,
                        "retrieval_mode": "vector",
                        "enable_weight_rerank": False,
                    }
                )
            else:
                r = retriever.model_copy(update={"enable_reranker": False})
        retrieval_plan.append((kind, q, r))

    def _invoke_with_timing(
        kind: str, q: str, r: Any
    ) -> tuple[str, List[Document], str | None, float, Dict[str, Any] | None]:
        t0 = time.time()
        try:
            docs_i = r.invoke(q)
            docs_i = engine._annotate_docs_with_role(docs_i or [], kind)  # type: ignore[attr-defined]
            dbg = getattr(r, "_last_debug_metrics", None)
            dbg = dbg if isinstance(dbg, dict) else None
            return kind, (docs_i or []), None, time.time() - t0, dbg
        except Exception as exc:  # noqa: BLE001
            return kind, [], str(exc)[:200], time.time() - t0, None

    if retrieval_parallelism <= 1 or len(retrieval_plan) <= 1:
        for kind, q, r in retrieval_plan:
            kind, docs_i, err, elapsed_i, dbg = _invoke_with_timing(kind, q, r)
            retrieval_per_query.append(
                {
                    "kind": kind,
                    "query_chars": len(q or ""),
                    "elapsed_sec": round(elapsed_i, 3),
                    "ok": err is None,
                    "retriever_debug": dbg,
                }
            )
            if err:
                retrieval_errors.append(f"{kind}:{err[:160]}")
            docs_by_query.append(docs_i or [])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=retrieval_parallelism) as pool:
            futures = [pool.submit(_invoke_with_timing, kind, q, r) for kind, q, r in retrieval_plan]
            for fut in futures:
                kind, docs_i, err, elapsed_i, dbg = fut.result()
                retrieval_per_query.append(
                    {
                        "kind": kind,
                        "query_chars": len(q or ""),
                        "elapsed_sec": round(elapsed_i, 3),
                        "ok": err is None,
                        "retriever_debug": dbg,
                    }
                )
                if err:
                    retrieval_errors.append(f"{kind}:{err[:160]}")
                docs_by_query.append(docs_i or [])
    retrieval_elapsed = time.time() - start

    if len(docs_by_query) <= 1:
        docs = docs_by_query[0] if docs_by_query else []
    else:
        docs = engine.fuse_docs_rrf(docs_by_query, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]
    top_k = int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5)
    docs = (docs or [])[: max(0, top_k)]

    # Optional: TAG injection (table_store results) passed in by the API layer.
    injected = state.get("tag_docs")
    tag_docs: List[Document] = []
    if isinstance(injected, list) and injected:
        for obj in injected[:10]:  # hard cap: avoid huge state payloads
            if isinstance(obj, Document):
                tag_docs.append(obj)
                continue
            if isinstance(obj, dict):
                content = obj.get("page_content")
                if content is None:
                    content = obj.get("content")
                meta = obj.get("metadata")
                meta = meta if isinstance(meta, dict) else {}
                did = obj.get("id") or meta.get("chunk_id")
                try:
                    tag_docs.append(Document(page_content=str(content or ""), metadata=meta, id=did))
                except Exception:
                    continue
    if tag_docs:
        docs = tag_docs + (docs or [])

    citations = build_citations_from_docs(
        docs,
        retrieval_elapsed_sec=retrieval_elapsed,
        retrieval_mode=request_retrieval_mode,
        query=query_for_retrieval,
    )

    metrics = dict(state.get("metrics") or {})
    metrics["retrieval_elapsed_sec"] = round(retrieval_elapsed, 3)
    metrics["retrieval_mode"] = request_retrieval_mode
    metrics["retrieval_mode_requested"] = requested_retrieval_mode
    metrics["retrieval_mode_auto_routed"] = bool(retrieval_mode_routed)
    metrics["retrieval_query_parallelism"] = retrieval_parallelism
    metrics["retrieval_query_count"] = len(retrieval_plan)
    metrics["retrieval_per_query"] = retrieval_per_query[:8]
    metrics["vector_backend"] = settings.VECTOR_BACKEND
    if retrieval_errors:
        metrics["retrieval_errors"] = retrieval_errors[:5]
    metrics["query_rewrite_enabled"] = settings.ENABLE_QUERY_REWRITE
    metrics["rewrite_used"] = bool(rewrite_used)
    metrics["rewrite_elapsed_sec"] = round(rewrite_elapsed, 3)
    metrics["rewrite_model_used"] = rewrite_model_used
    metrics["multi_query_enabled"] = bool(settings.ENABLE_MULTI_QUERY)
    metrics["multi_query_used"] = bool(multi_query_used)
    metrics["multi_query_count"] = len(multi_queries)
    metrics["multi_query_elapsed_sec"] = round(multi_query_elapsed, 3)
    metrics["multi_query_model_used"] = multi_query_model_used
    metrics["multi_query_parse_ok"] = bool(multi_query_parse_meta.get("ok"))
    metrics["multi_query_parse_method"] = multi_query_parse_meta.get("method")
    metrics["multi_query_parse_error"] = multi_query_parse_meta.get("error")
    metrics["hyde_enabled"] = bool(settings.ENABLE_HYDE)
    metrics["hyde_used"] = bool(hyde_used)
    metrics["hyde_elapsed_sec"] = round(hyde_elapsed, 3)
    metrics["hyde_model_used"] = hyde_model_used
    metrics["decompose_enabled"] = bool(settings.ENABLE_QUERY_DECOMPOSITION)
    metrics["decompose_used"] = bool(decompose_used)
    metrics["decompose_count"] = len(sub_questions)
    metrics["decompose_elapsed_sec"] = round(decompose_elapsed, 3)
    metrics["decompose_model_used"] = decompose_model_used
    metrics["decompose_parse_ok"] = bool(decompose_parse_meta.get("ok"))
    metrics["decompose_parse_method"] = decompose_parse_meta.get("method")
    metrics["decompose_parse_error"] = decompose_parse_meta.get("error")
    if tag_docs:
        metrics["tag"] = {
            "enabled": True,
            "used": True,
            "returned": len(tag_docs),
            "reason": (state.get("tag_meta") or {}).get("reason") if isinstance(state.get("tag_meta"), dict) else "injected",
        }
    elif isinstance(state.get("tag_meta"), dict):
        metrics["tag"] = state.get("tag_meta")

    # Grounding guard: abstain when evidence is weak/empty.
    strict_visible = bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False))
    abstain_enabled = bool(settings.RAG_ABSTAIN_ENABLED) or strict_visible
    abstain_triggered = False
    abstain_reason: str | None = None
    top_rel = 0.0
    if citations:
        try:
            top_rel = max(
                float(
                    c.get("retrieval_score")
                    if c.get("retrieval_score") is not None
                    else (c.get("relevance_score", 0.0) or 0.0)
                )
                for c in citations
            )
        except Exception:
            top_rel = 0.0

    if abstain_enabled:
        min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0))
        min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
        if min_citations > 0 and len(citations) < min_citations:
            abstain_triggered = True
            abstain_reason = "citations_lt_min"
        elif min_top_rel > 0 and top_rel < min_top_rel:
            abstain_triggered = True
            abstain_reason = "top_relevance_lt_min"

    metrics["abstain_enabled"] = bool(abstain_enabled)
    metrics["abstain_triggered"] = bool(abstain_triggered)
    metrics["abstain_reason"] = abstain_reason
    metrics["abstain_min_citations"] = int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0)
    metrics["abstain_min_top_relevance_score"] = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
    metrics["top_relevance_score"] = round(float(top_rel or 0.0), 3)

    if bool(abstain_triggered):
        metrics["abstain_followup"] = build_abstain_followup(reason=abstain_reason, citations=citations)

    return {
        **state,
        "query_for_retrieval": query_for_retrieval,
        "docs": docs,
        "citations": citations,
        "metrics": metrics,
        "abstain_triggered": bool(abstain_triggered),
        "abstain_reason": abstain_reason,
    }


def _generate_node(state: RAGState) -> RAGState:
    # Grounding guard: retrieval already decided to abstain, skip generation.
    if bool(state.get("abstain_triggered")):
        engine = get_rag_engine()
        llm, route, reason = engine._select_llm(state["question"], state.get("history"))  # type: ignore[attr-defined]

        abstain_message = "Unable to answer this question based on the available materials."
        answer = abstain_message
        if bool(state.get("structured_output")):
            preset_key = (state.get("structured_preset") or "").lower()
            citations = state.get("citations") or []
            top_k = int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5)
            structured_citations: List[Dict[str, Any]] = []
            for c in citations[: max(0, int(top_k or 0))]:
                structured_citations.append(
                    {
                        "document_id": c.get("document_id"),
                        "chunk_id": c.get("chunk_id"),
                        "page_number": c.get("page_number"),
                        "relevance_score": c.get("relevance_score"),
                    }
                )
            payload: Dict[str, Any] = {"answer": abstain_message, "citations": structured_citations}
            if preset_key == "faq":
                payload["qa_pairs"] = []
            elif preset_key == "summary":
                payload["bullets"] = []
                payload["summary"] = ""
            elif preset_key == "action_items":
                payload["actions"] = []
            answer = json.dumps(payload, ensure_ascii=False)

        metrics = dict(state.get("metrics") or {})
        metrics["generation_elapsed_sec"] = 0.0
        metrics["context_evidence_enabled"] = bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
        metrics["context_evidence_max_sentences_per_chunk"] = (
            int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
        )
        metrics["context_evidence_min_sentence_chars"] = (
            int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
        )

        base = 0.0
        base += float(metrics.get("retrieval_elapsed_sec", 0.0) or 0.0)
        base += float(metrics.get("rewrite_elapsed_sec", 0.0) or 0.0)
        base += float(metrics.get("multi_query_elapsed_sec", 0.0) or 0.0)
        base += float(metrics.get("hyde_elapsed_sec", 0.0) or 0.0)
        base += float(metrics.get("decompose_elapsed_sec", 0.0) or 0.0)
        metrics["elapsed_sec"] = round(base, 3)

        metrics["model_route"] = route
        metrics["model_used"] = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        metrics["llm_max_retries"] = settings.LLM_MAX_RETRIES
        metrics["prompt_template_id"] = state.get("prompt_template_id")
        metrics["prompt_template_key"] = state.get("prompt_template_key")
        metrics["prompt_ab_experiment_key"] = state.get("prompt_ab_experiment_key")
        metrics["prompt_ab_variant"] = state.get("prompt_ab_variant")

        return {
            **state,
            "answer": answer,
            "route": route,
            "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
            "routing_reason": reason,
            "metrics": metrics,
        }

    engine = get_rag_engine()
    llm, route, reason = engine._select_llm(state["question"], state.get("history"))  # type: ignore[attr-defined]
    prompt_obj = engine.prompt_template
    prompt_content = state.get("prompt_template_content")
    if prompt_content:
        try:
            prompt_obj = ChatPromptTemplate.from_template(str(prompt_content))
        except Exception:
            prompt_obj = engine.prompt_template

    chain = prompt_obj | llm | StrOutputParser()
    format_instructions = state.get("format_instructions", "")

    ctx = _build_context(state.get("docs") or [], query=state.get("query_for_retrieval") or state.get("question"))
    hist_text = _build_history_text(state.get("history"))

    pii_on = bool(pii_redaction_enabled())

    start = time.time()
    answer = chain.invoke(
        {
            "context": redact_text(ctx) if pii_on else ctx,
            "history": redact_text(hist_text) if pii_on else hist_text,
            "question": redact_text(state["question"]) if pii_on else state["question"],
            "format_instructions": format_instructions,
        }
    )
    generation_elapsed = time.time() - start

    if pii_on:
        answer = redact_text(str(answer))

    strict_visible = bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False))
    claim_check_configured = bool(getattr(settings, "RAG_CLAIM_CHECK_ENABLED", False)) or strict_visible
    claim_check_max_claims = max(1, int(getattr(settings, "RAG_CLAIM_CHECK_MAX_CLAIMS", 24) or 24))
    claim_check_applied = bool(claim_check_configured) and (not bool(state.get("structured_output")))
    claim_check_removed = 0
    claim_check_total = 0

    if claim_check_applied:
        evidence_text = redact_text(ctx) if pii_on else ctx
        claims = split_into_claims(str(answer or ""), max_claims=claim_check_max_claims)
        claim_check_total = len(claims)
        kept: List[str] = []
        for c in claims:
            if is_claim_supported(c, evidence_text):
                kept.append(c)
            else:
                claim_check_removed += 1
        cleaned = "\n".join(kept).strip()
        if not cleaned:
            cleaned = "Unable to answer this question based on the available materials."
        answer = cleaned

    claim_evidence: list[dict[str, Any]] = []
    if not bool(state.get("structured_output")):
        try:
            claim_evidence = build_claim_evidence_map(
                str(answer or ""),
                evidence_chunks=list(state.get("docs") or []),
                max_claims=claim_check_max_claims if claim_check_configured else 24,
            )
        except Exception:
            claim_evidence = []

    # Append cited images as inline Markdown to the answer (non-structured output only, configurable)
    if not bool(state.get("structured_output")) and bool(settings.SHOW_IMAGE_IN_ANSWER) and settings.IMAGE_APPEND_MAX > 0:
        citations = state.get("citations") or []
        image_urls: List[str] = []
        for c in citations:
            if not c.get("has_image"):
                continue
            url = c.get("img_url")
            if not isinstance(url, str) or not url.strip():
                continue
            if url in image_urls:
                continue
            image_urls.append(url)
            if len(image_urls) >= settings.IMAGE_APPEND_MAX:
                break
        if image_urls:
            parts = ["\n\n---\n\n### Related Images\n"]
            for i, url in enumerate(image_urls, 1):
                parts.append(f"![Referenced Image {i}]({url})")
            answer = (answer or "") + "\n\n".join(parts) + "\n"

    metrics = dict(state.get("metrics") or {})
    metrics["generation_elapsed_sec"] = round(generation_elapsed, 3)
    metrics["context_chars"] = len(ctx or "")
    metrics["context_tokens"] = num_tokens_from_string(ctx or "")
    metrics["history_chars"] = len(hist_text or "")
    metrics["history_tokens"] = num_tokens_from_string(hist_text or "")
    metrics["question_chars"] = len(state.get("question") or "")
    metrics["question_tokens"] = num_tokens_from_string(state.get("question") or "")
    metrics["context_limit_total_chars"] = int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0)
    metrics["context_limit_total_tokens"] = int(getattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0) or 0)
    metrics["context_limit_per_chunk_chars"] = int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0)
    metrics["context_limit_per_chunk_tokens"] = int(getattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0) or 0)
    metrics["context_evidence_enabled"] = bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
    metrics["context_evidence_max_sentences_per_chunk"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
    )
    metrics["context_evidence_min_sentence_chars"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
    )
    metrics["claim_check_enabled"] = bool(claim_check_applied)
    metrics["claim_check_removed"] = int(claim_check_removed)
    metrics["claim_check_total"] = int(claim_check_total)
    metrics["claim_check_max_claims"] = int(claim_check_max_claims) if claim_check_configured else None
    metrics["claim_evidence"] = claim_evidence
    base = generation_elapsed
    base += float(metrics.get("retrieval_elapsed_sec", 0.0) or 0.0)
    base += float(metrics.get("rewrite_elapsed_sec", 0.0) or 0.0)
    base += float(metrics.get("multi_query_elapsed_sec", 0.0) or 0.0)
    base += float(metrics.get("hyde_elapsed_sec", 0.0) or 0.0)
    base += float(metrics.get("decompose_elapsed_sec", 0.0) or 0.0)
    metrics["elapsed_sec"] = round(base, 3)
    metrics["model_route"] = route
    metrics["model_used"] = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    metrics["llm_max_retries"] = settings.LLM_MAX_RETRIES
    metrics["prompt_template_id"] = state.get("prompt_template_id")
    metrics["prompt_template_key"] = state.get("prompt_template_key")
    metrics["prompt_ab_experiment_key"] = state.get("prompt_ab_experiment_key")
    metrics["prompt_ab_variant"] = state.get("prompt_ab_variant")
    return {
        **state,
        "answer": answer,
        "route": route,
        "model_used": getattr(llm, "model_name", None) or getattr(llm, "model", None),
        "routing_reason": reason,
        "metrics": metrics,
    }


# =============================================================================
# LangGraph 1.0+ Functional API Implementation
# =============================================================================

# Global checkpointer for Functional API
_functional_checkpointer = None


def _get_checkpointer():
    """Get or create global checkpointer instance."""
    global _functional_checkpointer
    if _functional_checkpointer is None:
        _functional_checkpointer = get_checkpointer()
    return _functional_checkpointer


@task(retry_policy=_RAG_TASK_RETRY_POLICY, cache_policy=_RAG_RETRIEVE_CACHE_POLICY)
def retrieve_task(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retrieval task - using Functional API @task decorator.

    Supports retry and timeout mechanisms, consistent with original _retrieve_node logic.
    """
    writer = None
    if bool(getattr(settings, "STREAM_WRITER_ENABLED", True)):
        try:
            writer = get_stream_writer()
        except Exception:  # noqa: BLE001
            writer = None

    if writer:
        writer(
            {
                "event": "retrieve_start",
                "question": (state.get("question") or "")[:500],
                "retrieval_mode": state.get("retrieval_mode"),
                "top_k": state.get("top_k"),
            }
        )

    tracing_client = None
    try:
        from app.rag.tracing import get_tracing_client

        tracing_client = get_tracing_client()
    except Exception:  # noqa: BLE001
        tracing_client = None

    if tracing_client and tracing_client.enabled:
        metrics_in = dict((state.get("metrics") or {}))
        with tracing_client.trace(
            name="rag_retrieve",
            run_type="retriever",
            inputs={
                "question": (state.get("question") or "")[:2000],
                "retrieval_mode": state.get("retrieval_mode"),
                "top_k": state.get("top_k"),
                "document_ids_count": len(state.get("document_ids") or []),
            },
            metadata={
                "request_id": metrics_in.get("request_id"),
                "conversation_id": metrics_in.get("conversation_id"),
                "tenant_id": metrics_in.get("tenant_id") or str(state.get("tenant_id") or ""),
                "account_id": metrics_in.get("account_id"),
            },
            tags=["rag", "langgraph", "retrieval"],
        ) as span:
            result = _run_with_retry("retrieve", _retrieve_node, state)
            citations = result.get("citations") or []
            metrics_out = result.get("metrics") or {}
            span.outputs = {
                "citations_count": len(citations),
                "query_for_retrieval": (result.get("query_for_retrieval") or "")[:2000],
                "retrieval_elapsed_sec": metrics_out.get("retrieval_elapsed_sec"),
            }
    else:
        result = _run_with_retry("retrieve", _retrieve_node, state)

    if writer:
        citations = result.get("citations") or []
        metrics = result.get("metrics") or {}
        writer(
            {
                "event": "retrieve_done",
                "query_for_retrieval": (result.get("query_for_retrieval") or "")[:500],
                "citations_count": len(citations),
                "retrieval_mode": metrics.get("retrieval_mode") or result.get("retrieval_mode"),
                "elapsed_sec": metrics.get("retrieval_elapsed_sec"),
            }
        )

    return result


@task(retry_policy=_RAG_TASK_RETRY_POLICY)
def generate_task(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generation task - using Functional API @task decorator.

    Supports retry and timeout mechanisms, consistent with original _generate_node logic.
    """
    writer = None
    if bool(getattr(settings, "STREAM_WRITER_ENABLED", True)):
        try:
            writer = get_stream_writer()
        except Exception:  # noqa: BLE001
            writer = None

    if writer:
        writer(
            {
                "event": "generate_start",
                "structured_output": bool(state.get("structured_output")),
                "structured_preset": state.get("structured_preset"),
            }
        )

    tracing_client = None
    try:
        from app.rag.tracing import get_tracing_client

        tracing_client = get_tracing_client()
    except Exception:  # noqa: BLE001
        tracing_client = None

    if tracing_client and tracing_client.enabled:
        metrics_in = dict((state.get("metrics") or {}))
        with tracing_client.trace(
            name="rag_generate",
            run_type="llm",
            inputs={
                "question": (state.get("question") or "")[:2000],
                "structured_output": bool(state.get("structured_output")),
                "structured_preset": state.get("structured_preset"),
            },
            metadata={
                "request_id": metrics_in.get("request_id"),
                "conversation_id": metrics_in.get("conversation_id"),
                "tenant_id": metrics_in.get("tenant_id") or str(state.get("tenant_id") or ""),
                "account_id": metrics_in.get("account_id"),
            },
            tags=["rag", "langgraph", "generation"],
        ) as span:
            result = _run_with_retry("generate", _generate_node, state)
            metrics_out = result.get("metrics") or {}
            span.outputs = {
                "answer_chars": len(result.get("answer") or ""),
                "route": result.get("route"),
                "model_used": result.get("model_used"),
                "generation_elapsed_sec": metrics_out.get("generation_elapsed_sec"),
            }
    else:
        result = _run_with_retry("generate", _generate_node, state)

    if writer:
        metrics = result.get("metrics") or {}
        writer(
            {
                "event": "generate_done",
                "answer_chars": len(result.get("answer") or ""),
                "route": result.get("route"),
                "model_used": result.get("model_used"),
                "elapsed_sec": metrics.get("generation_elapsed_sec"),
            }
        )

    return result


@entrypoint(checkpointer=_get_checkpointer(), store=get_langgraph_store(), context_schema=RAGRuntimeContext)
def rag_workflow(state: Dict[str, Any], runtime: Runtime[RAGRuntimeContext]) -> Dict[str, Any]:
    """
    RAG workflow entrypoint - using Functional API @entrypoint decorator.

    Executes retrieve -> generate flow with checkpoint persistence support.
    """
    # Execute retrieval task
    metrics = dict(state.get("metrics") or {})
    if runtime and getattr(runtime, "context", None):
        ctx = runtime.context
        if ctx.request_id:
            metrics["request_id"] = ctx.request_id
        if ctx.conversation_id:
            metrics["conversation_id"] = ctx.conversation_id
        if ctx.tenant_id:
            metrics["tenant_id"] = ctx.tenant_id
        if ctx.account_id:
            metrics["account_id"] = ctx.account_id
        if ctx.user_role:
            metrics["user_role"] = ctx.user_role
    if metrics:
        state["metrics"] = metrics

    state = retrieve_task(state).result()

    # Execute generation task
    state = generate_task(state).result()

    return state


def run_rag_workflow_functional(
    state: Dict[str, Any],
    *,
    thread_id: Optional[str] = None,
    stream_mode: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute RAG workflow using Functional API.

    Args:
        state: RAG state dictionary
        thread_id: Optional thread ID for session persistence
        stream_mode: Streaming mode ("updates", "values", None)

    Returns:
        Execution result state
    """
    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config: Dict[str, Any] = {
        "configurable": {"thread_id": thread_id or f"rag-{uuid4()}"},
        "recursion_limit": recursion_limit,
    }

    if stream_mode:
        # Streaming execution
        result = None
        for step in rag_workflow.stream(state, config=config, stream_mode=stream_mode, context=context):
            result = step
        return result or state
    else:
        # Synchronous execution
        return rag_workflow.invoke(state, config=config, context=context)


def build_rag_graph() -> Any:
    """Build a minimal RAG flow graph: retrieve -> generate -> end."""
    if bool(getattr(settings, "LANGGRAPH_USE_SUBGRAPHS", False)):
        return build_rag_graph_subgraphs()

    graph = StateGraph(RAGState)

    graph.add_node(
        "retrieve",
        partial(_run_with_retry, "retrieve", _retrieve_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    graph.add_node(
        "generate",
        partial(_run_with_retry, "generate", _generate_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    checkpointer = get_checkpointer()
    store = get_langgraph_store()
    return graph.compile(checkpointer=checkpointer, store=store)


def _build_retrieve_subgraph() -> Any:
    """Subgraph: retrieve only (END after retrieval)."""
    g = StateGraph(RAGState)
    g.add_node(
        "retrieve",
        partial(_run_with_retry, "retrieve", _retrieve_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", END)
    return g.compile(name="rag_retrieve_subgraph")


def _build_generate_subgraph() -> Any:
    """Subgraph: generate only (END after generation)."""
    g = StateGraph(RAGState)
    g.add_node(
        "generate",
        partial(_run_with_retry, "generate", _generate_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    g.set_entry_point("generate")
    g.add_edge("generate", END)
    return g.compile(name="rag_generate_subgraph")


def build_rag_graph_subgraphs() -> Any:
    """
    Build a modular RAG graph using LangGraph subgraphs.

    This enables composition of reusable subgraphs (retrieve/generate/…)
    and mirrors the reference project's "subgraph as node" pattern.
    """
    retrieve_subgraph = _build_retrieve_subgraph()
    generate_subgraph = _build_generate_subgraph()

    g = StateGraph(RAGState)
    g.add_node("retrieve_flow", retrieve_subgraph)
    g.add_node("generate_flow", generate_subgraph)
    g.set_entry_point("retrieve_flow")
    g.add_edge("retrieve_flow", "generate_flow")
    g.add_edge("generate_flow", END)

    checkpointer = get_checkpointer()
    store = get_langgraph_store()
    return g.compile(checkpointer=checkpointer, store=store, name="rag_graph_subgraphs")


def build_rag_state(
    *,
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    document_ids: Optional[List[UUID]] = None,
    tenant_id: Optional[UUID] = None,
    account_id: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    top_k: int = 5,
    score_threshold: float = 0.7,
    retrieval_mode: str = "hybrid",
    alpha: float = 0.6,
    enable_weight_rerank: bool = True,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.4,
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA,
    enable_reranker: bool = settings.ENABLE_RERANKER,
    reranker_provider: Optional[str] = settings.RERANKER_PROVIDER,
    reranker_top_n: int = settings.RERANKER_TOP_N,
    metadata_filter: Optional[Dict[str, Any]] = None,
    structured_output: bool = False,
    structured_preset: Optional[str] = None,
    prompt_template_id: Optional[UUID] = None,
    prompt_template_key: Optional[str] = None,
    prompt_ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build initial RAG graph state shared by run/stream entrypoints."""

    engine = get_rag_engine()
    preset_key = (structured_preset or "").lower()
    format_instructions = ""
    if structured_output:
        format_instructions = engine.structured_presets.get(
            preset_key,
            (
                "Please return JSON only, structure: "
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "...", "page_number": null, "relevance_score": 0.0}]}'
                " Do not output extra text."
            ),
        )

    prompt_template_content = None
    selected_prompt_template_id = None
    selected_prompt_template_key = None
    selected_prompt_ab_experiment_key = None
    selected_prompt_ab_variant = None
    if db and tenant_id and (prompt_template_id or prompt_template_key or prompt_ab_experiment_key):
        chosen = resolve_prompt_template(
            db=db,
            tenant_id=tenant_id,
            prompt_template_id=prompt_template_id,
            template_key=prompt_template_key,
            ab_experiment_key=prompt_ab_experiment_key,
            ab_user_key=ab_user_key,
        )
        if chosen:
            prompt_template_content = chosen.content
            selected_prompt_template_id = str(chosen.id)
            selected_prompt_template_key = getattr(chosen, "template_key", None)
            selected_prompt_ab_experiment_key = getattr(chosen, "ab_experiment_key", None)
            selected_prompt_ab_variant = getattr(chosen, "ab_variant", None)
            chosen.usage_count += 1
            db.commit()

    # Version-aware retrieval scoping: force retrieval to use each doc's active pipeline.
    if db is not None and tenant_id is not None and document_ids:
        try:
            from app.models.document import Document as DBDocument

            rows = (
                db.query(DBDocument.id, DBDocument.status, DBDocument.doc_metadata)
                .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(document_ids)))
                .all()
            )
            active_keys: list[str] = []
            for did, status, meta in rows:
                m = meta if isinstance(meta, dict) else {}
                ready = (
                    bool(m.get("active_pipeline_ready"))
                    if "active_pipeline_ready" in m
                    else (str(status or "").lower() == "completed")
                )
                if not ready:
                    continue
                active_hash = str(m.get("active_pipeline_hash") or m.get("pipeline_hash") or "").strip()
                if not active_hash:
                    continue
                active_keys.append(f"{did}:{active_hash}")

            if active_keys:
                mf = dict(metadata_filter or {})
                mf["doc_pipeline_key"] = {"$in": set(active_keys)}
                metadata_filter = mf
        except Exception:
            pass

    return {
        "question": question,
        "history": history or [],
        "document_ids": document_ids,
        "tenant_id": tenant_id,
        "account_id": account_id,
        "dataset_id": dataset_id,
        "top_k": top_k,
        "score_threshold": score_threshold,
        "retrieval_mode": retrieval_mode,
        "alpha": alpha,
        "enable_weight_rerank": enable_weight_rerank,
        "vector_weight": vector_weight,
        "keyword_weight": keyword_weight,
        "mmr_lambda": mmr_lambda,
        "enable_reranker": enable_reranker,
        "reranker_provider": reranker_provider,
        "reranker_top_n": reranker_top_n,
        "metadata_filter": metadata_filter,
        "format_instructions": format_instructions,
        "structured_output": bool(structured_output),
        "structured_preset": structured_preset,
        "prompt_template_content": prompt_template_content,
        "prompt_template_id": selected_prompt_template_id,
        "prompt_template_key": selected_prompt_template_key,
        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
        "prompt_ab_variant": selected_prompt_ab_variant,
    }


def run_rag_graph(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    document_ids: Optional[List[UUID]] = None,
    tenant_id: Optional[UUID] = None,
    account_id: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    top_k: int = 5,
    score_threshold: float = 0.7,
    retrieval_mode: str = "hybrid",
    thread_id: Optional[str] = None,
    runtime_context: Optional[Dict[str, Any]] = None,
    alpha: float = 0.6,
    enable_weight_rerank: bool = True,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.4,
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA,
    enable_reranker: bool = settings.ENABLE_RERANKER,
    reranker_provider: Optional[str] = settings.RERANKER_PROVIDER,
    reranker_top_n: int = settings.RERANKER_TOP_N,
    metadata_filter: Optional[Dict[str, Any]] = None,
    structured_output: bool = False,
    structured_preset: Optional[str] = None,
    prompt_template_id: Optional[UUID] = None,
    prompt_template_key: Optional[str] = None,
    prompt_ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute LangGraph RAG flow, return answer/citations/model info."""
    state = build_rag_state(
        question=question,
        history=history or [],
        document_ids=document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        top_k=top_k,
        score_threshold=score_threshold,
        retrieval_mode=retrieval_mode,
        alpha=alpha,
        enable_weight_rerank=enable_weight_rerank,
        vector_weight=vector_weight,
        keyword_weight=keyword_weight,
        mmr_lambda=mmr_lambda,
        enable_reranker=enable_reranker,
        reranker_provider=reranker_provider,
        reranker_top_n=reranker_top_n,
        metadata_filter=metadata_filter,
        structured_output=structured_output,
        structured_preset=structured_preset,
        prompt_template_id=prompt_template_id,
        prompt_template_key=prompt_template_key,
        prompt_ab_experiment_key=prompt_ab_experiment_key,
        ab_user_key=ab_user_key,
        db=db,
    )

    # Use Functional API (LangGraph 1.0+)
    use_functional_api = bool(getattr(settings, "LANGGRAPH_USE_FUNCTIONAL_API", True))

    if use_functional_api:
        result = run_rag_workflow_functional(state, thread_id=thread_id, context=runtime_context)
        logger.debug("RAG workflow executed using Functional API")
    else:
        app = build_rag_graph()
        recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
        config = {
            "configurable": {"thread_id": thread_id or f"rag-{uuid4()}"},
            "recursion_limit": recursion_limit,
        }
        result = app.invoke(state, config=config, context=runtime_context)

    return {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "model_used": result.get("model_used"),
        "route": result.get("route"),
        "routing_reason": result.get("routing_reason"),
        "metrics": result.get("metrics", {}),
    }


def stream_rag_graph(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    document_ids: Optional[List[UUID]] = None,
    tenant_id: Optional[UUID] = None,
    top_k: int = 5,
    score_threshold: float = 0.7,
    retrieval_mode: str = "hybrid",
    thread_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    **kwargs,
):
    """
    Stream RAG workflow execution, supports LangGraph 1.0+ Functional API.

    Yields:
        Dict[str, Any]: State updates for each step
    """
    state = {
        "question": question,
        "history": history or [],
        "document_ids": document_ids,
        "tenant_id": tenant_id,
        "top_k": top_k,
        "score_threshold": score_threshold,
        "retrieval_mode": retrieval_mode,
        **kwargs,
    }

    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config: Dict[str, Any] = {
        "configurable": {"thread_id": thread_id or f"rag-{uuid4()}"},
        "recursion_limit": recursion_limit,
    }

    for step in rag_workflow.stream(state, config=config, stream_mode="updates", context=context):
        yield step


# =============================================================================
# Public API Exports
# =============================================================================

__all__ = [
    # State types
    "RAGState",
    # Legacy API (backward compatible)
    "build_rag_graph",
    "run_rag_graph",
    # LangGraph 1.0+ Functional API
    "retrieve_task",
    "generate_task",
    "rag_workflow",
    "run_rag_workflow_functional",
    "stream_rag_graph",
]

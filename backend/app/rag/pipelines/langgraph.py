"""
LangGraph pipeline for RAG (retrieve -> generate).

This module is the canonical home for the non-streaming LangGraph-based runner.
`app.rag.graph` remains as a backward-compatible import path.

Refactored to use LangGraph 1.0+ Functional API with @entrypoint and @task decorators.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, List, Optional, TypedDict
from uuid import UUID, uuid4

import json
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
import concurrent.futures
from functools import partial
import time

from app.rag.core.citations import build_citations_from_docs
from app.rag.core.conversation import format_history_text
from app.rag.core.text import parse_json_from_text, extract_evidence_text, guess_retrieval_mode, normalize_retrieval_mode
from app.rag.retriever import hybrid_retriever
from app.rag.engine import get_rag_engine
from app.rag.checkpointer.factory import get_checkpointer
from app.rag.store.factory import get_langgraph_store
from app.core.config import settings
from app.services.prompt_template_selector import resolve_prompt_template

# LangGraph 1.0+ Functional API imports
from langgraph.func import entrypoint, task
from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, END
from langgraph.runtime import Runtime
from langgraph.types import RetryPolicy, CachePolicy

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
    format_instructions: str
    structured_output: bool
    structured_preset: Optional[str]
    prompt_template_content: Optional[str]
    prompt_template_id: Optional[str]
    prompt_template_key: Optional[str]
    prompt_ab_experiment_key: Optional[str]
    prompt_ab_variant: Optional[str]
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
    key_obj = {
        "question": (state.get("question") or "")[:800],
        "history": history_text,
        "tenant_id": str(state.get("tenant_id") or ""),
        "document_ids": doc_ids_key,
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
    }
    return json.dumps(key_obj, ensure_ascii=False, sort_keys=True)


_RAG_RETRIEVE_CACHE_POLICY = (
    CachePolicy(key_func=_retrieve_cache_key, ttl=_RAG_RETRIEVE_CACHE_TTL_SEC)
    if _RAG_RETRIEVE_CACHE_TTL_SEC > 0
    else None
)


def _build_context(docs: List[Document], *, query: str | None = None) -> str:
    """格式化检索到的文档上下文。"""
    if not docs:
        return "没有找到相关的参考资料。"
    parts = []
    max_per_chunk = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0))
    max_total = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0))
    total_chars = 0
    for idx, doc in enumerate(docs, 1):
        meta = doc.metadata or {}
        source = meta.get("source", "Unknown")
        page = meta.get("page", "N/A")
        raw_content = (doc.page_content or "").strip()
        content = raw_content
        if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) and query:
            content = extract_evidence_text(
                raw_content,
                str(query),
                max_chars=max_per_chunk,
                max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
                min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
            )
        elif max_per_chunk and len(content) > max_per_chunk:
            content = content[:max_per_chunk] + "..."
        part = f"[来源 {idx}: {source} - 第{page}页]\n{content}"
        if max_total and parts and (total_chars + len(part)) > max_total:
            break
        parts.append(part)
        total_chars += len(part)
        if max_total and total_chars >= max_total:
            break
    return "\n\n".join(parts)


def _build_history_text(history: Optional[List[Dict[str, str]]]) -> str:
    """压缩历史为可读文本，仅保留窗口。"""
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _run_with_retry(node_name: str, func, state: RAGState) -> RAGState:
    """节点级重试 + 超时（秒）。"""
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
        and history_text != "（无历史对话）"
        and len(question) <= settings.QUERY_REWRITE_MAX_CHARS
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
            "document_ids": state.get("document_ids"),
        }
    )
    # Query Expansion（Multi-Query / HyDE，可选）
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
            mq_data, multi_query_parse_meta = parse_json_from_text(mq_raw)

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
            dq_data, decompose_parse_meta = parse_json_from_text(dq_raw)

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

    docs_by_query: List[List[Document]] = []
    retrieval_errors: List[str] = []
    start = time.time()
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
        try:
            docs_i = r.invoke(q)
        except Exception as exc:  # noqa: BLE001
            retrieval_errors.append(f"{kind}:{str(exc)[:160]}")
            docs_i = []
        docs_by_query.append(docs_i or [])
    retrieval_elapsed = time.time() - start

    if len(docs_by_query) <= 1:
        docs = docs_by_query[0] if docs_by_query else []
    else:
        docs = engine.fuse_docs_rrf(docs_by_query, rrf_k=settings.RETRIEVAL_RRF_K, meta_prefix="query_expansion")  # type: ignore[attr-defined]
    top_k = int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5)
    docs = (docs or [])[: max(0, top_k)]

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

    # Grounding guard: abstain when evidence is weak/empty.
    abstain_enabled = bool(settings.RAG_ABSTAIN_ENABLED)
    abstain_triggered = False
    abstain_reason: str | None = None
    top_rel = 0.0
    if citations:
        try:
            top_rel = max(float(c.get("relevance_score", 0.0) or 0.0) for c in citations)
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

        abstain_message = "根据现有资料无法回答该问题。你可以补充上传相关文档，或缩小问题范围后再问。"
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

    start = time.time()
    answer = chain.invoke(
        {
            "context": ctx,
            "history": hist_text,
            "question": state["question"],
            "format_instructions": format_instructions,
        }
    )
    generation_elapsed = time.time() - start

    # 将引用图片以内嵌 Markdown 的形式追加到正文（仅非结构化输出，可配置）
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
            parts = ["\n\n---\n\n### 相关图片\n"]
            for i, url in enumerate(image_urls, 1):
                parts.append(f"![引用图片 {i}]({url})")
            answer = (answer or "") + "\n\n".join(parts) + "\n"

    metrics = dict(state.get("metrics") or {})
    metrics["generation_elapsed_sec"] = round(generation_elapsed, 3)
    metrics["context_evidence_enabled"] = bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
    metrics["context_evidence_max_sentences_per_chunk"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
    )
    metrics["context_evidence_min_sentence_chars"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0) if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) else None
    )
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
    """获取或创建全局 checkpointer 实例。"""
    global _functional_checkpointer
    if _functional_checkpointer is None:
        _functional_checkpointer = get_checkpointer()
    return _functional_checkpointer


@task(retry_policy=_RAG_TASK_RETRY_POLICY, cache_policy=_RAG_RETRIEVE_CACHE_POLICY)
def retrieve_task(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    检索任务 - 使用 Functional API @task 装饰器。

    支持重试和超时机制，与原有 _retrieve_node 逻辑一致。
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
    生成任务 - 使用 Functional API @task 装饰器。

    支持重试和超时机制，与原有 _generate_node 逻辑一致。
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
    RAG 工作流入口点 - 使用 Functional API @entrypoint 装饰器。

    执行检索 -> 生成的流程，支持检查点持久化。
    """
    # 执行检索任务
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

    # 执行生成任务
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
    使用 Functional API 执行 RAG 工作流。

    Args:
        state: RAG 状态字典
        thread_id: 可选的线程 ID，用于会话持久化
        stream_mode: 流式模式 ("updates", "values", None)

    Returns:
        执行结果状态
    """
    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config: Dict[str, Any] = {
        "configurable": {"thread_id": thread_id or f"rag-{uuid4()}"},
        "recursion_limit": recursion_limit,
    }

    if stream_mode:
        # 流式执行
        result = None
        for step in rag_workflow.stream(state, config=config, stream_mode=stream_mode, context=context):
            result = step
        return result or state
    else:
        # 同步执行
        return rag_workflow.invoke(state, config=config, context=context)


def build_rag_graph() -> Any:
    """构建一个最小 RAG 流程图：检索 -> 生成 -> 结束。"""
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


def build_rag_state(
    *,
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    document_ids: Optional[List[UUID]] = None,
    tenant_id: Optional[UUID] = None,
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
                "请仅返回 JSON，结构 "
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "...", "page_number": null, "relevance_score": 0.0}]}'
                " 不要输出多余文本。"
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

    return {
        "question": question,
        "history": history or [],
        "document_ids": document_ids,
        "tenant_id": tenant_id,
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
    structured_output: bool = False,
    structured_preset: Optional[str] = None,
    prompt_template_id: Optional[UUID] = None,
    prompt_template_key: Optional[str] = None,
    prompt_ab_experiment_key: Optional[str] = None,
    ab_user_key: Optional[str] = None,
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """执行 LangGraph RAG 流程，返回 answer/citations/模型信息。"""
    engine = get_rag_engine()
    preset_key = (structured_preset or "").lower()
    format_instructions = ""
    if structured_output:
        format_instructions = engine.structured_presets.get(
            preset_key,
            (
                "请仅返回 JSON，结构: "
                '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "...", "page_number": null, "relevance_score": 0.0}]}'
                " 不要输出多余文本。"
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

    state = {
        "question": question,
        "history": history or [],
        "document_ids": document_ids,
        "tenant_id": tenant_id,
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
        "format_instructions": format_instructions,
        "structured_output": bool(structured_output),
        "structured_preset": structured_preset,
        "prompt_template_content": prompt_template_content,
        "prompt_template_id": selected_prompt_template_id,
        "prompt_template_key": selected_prompt_template_key,
        "prompt_ab_experiment_key": selected_prompt_ab_experiment_key,
        "prompt_ab_variant": selected_prompt_ab_variant,
    }

    # 使用 Functional API (LangGraph 1.0+)
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
    流式执行 RAG 工作流，支持 LangGraph 1.0+ Functional API。

    Yields:
        Dict[str, Any]: 每个步骤的状态更新
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

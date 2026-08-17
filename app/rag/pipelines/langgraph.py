"""
LangGraph pipeline for RAG (retrieve -> generate).

This module is the canonical home for the non-streaming LangGraph-based runner.
`app.rag.graph` remains as a backward-compatible import path.

Refactored to use LangGraph 1.0+ Functional API with @entrypoint and @task decorators.
"""

import contextlib
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from functools import partial
from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.config import get_stream_writer

# LangGraph 1.0+ Functional API imports
from langgraph.func import entrypoint, task
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime, get_runtime
from langgraph.types import CachePolicy, RetryPolicy

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.pii_redaction import pii_redaction_enabled, redact_text
from app.core.token_utils import num_tokens_from_string, truncate
from app.rag.checkpointer.factory import get_checkpointer
from app.rag.core.claim_evidence import build_claim_evidence_map
from app.rag.core.confidence import compute_confidence_score
from app.rag.core.context_cliff import compute_context_cliff_metrics
from app.rag.core.conversation import format_history_text
from app.rag.core.faithfulness import compute_faithfulness_score
from app.rag.core.logging import get_logger
from app.rag.core.retrieval_profiles import apply_retrieval_profile_overrides
from app.rag.core.sentence_citations import (
    render_sentence_citations_inline,
    render_sentence_citations_markdown,
)
from app.rag.core.text import (
    build_abstain_answer_message,
    derive_followup_questions,
    extract_evidence_text,
    extract_followup_questions_from_answer,
    scrub_structured_output_visible_evidence_only,
    split_into_claims,
    verify_claim_with_fallback,
)
from app.rag.engine import get_rag_engine
from app.rag.llm.structured_output import (
    build_structured_abstain_payload,
    build_structured_output_instructions,
    parse_and_repair_structured_output,
)
from app.rag.retrieval.source_labels import maybe_build_source_identification_answer
from app.rag.store.factory import get_langgraph_store
from app.services.prompt_resolver import resolve_prompt_template
from app.services.rag_runtime_limiter import run_blocking_retrieval_call_sync

logger = get_logger("rag.pipelines.langgraph")

_UNABLE_TO_ANSWER_MESSAGE = "Unable to answer this question based on the available materials."


@dataclass
class RAGRuntimeContext:
    """Runtime-only context passed to LangGraph nodes (not persisted in state)."""

    request_id: str | None = None
    conversation_id: str | None = None
    tenant_id: str | None = None
    account_id: str | None = None
    user_role: str | None = None
    cancel_event: Any | None = None


class RAGState(TypedDict, total=False):
    """Graph state: question, history, docs, citations, answer, meta.

    Using TypedDict for better type hints and IDE support.
    """

    question: str
    history: list[dict[str, str]]
    document_ids: list[UUID] | None
    dataset_ids: list[UUID] | None
    tenant_id: UUID | None
    request_id: str | None
    top_k: int
    score_threshold: float
    retrieval_mode: str
    retrieval_profile: str | None
    retrieval_contract_mode: str | None
    intent_router: bool | None
    intent_router_policy: dict[str, Any] | None
    enable_query_alias_expansion: bool | None
    query_aliases: dict[str, list[str]] | None
    query_alias_max_queries: int | None
    enable_multi_query: bool | None
    multi_query_count: int | None
    multi_query_temperature: float | None
    multi_query_max_chars: int | None
    enable_hyde: bool | None
    enable_query_decomposition: bool | None
    enable_hierarchy_recall: bool | None
    hierarchy_family_collapse: bool | None
    hierarchy_family_aggregation: str | None
    hierarchy_tree_dedup: bool | None
    hierarchy_parent_depth: int | None
    hierarchy_sibling_window: int | None
    hierarchy_overfetch_factor: int | None
    enable_kg_query_expansion: bool | None
    enable_kg_chunk_injection: bool | None
    kg_chunk_injection_max_chunks: int | None
    enable_kg_chunk_boost: bool | None
    kg_chunk_boost_weight: float | None
    kg_chunk_boost_max_promoted: int | None
    enable_query_rewrite: bool | None
    query_rewrite_strategy: str | None
    query_rewrite_temperature: float | None
    query_rewrite_max_chars: int | None
    sparse_retrieval_enabled: bool | None
    sparse_retrieval_provider: str | None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None
    metadata_exact_db_fallback_enabled: bool | None
    alpha: float
    enable_weight_rerank: bool
    fusion_strategy: str | None
    fusion_budgets: dict[str, int] | None
    fusion_min_scores: dict[str, float] | None
    fusion_weights: dict[str, float] | None
    vector_weight: float
    keyword_weight: float
    mmr_lambda: float
    enable_reranker: bool
    reranker_provider: str | None
    reranker_top_n: int
    metadata_filter: dict[str, Any] | None
    max_tokens: int | None
    format_instructions: str
    structured_output: bool
    structured_preset: str | None
    prompt_template_content: str | None
    prompt_template_id: str | None
    prompt_template_key: str | None
    prompt_ab_experiment_key: str | None
    prompt_ab_variant: str | None
    # Optional: TAG injection (table_store query results) passed in by API layer.
    tag_docs: list[Document] | None
    tag_meta: dict[str, Any] | None
    # Output fields
    query_for_retrieval: str | None
    docs: list[Document] | None
    citations: list[dict[str, Any]] | None
    answer: str | None
    route: str | None
    model_used: str | None
    routing_reason: str | None
    metrics: dict[str, Any] | None
    abstain_triggered: bool | None
    abstain_reason: str | None
    followup_questions: list[str] | None
    # Optional: best-effort debug payload (query normalization/expansion provenance).
    query_debug: dict[str, Any] | None


_RAG_TASK_RETRY_POLICY = RetryPolicy(
    max_attempts=max(1, int(getattr(settings, "RAG_GRAPH_MAX_RETRIES", 0) or 0) + 1),
    retry_on=lambda exc: not isinstance(exc, (ValueError, TypeError, KeyError)),
)


_RAG_RETRIEVE_CACHE_TTL_SEC = max(0, int(getattr(settings, "RAG_GRAPH_CACHE_TTL_SEC", 0) or 0))


def _retrieve_cache_key(state: dict[str, Any]) -> str:
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
    policy_json = ""
    raw_policy = state.get("intent_router_policy")
    if raw_policy is not None:
        try:
            policy_json = json.dumps(raw_policy, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            policy_json = str(raw_policy)
    policy_hash = hashlib.sha256(policy_json.encode("utf-8", errors="ignore")).hexdigest()[:16] if policy_json else ""
    key_obj = {
        "question": (state.get("question") or "")[:800],
        "history": history_text,
        "tenant_id": str(state.get("tenant_id") or ""),
        "account_id": account_id,
        "dataset_id": dataset_id,
        "document_ids": doc_ids_key,
        "embedding_space_hash": embedding_space,
        # Retrieval parameters (must match _retrieve_node defaults; avoid `or` because 0.0 is valid).
        "top_k": int(settings.RETRIEVAL_TOP_K if state.get("top_k") is None else state.get("top_k")),
        "score_threshold": float(
            settings.SIMILARITY_THRESHOLD if state.get("score_threshold") is None else state.get("score_threshold")
        ),
        "retrieval_mode": str(state.get("retrieval_mode") or "hybrid"),
        "retrieval_profile": str(state.get("retrieval_profile") or ""),
        "intent_router": state.get("intent_router"),
        "intent_router_policy_hash": policy_hash,
        # Query expansion knobs affect retrieval results; include them to avoid cache collisions.
        "enable_query_alias_expansion": state.get("enable_query_alias_expansion"),
        "query_alias_max_queries": state.get("query_alias_max_queries"),
        "query_aliases": state.get("query_aliases") or None,
        "enable_multi_query": state.get("enable_multi_query"),
        "multi_query_count": state.get("multi_query_count"),
        "multi_query_temperature": state.get("multi_query_temperature"),
        "multi_query_max_chars": state.get("multi_query_max_chars"),
        "enable_hyde": state.get("enable_hyde"),
        "enable_query_rewrite": state.get("enable_query_rewrite"),
        "enable_kg_query_expansion": state.get("enable_kg_query_expansion"),
        "enable_kg_chunk_injection": state.get("enable_kg_chunk_injection"),
        "kg_chunk_injection_max_chunks": state.get("kg_chunk_injection_max_chunks"),
        "enable_kg_chunk_boost": state.get("enable_kg_chunk_boost"),
        "kg_chunk_boost_weight": state.get("kg_chunk_boost_weight"),
        "kg_chunk_boost_max_promoted": state.get("kg_chunk_boost_max_promoted"),
        "lexical_db_hybrid_metadata_exact_fallback_enabled": state.get(
            "lexical_db_hybrid_metadata_exact_fallback_enabled"
        ),
        "metadata_exact_db_fallback_enabled": state.get("metadata_exact_db_fallback_enabled"),
        "query_rewrite_strategy": state.get("query_rewrite_strategy"),
        "query_rewrite_temperature": state.get("query_rewrite_temperature"),
        "query_rewrite_max_chars": state.get("query_rewrite_max_chars"),
        "alpha": float(settings.RETRIEVAL_DEFAULT_ALPHA if state.get("alpha") is None else state.get("alpha")),
        "enable_weight_rerank": bool(
            True if state.get("enable_weight_rerank") is None else state.get("enable_weight_rerank")
        ),
        "vector_weight": float(0.6 if state.get("vector_weight") is None else state.get("vector_weight")),
        "keyword_weight": float(0.4 if state.get("keyword_weight") is None else state.get("keyword_weight")),
        "mmr_lambda": float(
            settings.RETRIEVAL_MMR_LAMBDA if state.get("mmr_lambda") is None else state.get("mmr_lambda")
        ),
        "enable_reranker": bool(
            settings.ENABLE_RERANKER if state.get("enable_reranker") is None else state.get("enable_reranker")
        ),
        "reranker_provider": str(
            (settings.RERANKER_PROVIDER if state.get("reranker_provider") is None else state.get("reranker_provider"))
            or ""
        ),
        "reranker_top_n": int(
            settings.RERANKER_TOP_N if state.get("reranker_top_n") is None else state.get("reranker_top_n")
        ),
        "sparse_retrieval_enabled": state.get("sparse_retrieval_enabled"),
        "sparse_retrieval_provider": state.get("sparse_retrieval_provider"),
        "metadata_filter": state.get("metadata_filter") or None,
    }
    return json.dumps(key_obj, ensure_ascii=False, sort_keys=True, default=str)


_RAG_RETRIEVE_CACHE_POLICY = (
    CachePolicy(key_func=_retrieve_cache_key, ttl=_RAG_RETRIEVE_CACHE_TTL_SEC)
    if _RAG_RETRIEVE_CACHE_TTL_SEC > 0
    else None
)


def _build_context(docs: list[Document], *, query: str | None = None) -> str:
    """Format retrieved document context."""
    if not docs:
        return "No relevant reference materials found."

    usable_docs = _prepare_context_docs(docs, query=query)

    parts = []
    max_per_chunk_chars = max(0, int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0))
    max_total_chars = max(0, int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0))
    max_per_chunk_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0) or 0))
    max_total_tokens = max(0, int(getattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0) or 0))
    total_chars = 0
    total_tokens = 0
    for idx, doc in enumerate(usable_docs, 1):
        part = _build_context_part(
            doc,
            idx=idx,
            query=query,
            max_per_chunk_chars=max_per_chunk_chars,
            max_per_chunk_tokens=max_per_chunk_tokens,
        )
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


def _prepare_context_docs(docs: list[Document], *, query: str | None) -> list[Document]:
    usable_docs = _denoise_context_docs(docs)
    if bool(getattr(settings, "RAG_CONTEXT_LLM_COMPRESSION_ENABLED", False)):
        return _compress_context_docs_with_llm(usable_docs, query=query)
    if bool(getattr(settings, "RAG_CONTEXT_COMPRESSION_ENABLED", False)):
        usable_docs = _compress_context_docs(usable_docs, query=query)
    if bool(getattr(settings, "RAG_CONTEXT_REORDER_ENABLED", False)):
        usable_docs = _reorder_context_docs(usable_docs)
    return usable_docs


def _denoise_context_docs(docs: list[Document]) -> list[Document]:
    try:
        from app.rag.core.context_denoise import denoise_context_docs

        return denoise_context_docs(docs) or list(docs)
    except Exception as exc:
        logger.debug("Context denoise failed, falling back to raw docs: %s", exc)
        return list(docs)


def _compress_context_docs_with_llm(docs: list[Document], *, query: str | None) -> list[Document]:
    try:
        from app.rag.core.context_denoise import compress_context_docs_with_llm

        return compress_context_docs_with_llm(docs, query=query) or list(docs)
    except Exception as exc:
        logger.debug("LLM context compression failed, skipping compression: %s", exc)
        return list(docs)


def _compress_context_docs(docs: list[Document], *, query: str | None) -> list[Document]:
    try:
        from app.rag.core.context_compression import compress_context_docs

        return compress_context_docs(docs, query=query) or list(docs)
    except Exception as exc:
        logger.debug("Context compression failed, skipping compression: %s", exc)
        return list(docs)


def _reorder_context_docs(docs: list[Document]) -> list[Document]:
    try:
        from app.rag.core.doc_ordering import reorder_docs_for_generation

        return reorder_docs_for_generation(docs) or list(docs)
    except Exception as exc:
        logger.debug("Context doc ordering failed, skipping reorder: %s", exc)
        return list(docs)


def _context_page_info(meta: dict[str, Any]) -> str | None:
    try:
        page_raw = meta.get("page")
        page_int = int(page_raw) if page_raw is not None else None
    except Exception:
        return None
    if page_int and page_int > 0:
        return f"Page {page_int}"
    return None


def _context_role_info(meta: dict[str, Any]) -> str | None:
    retrieval_role = meta.get("retrieval_role")
    if retrieval_role == "neighbor":
        return "neighbor"
    if retrieval_role:
        return str(retrieval_role)
    return None


def _context_content(
    doc: Document,
    *,
    query: str | None,
    max_per_chunk_chars: int,
    max_per_chunk_tokens: int,
) -> str:
    raw_content = str(doc.page_content or "").strip()
    if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED) and query:
        return extract_evidence_text(
            raw_content,
            str(query),
            max_chars=(max_per_chunk_chars if not max_per_chunk_tokens else 0),
            max_sentences=settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK,
            min_sentence_chars=settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS,
        )
    if max_per_chunk_tokens:
        return truncate(raw_content, max_per_chunk_tokens)
    if max_per_chunk_chars and len(raw_content) > max_per_chunk_chars:
        return raw_content[:max_per_chunk_chars] + "..."
    return raw_content


def _build_context_part(
    doc: Document,
    *,
    idx: int,
    query: str | None,
    max_per_chunk_chars: int,
    max_per_chunk_tokens: int,
) -> str:
    meta = doc.metadata or {}
    filename = str(meta.get("filename") or "").strip()
    source = str(meta.get("source") or filename or "Unknown")
    info_parts: list[str] = []
    title = str(meta.get("document_title") or meta.get("doc_title") or meta.get("title") or "").strip()
    if title:
        info_parts.append(f"Title: {title}")
    if filename:
        info_parts.append(f"File: {filename}")
    elif source:
        info_parts.append(source)
    for value in (
        _context_page_info(meta),
        meta.get("header_path") or meta.get("header_context"),
        _context_role_info(meta),
    ):
        if value:
            info_parts.append(str(value))
    content = _context_content(
        doc,
        query=query,
        max_per_chunk_chars=max_per_chunk_chars,
        max_per_chunk_tokens=max_per_chunk_tokens,
    )
    return f"[Source {idx}: {' | '.join(info_parts)}]\n{content}"


def _build_history_text(history: list[dict[str, str]] | None) -> str:
    """Compress history to readable text, keep only within window."""
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _run_with_retry(node_name: str, func, state: RAGState) -> RAGState:
    """Collect node attempt metrics; LangGraph owns retry policy."""
    metrics = dict(state.get("metrics") or {})
    attempts = int(metrics.get(f"{node_name}_attempts", 0) or 0) + 1

    try:
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
    from app.rag.retrieval.orchestrator import run_retrieval

    cancel_event = None
    with contextlib.suppress(RuntimeError):
        runtime = get_runtime(RAGRuntimeContext)
        cancel_event = getattr(getattr(runtime, "context", None), "cancel_event", None)

    def retrieve_with_session() -> RAGState:
        db = SessionLocal()
        try:
            retrieval_state = dict(state)
            retrieval_state["db"] = db
            result = dict(run_retrieval(retrieval_state))
            result.pop("db", None)
            return cast(RAGState, result)
        finally:
            with contextlib.suppress(Exception):
                db.rollback()
            db.close()

    return run_blocking_retrieval_call_sync(  # type: ignore[return-value]
        retrieve_with_session,
        cancel_event=cancel_event,
    )


def _generate_node(state: RAGState) -> RAGState:
    # Grounding guard: retrieval already decided to abstain, skip generation.
    if bool(state.get("abstain_triggered")):
        return _generate_abstain_result(state)
    return _generate_standard_result(state)


def _generate_abstain_result(state: RAGState) -> RAGState:
    _engine, llm, route, reason, model_used = _prepare_generation_model(state)
    abstain_message = build_abstain_answer_message(state.get("abstain_reason"))
    answer = _abstain_answer_payload(state, abstain_message=abstain_message)
    metrics = dict(state.get("metrics") or {})
    followup_questions = derive_followup_questions(metrics.get("abstain_followup"))
    faithfulness_meta = _compute_generation_faithfulness(
        answer=answer,
        docs=state.get("docs") or [],
        verifier_mode=_normalized_claim_verifier_mode(),
        verifier_enable_contradiction_check=bool(
            getattr(settings, "RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK", True)
        ),
    )
    _apply_common_generation_metrics(
        metrics=metrics,
        faithfulness_meta=faithfulness_meta,
        confidence_meta=_generation_confidence_meta(metrics=metrics, faithfulness_meta=faithfulness_meta),
        followup_questions=followup_questions,
        route=route,
        model_used=model_used,
        generation_elapsed=0.0,
        prompt_state=state,
    )
    metrics["sentence_citations_count"] = 0
    metrics["sentence_citations"] = []
    metrics["sentence_citations_inline_enabled"] = bool(getattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", False))
    metrics["sentence_citations_inline_used"] = False
    metrics["sentence_citations_inline_count"] = 0
    return {
        **state,
        "answer": answer,
        "route": route,
        "model_used": model_used,
        "routing_reason": reason,
        "metrics": metrics,
        "followup_questions": followup_questions,
    }


def _generate_standard_result(state: RAGState) -> RAGState:
    engine, llm, route, reason, model_used = _prepare_generation_model(state)
    llm, generation_max_tokens = _apply_generation_max_tokens(llm, state)
    chain = _build_generation_chain(engine=engine, llm=llm, prompt_content=state.get("prompt_template_content"))
    ctx = _build_context(state.get("docs") or [], query=state.get("query_for_retrieval") or state.get("question"))
    hist_text = _build_history_text(state.get("history"))
    pii_on = bool(pii_redaction_enabled())
    answer, generation_elapsed = _invoke_generation_chain(
        chain=chain,
        state=state,
        ctx=ctx,
        hist_text=hist_text,
        pii_on=pii_on,
    )
    answer, source_identification_answer_used, followup_questions = _prepare_generation_answer(
        answer=answer,
        state=state,
        pii_on=pii_on,
    )
    claim_ctx = _generation_claim_context(state=state, ctx=ctx, pii_on=pii_on)
    answer, claim_meta = _apply_claim_check_to_answer(
        answer=answer,
        state=state,
        claim_ctx=claim_ctx,
    )
    claim_evidence = _build_claim_evidence_safe(
        answer=answer,
        state=state,
        claim_ctx=claim_ctx,
    )
    answer, sentence_meta = _render_generation_answer_extras(
        answer=answer,
        state=state,
        pii_on=pii_on,
        claim_ctx=claim_ctx,
        claim_evidence=claim_evidence,
    )
    faithfulness_meta = _compute_generation_faithfulness(
        answer=answer,
        docs=state.get("docs") or [],
        verifier_mode=str(claim_ctx["claim_verifier_mode"]),
        verifier_enable_contradiction_check=bool(claim_ctx["claim_verifier_enable_contradiction_check"]),
    )
    metrics = dict(state.get("metrics") or {})
    _populate_standard_generation_metrics(
        metrics=metrics,
        state=state,
        ctx=ctx,
        hist_text=hist_text,
        route=route,
        model_used=model_used,
        generation_elapsed=generation_elapsed,
        generation_max_tokens=generation_max_tokens,
        claim_ctx=claim_ctx,
        claim_meta=claim_meta,
        claim_evidence=claim_evidence,
        sentence_meta=sentence_meta,
        faithfulness_meta=faithfulness_meta,
        followup_questions=followup_questions,
        source_identification_answer_used=source_identification_answer_used,
    )
    return {
        **state,
        "answer": answer,
        "route": route,
        "model_used": model_used,
        "routing_reason": reason,
        "metrics": metrics,
        "followup_questions": list(followup_questions or []),
    }


def _prepare_generation_model(state: RAGState) -> tuple[Any, Any, str | None, str | None, str | None]:
    engine = get_rag_engine()
    llm, route, reason = engine._select_llm(state["question"], state.get("history"))  # type: ignore[attr-defined]
    model_used = getattr(llm, "model_name", None) or getattr(llm, "model", None)
    return engine, llm, route, reason, model_used


def _apply_generation_max_tokens(llm: Any, state: RAGState) -> tuple[Any, int]:
    generation_max_tokens = max(0, int(state.get("max_tokens") or 0))
    if generation_max_tokens > 0:
        llm = llm.bind(max_tokens=generation_max_tokens)
    return llm, generation_max_tokens


def _build_structured_citations(citations: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    return [
        {
            "document_id": citation.get("document_id"),
            "chunk_id": citation.get("chunk_id"),
            "page_number": citation.get("page_number"),
            "relevance_score": citation.get("relevance_score"),
        }
        for citation in citations[: max(0, int(top_k or 0))]
    ]


def _abstain_answer_payload(state: RAGState, *, abstain_message: str) -> str:
    if not bool(state.get("structured_output")):
        return abstain_message
    citations = state.get("citations") or []
    top_k = int(state.get("top_k", settings.RETRIEVAL_TOP_K) or settings.RETRIEVAL_TOP_K or 5)
    payload = build_structured_abstain_payload(
        preset=state.get("structured_preset"),
        answer=abstain_message,
        citations=_build_structured_citations(citations, top_k=top_k),
    )
    return json.dumps(payload, ensure_ascii=False)


def _build_generation_chain(*, engine: Any, llm: Any, prompt_content: Any) -> Any:
    prompt_obj = engine.prompt_template
    if prompt_content:
        with contextlib.suppress(Exception):
            prompt_obj = ChatPromptTemplate.from_template(str(prompt_content))
    return prompt_obj | llm | StrOutputParser()


def _invoke_generation_chain(
    *,
    chain: Any,
    state: RAGState,
    ctx: str,
    hist_text: str,
    pii_on: bool,
) -> tuple[str, float]:
    start = time.time()
    answer = chain.invoke(
        {
            "context": redact_text(ctx) if pii_on else ctx,
            "history": redact_text(hist_text) if pii_on else hist_text,
            "question": redact_text(state["question"]) if pii_on else state["question"],
            "format_instructions": state.get("format_instructions", ""),
        }
    )
    rendered = redact_text(str(answer)) if pii_on else str(answer)
    return rendered, time.time() - start


def _prepare_generation_answer(
    *,
    answer: str,
    state: RAGState,
    pii_on: bool,
) -> tuple[str, bool, list[str]]:
    source_identification_answer_used = False
    if not bool(state.get("structured_output")):
        deterministic_source_answer = maybe_build_source_identification_answer(
            question=state["question"],
            docs=list(state.get("docs") or []),
        )
        if deterministic_source_answer:
            answer = redact_text(deterministic_source_answer) if pii_on else deterministic_source_answer
            source_identification_answer_used = True
    followup_questions: list[str] = []
    if not bool(state.get("structured_output")) and bool(getattr(settings, "RAG_FOLLOWUP_SUGGESTIONS_ENABLED", False)):
        answer, followup_questions = extract_followup_questions_from_answer(str(answer or ""), max_items=3)
    return answer, source_identification_answer_used, followup_questions


def _normalized_claim_verifier_mode() -> str:
    mode = str(getattr(settings, "RAG_CLAIM_VERIFIER_MODE", "token_overlap") or "token_overlap").strip().lower()
    return mode if mode in {"token_overlap", "semantic_heuristic", "strict"} else "token_overlap"


def _generation_claim_context(*, state: RAGState, ctx: str, pii_on: bool) -> dict[str, Any]:
    strict_visible = bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)) or bool(
        state.get("visible_evidence_only")
    )
    claim_check_configured = bool(getattr(settings, "RAG_CLAIM_CHECK_ENABLED", False)) or strict_visible
    claim_check_mode = "none"
    if claim_check_configured:
        claim_check_mode = "structured" if bool(state.get("structured_output")) else "text"
    return {
        "strict_visible": strict_visible,
        "claim_check_configured": claim_check_configured,
        "claim_check_mode": claim_check_mode,
        "claim_check_applied": claim_check_mode != "none",
        "claim_check_max_claims": max(1, int(getattr(settings, "RAG_CLAIM_CHECK_MAX_CLAIMS", 24) or 24)),
        "claim_verifier_mode": _normalized_claim_verifier_mode(),
        "claim_verifier_enable_contradiction_check": bool(
            getattr(settings, "RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK", True)
        ),
        "evidence_text": redact_text(ctx) if pii_on else ctx,
    }


def _claim_verifier_kwargs(claim_ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "verifier_mode": claim_ctx["claim_verifier_mode"],
        "verifier_enable_contradiction_check": claim_ctx["claim_verifier_enable_contradiction_check"],
        "use_nli_fallback": bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
        "nli_provider": str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
        "nli_model_name": str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
        "nli_timeout_sec": float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
    }


def _apply_claim_check_to_answer(
    *,
    answer: str,
    state: RAGState,
    claim_ctx: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    meta = {"claim_check_removed": 0, "claim_check_total": 0, "claim_check_removed_reasons": []}
    if not claim_ctx["claim_check_applied"]:
        return answer, meta
    if claim_ctx["claim_check_mode"] == "text":
        return _apply_text_claim_check(answer=answer, claim_ctx=claim_ctx)
    return _apply_structured_claim_check(answer=answer, state=state, claim_ctx=claim_ctx)


def _apply_text_claim_check(*, answer: str, claim_ctx: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    claims = split_into_claims(str(answer or ""), max_claims=int(claim_ctx["claim_check_max_claims"]))
    kept: list[str] = []
    removed_reasons: list[dict[str, Any]] = []
    for claim in claims:
        result = verify_claim_with_fallback(
            claim,
            claim_ctx["evidence_text"],
            **_claim_verifier_kwargs(claim_ctx),
        )
        if bool(result.supported):
            kept.append(claim)
            continue
        if len(removed_reasons) < 64:
            diag = result.diagnostics if isinstance(result.diagnostics, dict) else {}
            removed_reasons.append(
                {
                    "claim": str(claim or "")[:300],
                    "reason_code": str(diag.get("reason_code") or diag.get("reason") or "unsupported")[:120],
                    "contradiction_type": (
                        str(diag.get("contradiction_type"))[:120]
                        if diag.get("contradiction_type") is not None
                        else None
                    ),
                }
            )
    cleaned = "\n".join(kept).strip() or _UNABLE_TO_ANSWER_MESSAGE
    return cleaned, {
        "claim_check_removed": max(0, len(claims) - len(kept)),
        "claim_check_total": len(claims),
        "claim_check_removed_reasons": removed_reasons,
    }


def _apply_structured_claim_check(
    *,
    answer: str,
    state: RAGState,
    claim_ctx: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    structured_citations = _build_structured_citations(
        state.get("citations") or [],
        top_k=int(state.get("top_k") or 0),
    )
    parsed, _meta = parse_and_repair_structured_output(
        str(answer or ""),
        preset=state.get("structured_preset"),
        fallback_answer=_UNABLE_TO_ANSWER_MESSAGE,
        fallback_citations=structured_citations,
    )
    scrubbed, scrub_meta = scrub_structured_output_visible_evidence_only(
        parsed,
        evidence_text=claim_ctx["evidence_text"],
        max_claims=int(claim_ctx["claim_check_max_claims"]),
        **_claim_verifier_kwargs(claim_ctx),
    )
    if (
        isinstance(scrubbed, dict)
        and isinstance(scrubbed.get("answer"), str)
        and not str(scrubbed.get("answer") or "").strip()
    ):
        scrubbed["answer"] = _UNABLE_TO_ANSWER_MESSAGE
    removed_reasons = []
    if isinstance(scrub_meta, dict) and isinstance(scrub_meta.get("claim_check_removed_reasons"), list):
        removed_reasons = [x for x in scrub_meta["claim_check_removed_reasons"] if isinstance(x, dict)][:64]
    return json.dumps(scrubbed, ensure_ascii=False, separators=(",", ":")), {
        "claim_check_removed": int(scrub_meta.get("claims_removed") or 0) if isinstance(scrub_meta, dict) else 0,
        "claim_check_total": int(scrub_meta.get("claims_total") or 0) if isinstance(scrub_meta, dict) else 0,
        "claim_check_removed_reasons": removed_reasons,
    }


def _build_claim_evidence_safe(
    *,
    answer: str,
    state: RAGState,
    claim_ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    if bool(state.get("structured_output")):
        return []
    try:
        return build_claim_evidence_map(
            str(answer or ""),
            evidence_chunks=list(state.get("docs") or []),
            max_claims=int(claim_ctx["claim_check_max_claims"]) if claim_ctx["claim_check_configured"] else 24,
            **_claim_verifier_kwargs(claim_ctx),
        )
    except Exception:
        return []


def _render_generation_answer_extras(
    *,
    answer: str,
    state: RAGState,
    pii_on: bool,
    claim_ctx: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    sentence_meta = {
        "enabled": bool(getattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", False)),
        "style": str(getattr(settings, "SENTENCE_CITATIONS_INLINE_STYLE", "appendix") or "appendix").strip().lower()
        or "appendix",
        "used": False,
        "count": 0,
        "fallback_reason": None,
    }
    if sentence_meta["style"] not in {"appendix", "inline"}:
        sentence_meta["style"] = "appendix"
    answer, sentence_meta = _render_sentence_citation_variants(
        answer=answer,
        state=state,
        pii_on=pii_on,
        claim_ctx=claim_ctx,
        claim_evidence=claim_evidence,
        sentence_meta=sentence_meta,
    )
    answer = _append_related_images(answer=answer, state=state, pii_on=pii_on)
    return answer, sentence_meta


def _render_sentence_citation_variants(
    *,
    answer: str,
    state: RAGState,
    pii_on: bool,
    claim_ctx: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if bool(state.get("structured_output")) or not sentence_meta["enabled"]:
        return answer, sentence_meta
    if sentence_meta["style"] == "inline":
        answer, sentence_meta = _render_inline_sentence_citations(
            answer=answer,
            claim_ctx=claim_ctx,
            claim_evidence=claim_evidence,
            sentence_meta=sentence_meta,
        )
    if sentence_meta["style"] == "appendix":
        answer, sentence_meta = _render_appendix_sentence_citations(
            answer=answer,
            pii_on=pii_on,
            claim_evidence=claim_evidence,
            sentence_meta=sentence_meta,
        )
    return answer, sentence_meta


def _sentence_citation_render_limits() -> dict[str, int]:
    return {
        "max_items": max(0, int(getattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_ITEMS", 8) or 8)),
        "max_evidence_per_claim": max(
            1,
            int(getattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM", 2) or 2),
        ),
    }


def _render_inline_sentence_citations(
    *,
    answer: str,
    claim_ctx: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if claim_ctx["claim_check_mode"] != "text":
        sentence_meta["style"] = "appendix"
        sentence_meta["fallback_reason"] = "claim_check_not_text"
        return answer, sentence_meta
    limits = _sentence_citation_render_limits()
    inline_text, rendered_count = render_sentence_citations_inline(claim_evidence, **limits)
    if inline_text:
        sentence_meta["used"] = True
        sentence_meta["count"] = int(rendered_count or 0)
        return inline_text, sentence_meta
    sentence_meta["style"] = "appendix"
    sentence_meta["fallback_reason"] = "inline_render_empty"
    return answer, sentence_meta


def _render_appendix_sentence_citations(
    *,
    answer: str,
    pii_on: bool,
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    limits = _sentence_citation_render_limits()
    suffix_md, rendered_count = render_sentence_citations_markdown(claim_evidence, **limits)
    if not suffix_md:
        return answer, sentence_meta
    answer = (answer or "") + (redact_text(suffix_md) if pii_on else suffix_md)
    sentence_meta["used"] = True
    sentence_meta["count"] = int(rendered_count or 0)
    return answer, sentence_meta


def _append_related_images(*, answer: str, state: RAGState, pii_on: bool) -> str:
    if (
        bool(state.get("structured_output"))
        or not bool(settings.SHOW_IMAGE_IN_ANSWER)
        or settings.IMAGE_APPEND_MAX <= 0
    ):
        return answer
    image_urls = _answer_image_urls(state.get("citations") or [])
    if not image_urls:
        return answer
    parts = ["\n\n---\n\n### Related Images\n"]
    parts.extend(f"![Referenced Image {idx}]({url})" for idx, url in enumerate(image_urls, 1))
    images_md = "\n\n".join(parts) + "\n"
    return (answer or "") + (redact_text(images_md) if pii_on else images_md)


def _answer_image_urls(citations: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for citation in citations:
        if not citation.get("has_image"):
            continue
        url = citation.get("img_url")
        if not isinstance(url, str) or not url.strip() or url in urls:
            continue
        urls.append(url)
        if len(urls) >= settings.IMAGE_APPEND_MAX:
            break
    return urls


def _generation_evidence_text(docs: list[Document]) -> str:
    evidence_text = "\n".join(
        str(getattr(doc, "page_content", "") or "")
        for doc in docs
        if str(getattr(doc, "page_content", "") or "").strip()
    )
    max_evidence_chars = max(0, int(getattr(settings, "FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS", 24_000) or 24_000))
    if max_evidence_chars and len(evidence_text) > max_evidence_chars:
        return evidence_text[:max_evidence_chars]
    return evidence_text


def _compute_generation_faithfulness(
    *,
    answer: str,
    docs: list[Document],
    verifier_mode: str,
    verifier_enable_contradiction_check: bool,
) -> dict[str, Any]:
    faithfulness_meta: dict[str, Any] = {
        "score": None,
        "supported_claims": 0,
        "total_claims": 0,
        "unsupported_claims": [],
        "method": "claim_support_ratio",
    }
    if not bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True)):
        return faithfulness_meta
    return compute_faithfulness_score(
        answer=str(answer or ""),
        evidence_text=_generation_evidence_text(docs),
        max_claims=max(1, int(getattr(settings, "FAITHFULNESS_SCORE_MAX_CLAIMS", 24) or 24)),
        verifier_mode=verifier_mode,
        verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
        use_nli_fallback=bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
        nli_provider=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
        nli_model_name=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
        nli_timeout_sec=float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
    )


def _retrieval_gap(metrics: dict[str, Any]) -> dict[str, Any] | None:
    gap = metrics.get("iterative_pass_gap")
    if isinstance(gap, dict):
        return gap
    fallback_gap = metrics.get("evidence_gap")
    return fallback_gap if isinstance(fallback_gap, dict) else None


def _generation_confidence_meta(
    *,
    metrics: dict[str, Any],
    faithfulness_meta: dict[str, Any],
) -> dict[str, Any]:
    return compute_confidence_score(
        faithfulness_score=faithfulness_meta.get("score"),
        claim_total=faithfulness_meta.get("total_claims"),
        claim_supported=faithfulness_meta.get("supported_claims"),
        evidence_gap=_retrieval_gap(metrics),
    )


def _apply_common_generation_metrics(
    *,
    metrics: dict[str, Any],
    faithfulness_meta: dict[str, Any],
    confidence_meta: dict[str, Any],
    followup_questions: list[str],
    route: str | None,
    model_used: str | None,
    generation_elapsed: float,
    prompt_state: RAGState,
) -> None:
    metrics["generation_elapsed_sec"] = round(float(generation_elapsed), 3)
    metrics["context_evidence_enabled"] = bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
    metrics["context_evidence_max_sentences_per_chunk"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK or 0)
        if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
        else None
    )
    metrics["context_evidence_min_sentence_chars"] = (
        int(settings.RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS or 0)
        if bool(settings.RAG_CONTEXT_EVIDENCE_ENABLED)
        else None
    )
    metrics["faithfulness_score_enabled"] = bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True))
    metrics["faithfulness_score_method"] = str(faithfulness_meta.get("method") or "claim_support_ratio")
    metrics["faithfulness_score"] = faithfulness_meta.get("score")
    metrics["faithfulness_supported_claims"] = int(faithfulness_meta.get("supported_claims") or 0)
    metrics["faithfulness_total_claims"] = int(faithfulness_meta.get("total_claims") or 0)
    metrics["faithfulness_unsupported_claims"] = list(faithfulness_meta.get("unsupported_claims") or [])
    metrics["confidence_score"] = confidence_meta.get("score")
    metrics["confidence_band"] = confidence_meta.get("band")
    metrics["confidence_reasons"] = list(confidence_meta.get("reasons") or [])
    metrics["followup_questions"] = list(followup_questions or [])
    metrics["elapsed_sec"] = round(
        float(generation_elapsed)
        + float(metrics.get("retrieval_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("rewrite_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("multi_query_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("hyde_elapsed_sec", 0.0) or 0.0)
        + float(metrics.get("decompose_elapsed_sec", 0.0) or 0.0),
        3,
    )
    metrics["model_route"] = route
    metrics["model_used"] = model_used
    metrics["llm_max_retries"] = settings.LLM_MAX_RETRIES
    metrics["prompt_template_id"] = prompt_state.get("prompt_template_id")
    metrics["prompt_template_key"] = prompt_state.get("prompt_template_key")
    metrics["prompt_ab_experiment_key"] = prompt_state.get("prompt_ab_experiment_key")
    metrics["prompt_ab_variant"] = prompt_state.get("prompt_ab_variant")


def _populate_standard_generation_metrics(
    *,
    metrics: dict[str, Any],
    state: RAGState,
    ctx: str,
    hist_text: str,
    route: str | None,
    model_used: str | None,
    generation_elapsed: float,
    generation_max_tokens: int,
    claim_ctx: dict[str, Any],
    claim_meta: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
    faithfulness_meta: dict[str, Any],
    followup_questions: list[str],
    source_identification_answer_used: bool,
) -> None:
    _apply_common_generation_metrics(
        metrics=metrics,
        faithfulness_meta=faithfulness_meta,
        confidence_meta=_generation_confidence_meta(metrics=metrics, faithfulness_meta=faithfulness_meta),
        followup_questions=followup_questions,
        route=route,
        model_used=model_used,
        generation_elapsed=generation_elapsed,
        prompt_state=state,
    )
    metrics["context_chars"] = len(ctx or "")
    metrics["context_tokens"] = num_tokens_from_string(ctx or "")
    metrics.update(
        compute_context_cliff_metrics(
            context_tokens=int(metrics["context_tokens"] or 0),
            threshold_tokens=int(getattr(settings, "RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS", 2500) or 2500),
        )
    )
    metrics["history_chars"] = len(hist_text or "")
    metrics["history_tokens"] = num_tokens_from_string(hist_text or "")
    metrics["question_chars"] = len(state.get("question") or "")
    metrics["question_tokens"] = num_tokens_from_string(state.get("question") or "")
    metrics["context_limit_total_chars"] = int(settings.RAG_CONTEXT_MAX_TOTAL_CHARS or 0)
    metrics["context_limit_total_tokens"] = int(getattr(settings, "RAG_CONTEXT_MAX_TOTAL_TOKENS", 0) or 0)
    metrics["context_limit_per_chunk_chars"] = int(settings.RAG_CONTEXT_MAX_CHARS_PER_CHUNK or 0)
    metrics["context_limit_per_chunk_tokens"] = int(getattr(settings, "RAG_CONTEXT_MAX_TOKENS_PER_CHUNK", 0) or 0)
    metrics["claim_check_enabled"] = bool(claim_ctx["claim_check_applied"])
    metrics["claim_check_mode"] = claim_ctx["claim_check_mode"]
    metrics["claim_verifier_mode"] = claim_ctx["claim_verifier_mode"]
    metrics["claim_verifier_enable_contradiction_check"] = bool(claim_ctx["claim_verifier_enable_contradiction_check"])
    metrics["claim_check_removed"] = int(claim_meta.get("claim_check_removed") or 0)
    metrics["claim_check_total"] = int(claim_meta.get("claim_check_total") or 0)
    metrics["claim_check_removed_reasons"] = list(claim_meta.get("claim_check_removed_reasons") or [])
    metrics["claim_check_max_claims"] = (
        int(claim_ctx["claim_check_max_claims"]) if claim_ctx["claim_check_configured"] else None
    )
    metrics["claim_nli_verifier"] = {
        "enabled": bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
        "provider": str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
        "model_name": str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
    }
    metrics["claim_evidence"] = claim_evidence
    metrics["sentence_citations_count"] = int(len(claim_evidence or []))
    metrics["sentence_citations"] = claim_evidence
    metrics["sentence_citations_inline_enabled"] = bool(sentence_meta["enabled"])
    metrics["sentence_citations_inline_style"] = str(sentence_meta["style"])
    metrics["sentence_citations_inline_used"] = bool(sentence_meta["used"])
    metrics["sentence_citations_inline_count"] = int(sentence_meta["count"] or 0)
    metrics["sentence_citations_inline_fallback_reason"] = sentence_meta["fallback_reason"]
    metrics["visible_evidence_only_enabled"] = bool(claim_ctx["strict_visible"])
    metrics["visible_evidence_only_requested"] = bool(state.get("visible_evidence_only"))
    metrics["generation_max_tokens"] = generation_max_tokens or None
    metrics["source_identification_answer_used"] = bool(source_identification_answer_used)


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
def retrieve_task(state: dict[str, Any]) -> dict[str, Any]:
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
def generate_task(state: dict[str, Any]) -> dict[str, Any]:
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


def _run_corrective_loop(
    state: dict[str, Any],
    *,
    retrieve_fn: Callable[[dict[str, Any]], dict[str, Any]],
    generate_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """
    Minimal CRAG-like loop (feature-flagged):
    - If retrieval abstains (weak/empty evidence): retry with a recall-first profile.
    - If answer faithfulness is low: retry retrieval + generation once (bounded).

    This is intentionally conservative:
    - small number of attempts
    - deterministic overrides (profile + multi-query)
    - metrics include a compact corrective summary for debugging.
    """
    corrective_enabled = bool(getattr(settings, "RAG_CORRECTIVE_ENABLED", False))
    max_attempts_raw = int(getattr(settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2) or 2)
    max_attempts = max(1, min(max_attempts_raw, 3))
    min_faithfulness = float(getattr(settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.75) or 0.75)
    min_faithfulness = min(1.0, max(0.0, float(min_faithfulness)))

    # Second-pass retrieval overrides (best-effort).
    second_profile = (
        str(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_PROFILE", "recall50") or "recall50").strip().lower()
    )
    if second_profile not in {"recall20", "recall50", "coverage80", "hierarchy_recall20", "hierarchy_recall20_expand"}:
        second_profile = "recall50"
    second_enable_mq = bool(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY", True))
    second_mq_count = int(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT", 5) or 5)
    second_mq_count = max(0, min(second_mq_count, int(getattr(settings, "MULTI_QUERY_COUNT_CAP", 8) or 8)))

    base_state = dict(state or {})
    metrics0 = dict(base_state.get("metrics") or {})
    attempt_summaries: list[dict[str, Any]] = []
    reason_codes: list[str] = []
    used = False

    last_state: dict[str, Any] = dict(base_state)

    if not corrective_enabled or max_attempts <= 1:
        last_state = retrieve_fn(dict(base_state))
        last_state = generate_fn(dict(last_state))
        return last_state

    for attempt in range(1, max_attempts + 1):
        attempt_result = _run_corrective_attempt(
            base_state=base_state,
            metrics=metrics0,
            attempt=attempt,
            max_attempts=max_attempts,
            second_profile=second_profile,
            second_enable_mq=second_enable_mq,
            second_mq_count=second_mq_count,
            min_faithfulness=min_faithfulness,
            retrieve_fn=retrieve_fn,
            generate_fn=generate_fn,
        )
        last_state = attempt_result["state"]
        metrics0 = dict(last_state.get("metrics") or {})
        attempt_summaries.append(attempt_result["summary"])
        used = bool(used or attempt_result["used_second_pass"])
        reason_code = attempt_result["reason_code"]
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
        if not attempt_result["retry"]:
            break

    # Attach a compact summary for debugging (PII-safe).
    metrics_final = dict(last_state.get("metrics") or {})
    metrics_final["corrective_enabled"] = bool(corrective_enabled)
    metrics_final["corrective_used"] = bool(used)
    metrics_final["corrective_max_attempts"] = int(max_attempts)
    metrics_final["corrective_reason_codes"] = list(reason_codes or [])[:8]
    metrics_final["corrective_attempts"] = attempt_summaries[:3]
    metrics_final["corrective_second_pass"] = {
        "retrieval_profile": second_profile,
        "enable_multi_query": bool(second_enable_mq),
        "multi_query_count": int(second_mq_count),
    }
    last_state["metrics"] = metrics_final
    return last_state


def _run_corrective_attempt(
    *,
    base_state: dict[str, Any],
    metrics: dict[str, Any],
    attempt: int,
    max_attempts: int,
    second_profile: str,
    second_enable_mq: bool,
    second_mq_count: int,
    min_faithfulness: float,
    retrieve_fn: Callable[[dict[str, Any]], dict[str, Any]],
    generate_fn: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    attempt_state = dict(base_state)
    attempt_metrics = dict(metrics)
    attempt_metrics["corrective_attempt"] = int(attempt)
    attempt_state["metrics"] = attempt_metrics
    used_second_pass = attempt > 1
    if used_second_pass:
        attempt_state["retrieval_profile"] = second_profile
        if second_enable_mq:
            attempt_state["enable_multi_query"] = True
            attempt_state["multi_query_count"] = int(second_mq_count)

    retrieved = dict(retrieve_fn(attempt_state) or {})
    retrieval_metrics = dict(retrieved.get("metrics") or {})
    summary = {
        "attempt": int(attempt),
        "retrieval_profile": retrieved.get("retrieval_profile"),
        "top_k": retrieved.get("top_k"),
        "retrieval_mode": retrieval_metrics.get("retrieval_mode") or retrieved.get("retrieval_mode"),
        "abstain_triggered": bool(retrieved.get("abstain_triggered")),
    }
    if bool(retrieved.get("abstain_triggered")):
        return {
            "state": retrieved,
            "summary": summary,
            "used_second_pass": used_second_pass,
            "reason_code": "abstain" if attempt < max_attempts else None,
            "retry": attempt < max_attempts,
        }

    generated = dict(generate_fn(retrieved) or {})
    generation_metrics = dict(generated.get("metrics") or {})
    faithfulness_score = generation_metrics.get("faithfulness_score")
    summary.update(
        {
            "faithfulness_score": faithfulness_score,
            "claim_check_removed": generation_metrics.get("claim_check_removed"),
            "claim_check_total": generation_metrics.get("claim_check_total"),
        }
    )
    low_faithfulness = _faithfulness_below_threshold(
        faithfulness_score=faithfulness_score,
        min_faithfulness=min_faithfulness,
    )
    return {
        "state": generated,
        "summary": summary,
        "used_second_pass": used_second_pass,
        "reason_code": "faithfulness_lt_min" if low_faithfulness and attempt < max_attempts else None,
        "retry": bool(low_faithfulness and attempt < max_attempts),
    }


def _faithfulness_below_threshold(*, faithfulness_score: Any, min_faithfulness: float) -> bool:
    try:
        return faithfulness_score is not None and float(faithfulness_score) < float(min_faithfulness)
    except Exception:
        return False


@entrypoint(checkpointer=_get_checkpointer(), store=get_langgraph_store(), context_schema=RAGRuntimeContext)
def rag_workflow(state: dict[str, Any], runtime: Runtime[RAGRuntimeContext]) -> dict[str, Any]:
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

    state = _run_corrective_loop(
        state,
        retrieve_fn=lambda s: retrieve_task(s).result(),
        generate_fn=lambda s: generate_task(s).result(),
    )

    return state


def run_rag_workflow_functional(
    state: dict[str, Any],
    *,
    thread_id: str | None = None,
    stream_mode: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute RAG workflow using Functional API.

    Args:
        state: RAG state dictionary
        thread_id: Optional thread ID for session persistence
        stream_mode: Streaming mode ("updates", "values", None)

    Returns:
        Execution result state
    """
    state = dict(state)
    state.pop("db", None)
    recursion_limit = max(1, int(getattr(settings, "LANGGRAPH_RECURSION_LIMIT", 25) or 25))
    config: dict[str, Any] = {
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


@dataclass(frozen=True)
class RagStateBuildOptions:
    question: str
    history: list[dict[str, str]] | None = None
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    request_id: str | None = None
    account_id: str | None = None
    dataset_id: UUID | None = None
    dataset_ids: list[UUID] | None = None
    top_k: int = 5
    score_threshold: float = 0.7
    retrieval_mode: str = "hybrid"
    retrieval_profile: str | None = None
    retrieval_contract_mode: str | None = None
    must_recall: bool | None = None
    must_recall_expected_source_keys: list[str] | None = None
    must_recall_required_anchor_fields: list[str] | None = None
    intent_router: bool | None = None
    intent_router_policy: dict[str, Any] | None = None
    industry_rules_enabled: bool | None = None
    industry_rules_rulesets: list[str] | str | None = None
    enable_query_alias_expansion: bool | None = None
    query_aliases: dict[str, list[str]] | None = None
    query_alias_max_queries: int | None = None
    enable_multi_query: bool | None = None
    multi_query_count: int | None = None
    multi_query_temperature: float | None = None
    multi_query_max_chars: int | None = None
    enable_hyde: bool | None = None
    enable_query_decomposition: bool | None = None
    enable_hierarchy_recall: bool | None = None
    hierarchy_family_collapse: bool | None = None
    hierarchy_family_aggregation: str | None = None
    hierarchy_tree_dedup: bool | None = None
    hierarchy_parent_depth: int | None = None
    hierarchy_sibling_window: int | None = None
    hierarchy_overfetch_factor: int | None = None
    enable_kg_query_expansion: bool | None = None
    enable_kg_chunk_injection: bool | None = None
    kg_chunk_injection_max_chunks: int | None = None
    enable_kg_chunk_boost: bool | None = None
    kg_chunk_boost_weight: float | None = None
    kg_chunk_boost_max_promoted: int | None = None
    enable_query_rewrite: bool | None = None
    query_rewrite_strategy: str | None = None
    query_rewrite_temperature: float | None = None
    query_rewrite_max_chars: int | None = None
    sparse_retrieval_enabled: bool | None = None
    sparse_retrieval_provider: str | None = None
    lexical_db_hybrid_fallback_only: bool | None = None
    lexical_db_hybrid_metadata_exact_fallback_enabled: bool | None = None
    metadata_exact_db_fallback_enabled: bool | None = None
    alpha: float = settings.RETRIEVAL_DEFAULT_ALPHA
    fusion_strategy: str | None = None
    fusion_budgets: dict[str, int] | None = None
    fusion_min_scores: dict[str, float] | None = None
    fusion_weights: dict[str, float] | None = None
    retrieval_overfetch_multiplier: int | None = None
    retrieval_overfetch_max_k: int | None = None
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    mmr_lambda: float = settings.RETRIEVAL_MMR_LAMBDA
    enable_reranker: bool = settings.ENABLE_RERANKER
    reranker_provider: str | None = settings.RERANKER_PROVIDER
    reranker_top_n: int = settings.RERANKER_TOP_N
    metadata_filter: dict[str, Any] | None = None
    max_tokens: int | None = None
    structured_output: bool = False
    structured_preset: str | None = None
    visible_evidence_only: bool = False
    prompt_template_id: UUID | None = None
    prompt_template_key: str | None = None
    prompt_ab_experiment_key: str | None = None
    ab_user_key: str | None = None
    db: Any | None = None


def _resolve_rag_state_build_options(
    *,
    options: RagStateBuildOptions | None,
    legacy_overrides: dict[str, Any],
) -> RagStateBuildOptions:
    if options is None:
        return RagStateBuildOptions(**legacy_overrides)
    if not legacy_overrides:
        return options
    return cast(RagStateBuildOptions, replace(options, **legacy_overrides))


def build_rag_state(
    *,
    options: RagStateBuildOptions | None = None,
    **legacy_overrides: Any,
) -> dict[str, Any]:
    """Build initial RAG graph state shared by run/stream entrypoints."""

    resolved = _resolve_rag_state_build_options(options=options, legacy_overrides=legacy_overrides)
    state = asdict(resolved)
    state["history"] = resolved.history or []
    state["intent_router_policy"] = _normalize_intent_router_policy_or_none(resolved.intent_router_policy)
    state["format_instructions"] = (
        build_structured_output_instructions(resolved.structured_preset) if resolved.structured_output else ""
    )
    state.update(
        _resolve_prompt_template_fields(
            db=resolved.db,
            tenant_id=resolved.tenant_id,
            prompt_template_id=resolved.prompt_template_id,
            prompt_template_key=resolved.prompt_template_key,
            prompt_ab_experiment_key=resolved.prompt_ab_experiment_key,
            ab_user_key=resolved.ab_user_key,
        )
    )
    state["metadata_filter"] = _apply_active_pipeline_metadata_filter(
        db=resolved.db,
        tenant_id=resolved.tenant_id,
        document_ids=resolved.document_ids,
        metadata_filter=resolved.metadata_filter,
    )
    _apply_profile_overrides_to_state(state)
    state["structured_output"] = bool(resolved.structured_output)
    state["visible_evidence_only"] = bool(resolved.visible_evidence_only)
    state.pop("db", None)
    state.pop("ab_user_key", None)
    return state


def _normalize_intent_router_policy_or_none(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    try:
        from app.rag.policy.intent_router import normalize_intent_router_policy

        return normalize_intent_router_policy(policy)
    except Exception:
        return None


def _resolve_prompt_template_fields(
    *,
    db: Any,
    tenant_id: UUID | None,
    prompt_template_id: UUID | None,
    prompt_template_key: str | None,
    prompt_ab_experiment_key: str | None,
    ab_user_key: str | None,
) -> dict[str, Any]:
    fields = {
        "prompt_template_content": None,
        "prompt_template_id": None,
        "prompt_template_key": None,
        "prompt_ab_experiment_key": None,
        "prompt_ab_variant": None,
    }
    if not (db and tenant_id and (prompt_template_id or prompt_template_key or prompt_ab_experiment_key)):
        return fields
    chosen = resolve_prompt_template(
        db=db,
        tenant_id=tenant_id,
        prompt_template_id=prompt_template_id,
        template_key=prompt_template_key,
        ab_experiment_key=prompt_ab_experiment_key,
        ab_user_key=ab_user_key,
    )
    if not chosen:
        return fields
    chosen.usage_count += 1
    db.commit()
    fields.update(
        {
            "prompt_template_content": chosen.content,
            "prompt_template_id": str(chosen.id),
            "prompt_template_key": getattr(chosen, "template_key", None),
            "prompt_ab_experiment_key": getattr(chosen, "ab_experiment_key", None),
            "prompt_ab_variant": getattr(chosen, "ab_variant", None),
        }
    )
    return fields


def _apply_active_pipeline_metadata_filter(
    *,
    db: Any,
    tenant_id: UUID | None,
    document_ids: list[UUID] | None,
    metadata_filter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if db is None or tenant_id is None or not document_ids:
        return metadata_filter
    try:
        from app.models.document import Document as DBDocument

        rows = (
            db.query(DBDocument.id, DBDocument.status, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(document_ids)))
            .all()
        )
        active_keys = [
            f"{did}:{active_hash}"
            for did, status, meta in rows
            if (active_hash := _active_pipeline_hash(status=status, meta=meta))
        ]
        if not active_keys:
            return metadata_filter
        scoped_filter = dict(metadata_filter or {})
        scoped_filter["doc_pipeline_key"] = {"$in": set(active_keys)}
        return scoped_filter
    except Exception as exc:
        logger.debug("Ignoring active pipeline metadata filter synthesis failure: %s", exc)
        return metadata_filter


def _active_pipeline_hash(*, status: Any, meta: Any) -> str | None:
    metadata = meta if isinstance(meta, dict) else {}
    ready = (
        bool(metadata.get("active_pipeline_ready"))
        if "active_pipeline_ready" in metadata
        else (str(status or "").lower() == "completed")
    )
    if not ready:
        return None
    active_hash = str(metadata.get("active_pipeline_hash") or metadata.get("pipeline_hash") or "").strip()
    return active_hash or None


def _apply_profile_overrides_to_state(state: dict[str, Any]) -> None:
    profile_applied = apply_retrieval_profile_overrides(
        profile=state.get("retrieval_profile"),
        top_k=int(state.get("top_k") or 0),
        score_threshold=float(state.get("score_threshold") or 0.0),
        retrieval_mode=str(state.get("retrieval_mode") or "hybrid"),
        enable_reranker=bool(state.get("enable_reranker")),
        reranker_provider=state.get("reranker_provider"),
        reranker_top_n=int(state.get("reranker_top_n") or 0),
        enable_weight_rerank=bool(state.get("enable_weight_rerank")),
    )
    state["retrieval_profile"] = profile_applied.get("retrieval_profile")
    state["top_k"] = int(profile_applied.get("top_k") or 0)
    state["score_threshold"] = float(profile_applied.get("score_threshold") or 0.0)
    state["retrieval_mode"] = str(profile_applied.get("retrieval_mode") or state.get("retrieval_mode") or "hybrid")
    for key in (
        "enable_reranker",
        "reranker_provider",
        "reranker_top_n",
        "enable_weight_rerank",
        "sparse_retrieval_enabled",
        "sparse_retrieval_provider",
        "enable_hierarchy_recall",
        "hierarchy_family_collapse",
        "hierarchy_family_aggregation",
        "hierarchy_tree_dedup",
        "hierarchy_parent_depth",
        "hierarchy_sibling_window",
        "hierarchy_overfetch_factor",
    ):
        if profile_applied.get(key) is not None and profile_applied.get(key) != "":
            state[key] = profile_applied.get(key)


def run_rag_graph(
    question: str,
    history: list[dict[str, str]] | None = None,
    document_ids: list[UUID] | None = None,
    *args: Any,
    thread_id: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute LangGraph RAG flow, return answer/citations/model info."""
    # Backward compatibility: legacy signature supported a long list of positional args.
    legacy_positional_keys = [
        "tenant_id",
        "account_id",
        "dataset_id",
        "top_k",
        "score_threshold",
        "retrieval_mode",
        "retrieval_contract_mode",
        "thread_id",
        "runtime_context",
        "alpha",
        "enable_weight_rerank",
        "vector_weight",
        "keyword_weight",
        "mmr_lambda",
        "enable_reranker",
        "reranker_provider",
        "reranker_top_n",
        "metadata_filter",
        "structured_output",
        "structured_preset",
        "prompt_template_id",
        "prompt_template_key",
        "prompt_ab_experiment_key",
        "ab_user_key",
        "db",
    ]
    if args:
        if len(args) > len(legacy_positional_keys):
            raise TypeError(f"run_rag_graph() takes at most {3 + len(legacy_positional_keys)} positional arguments")
        for key, value in zip(legacy_positional_keys, args, strict=False):
            if key == "thread_id" and thread_id is None:
                thread_id = value if value is None else str(value)
                continue
            if key == "runtime_context" and runtime_context is None:
                runtime_context = value if value is None else dict(value)
                continue
            kwargs.setdefault(key, value)

    # Do not forward execution-only kwargs into build_rag_state.
    if "thread_id" in kwargs and thread_id is None:
        thread_id = kwargs.pop("thread_id")
    else:
        kwargs.pop("thread_id", None)

    if "runtime_context" in kwargs and runtime_context is None:
        runtime_context = kwargs.pop("runtime_context")
    else:
        kwargs.pop("runtime_context", None)

    state = build_rag_state(
        question=question,
        history=history or [],
        document_ids=document_ids,
        **kwargs,
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
]

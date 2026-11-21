"""Run retrieval, generation and bounded corrective tasks with LangGraph policies."""

import contextlib
import hashlib
import json
from collections.abc import Callable
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.func import task
from langgraph.runtime import get_runtime
from langgraph.types import CachePolicy, RetryPolicy

from app.infrastructure.config import settings
from app.infrastructure.database.connection import SessionLocal
from app.infrastructure.model_policy import reject_retired_retrieval_options
from app.rag.llm.prompts.templates import format_history_text
from app.rag.runtime.graph.generation import _generate_node
from app.rag.runtime.graph.state import RAGRuntimeContext, RAGState
from app.services.runtime.retrieval_limiter import run_blocking_retrieval_call_sync
from app.types.document_metadata import metadata_text

_RAG_TASK_RETRY_POLICY = RetryPolicy(
    max_attempts=max(1, int(settings.RAG_GRAPH_MAX_RETRIES) + 1),
    retry_on=lambda exc: not isinstance(exc, (ValueError, TypeError, KeyError)),
)


_RAG_RETRIEVE_CACHE_TTL_SEC = max(0, int(settings.RAG_GRAPH_CACHE_TTL_SEC))


def _retrieve_cache_key(state: dict[str, Any]) -> str:
    reject_retired_retrieval_options(state)
    history_text = format_history_text(state.get("history") or [], window=settings.CHAT_HISTORY_WINDOW)
    doc_ids = state.get("document_ids") or []
    doc_ids_key = ",".join(sorted(str(x) for x in doc_ids))
    # Security: retrieval is scoped by ACL and dataset; cache key MUST include account_id/dataset_id
    # to avoid cross-user leakage when cache is enabled.
    account_id = metadata_text(state, "account_id")
    dataset_id = metadata_text(state, "dataset_id")
    from app.rag.embedding.utils import current_embedding_space_hash

    embedding_space = current_embedding_space_hash()
    policy_json = ""
    raw_policy = state.get("intent_router_policy")
    if raw_policy is not None:
        policy_json = json.dumps(raw_policy, ensure_ascii=False, sort_keys=True, default=str)
    policy_hash = hashlib.sha256(policy_json.encode("utf-8", errors="ignore")).hexdigest()[:16] if policy_json else ""
    key_obj = {
        "question": state["question"],
        "history": history_text,
        "tenant_id": metadata_text(state, "tenant_id"),
        "account_id": account_id,
        "dataset_id": dataset_id,
        "dataset_ids": state.get("dataset_ids"),
        "document_ids": doc_ids_key,
        "document_scope_selected": state.get("document_ids") is not None,
        "embedding_space_hash": embedding_space,
        # Retrieval parameters (must match _retrieve_node defaults; avoid `or` because 0.0 is valid).
        "top_k": int(settings.RETRIEVAL_TOP_K if state.get("top_k") is None else state.get("top_k")),
        "score_threshold": float(
            settings.SIMILARITY_THRESHOLD if state.get("score_threshold") is None else state.get("score_threshold")
        ),
        "retrieval_mode": str(state.get("retrieval_mode") or "hybrid"),
        "retrieval_profile": metadata_text(state, "retrieval_profile"),
        "intent_router": state.get("intent_router"),
        "intent_router_policy_hash": policy_hash,
        # Query expansion knobs affect retrieval results; include them to avoid cache collisions.
        "enable_query_alias_expansion": state.get("enable_query_alias_expansion"),
        "query_alias_max_queries": state.get("query_alias_max_queries"),
        "query_aliases": state.get("query_aliases"),
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
        "reranker_provider": settings.RERANKER_PROVIDER
        if state.get("reranker_provider") is None
        else state["reranker_provider"],
        "reranker_top_n": int(
            settings.RERANKER_TOP_N if state.get("reranker_top_n") is None else state.get("reranker_top_n")
        ),
        "metadata_filter": state.get("metadata_filter"),
    }
    return json.dumps(key_obj, ensure_ascii=False, sort_keys=True, default=str)


_RAG_RETRIEVE_CACHE_POLICY = (
    CachePolicy(key_func=_retrieve_cache_key, ttl=_RAG_RETRIEVE_CACHE_TTL_SEC)
    if _RAG_RETRIEVE_CACHE_TTL_SEC > 0
    else None
)


def _run_with_retry(node_name: str, func: Callable[[RAGState], RAGState], state: RAGState) -> RAGState:
    """Collect node attempt metrics; LangGraph owns retry policy."""
    metrics = dict(state.get("metrics") or {})
    attempt_key = f"{node_name}_attempts"
    attempts = int(metrics.get(attempt_key, 0) or 0) + 1
    attempt_metrics = {attempt_key: attempts, f"{node_name}_retries": max(attempts - 1, 0)}

    try:
        result = func(state)

        merged = dict(metrics)
        merged.update(result.get("metrics") or {})
        merged.update(attempt_metrics)
        result["metrics"] = merged
        return result
    except Exception as exc:  # noqa: BLE001
        metrics.update(attempt_metrics)
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


@task(retry_policy=_RAG_TASK_RETRY_POLICY, cache_policy=_RAG_RETRIEVE_CACHE_POLICY)
def retrieve_task(state: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieval task - using Functional API @task decorator.

    Supports retry and timeout mechanisms, consistent with original _retrieve_node logic.
    """
    writer = None
    if settings.STREAM_WRITER_ENABLED:
        try:
            writer = get_stream_writer()
        except Exception:  # noqa: BLE001
            writer = None

    if writer:
        writer(
            {
                "event": "retrieve_start",
                "question": (state["question"])[:500],
                "retrieval_mode": state.get("retrieval_mode"),
                "top_k": state.get("top_k"),
            }
        )

    tracing_client = None
    try:
        from app.rag.tracing.langsmith import get_tracing_client

        tracing_client = get_tracing_client()
    except Exception:  # noqa: BLE001
        tracing_client = None

    if tracing_client and tracing_client.enabled:
        metrics_in = dict((state.get("metrics") or {}))
        with tracing_client.trace(
            name="rag_retrieve",
            run_type="retriever",
            inputs={
                "question": (state["question"])[:2000],
                "retrieval_mode": state.get("retrieval_mode"),
                "top_k": state.get("top_k"),
                "document_ids_count": len(state.get("document_ids") or []),
            },
            metadata={
                "request_id": metrics_in.get("request_id"),
                "conversation_id": metrics_in.get("conversation_id"),
                "tenant_id": metrics_in.get("tenant_id") or metadata_text(state, "tenant_id"),
                "account_id": metrics_in.get("account_id"),
            },
            tags=["rag", "langgraph", "retrieval"],
        ) as span:
            result = _run_with_retry("retrieve", _retrieve_node, state)
            citations = result.get("citations") or []
            metrics_out = result.get("metrics") or {}
            span.outputs = {
                "citations_count": len(citations),
                "query_for_retrieval": result["query_for_retrieval"][:2000],
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
                "query_for_retrieval": result["query_for_retrieval"][:500],
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
    if settings.STREAM_WRITER_ENABLED:
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
        from app.rag.tracing.langsmith import get_tracing_client

        tracing_client = get_tracing_client()
    except Exception:  # noqa: BLE001
        tracing_client = None

    if tracing_client and tracing_client.enabled:
        metrics_in = dict((state.get("metrics") or {}))
        with tracing_client.trace(
            name="rag_generate",
            run_type="llm",
            inputs={
                "question": (state["question"])[:2000],
                "structured_output": bool(state.get("structured_output")),
                "structured_preset": state.get("structured_preset"),
            },
            metadata={
                "request_id": metrics_in.get("request_id"),
                "conversation_id": metrics_in.get("conversation_id"),
                "tenant_id": metrics_in.get("tenant_id") or metadata_text(state, "tenant_id"),
                "account_id": metrics_in.get("account_id"),
            },
            tags=["rag", "langgraph", "generation"],
        ) as span:
            result = _run_with_retry("generate", _generate_node, state)
            metrics_out = result.get("metrics") or {}
            span.outputs = {
                "answer_chars": len(result["answer"]),
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
                "answer_chars": len(result["answer"]),
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
    corrective_enabled = bool(settings.RAG_CORRECTIVE_ENABLED)
    max_attempts_raw = int(settings.RAG_CORRECTIVE_MAX_ATTEMPTS)
    max_attempts = max(1, min(max_attempts_raw, 3))
    min_faithfulness = float(settings.RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE)
    min_faithfulness = min(1.0, max(0.0, min_faithfulness))

    # Second-pass retrieval overrides (best-effort).
    second_profile = str(settings.RAG_CORRECTIVE_SECOND_PASS_PROFILE).strip().lower()
    if second_profile not in {"recall20", "recall50", "coverage80", "hierarchy_recall20", "hierarchy_recall20_expand"}:
        second_profile = "recall50"
    second_enable_mq = bool(settings.RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY)
    second_mq_count = int(settings.RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT)
    second_mq_count = max(0, min(second_mq_count, int(settings.MULTI_QUERY_COUNT_CAP)))

    base_state = dict(state)
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
        used = used or attempt_result["used_second_pass"]
        reason_code = attempt_result["reason_code"]
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
        if not attempt_result["retry"]:
            break

    # Attach a compact summary for debugging (PII-safe).
    if last_state.get("abstain_triggered"):
        last_state = generate_fn(last_state)
    metrics_final = dict(last_state.get("metrics") or {})
    metrics_final["corrective_enabled"] = corrective_enabled
    metrics_final["corrective_used"] = used
    metrics_final["corrective_max_attempts"] = max_attempts
    metrics_final["corrective_reason_codes"] = reason_codes[:8]
    metrics_final["corrective_attempts"] = attempt_summaries[:3]
    metrics_final["corrective_second_pass"] = {
        "retrieval_profile": second_profile,
        "enable_multi_query": second_enable_mq,
        "multi_query_count": second_mq_count,
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

    retrieved = dict(retrieve_fn(attempt_state))
    retrieval_metrics = dict(retrieved.get("metrics") or {})
    summary = {
        "attempt": int(attempt),
        "retrieval_profile": retrieved.get("retrieval_profile"),
        "top_k": retrieved.get("top_k"),
        "retrieval_mode": retrieval_metrics.get("retrieval_mode") or retrieved.get("retrieval_mode"),
        "abstain_triggered": bool(retrieved.get("abstain_triggered")),
    }
    if retrieved.get("abstain_triggered"):
        return {
            "state": retrieved,
            "summary": summary,
            "used_second_pass": used_second_pass,
            "reason_code": "abstain" if attempt < max_attempts else None,
            "retry": attempt < max_attempts,
        }

    generated = dict(generate_fn(retrieved))
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
    except (OverflowError, TypeError, ValueError):
        return False

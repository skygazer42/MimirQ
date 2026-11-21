"""Invoke retrieval queries and ordered decomposition steps."""

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.tokens import num_tokens_from_string
from app.rag.retrieval.evidence.citations import build_citations_from_docs
from app.rag.retrieval.ranking.fusion import annotate_documents_with_role
from app.rag.retrieval.results import _log_orchestrator_fallback
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.rag.tracing.retrieval_debug import _sanitize_retriever_debug
from app.storage.bm25.milvus import BM25IndexNotReadyError


@dataclass(frozen=True)
class RetrievalPerQueryItemInput:
    kind: str
    query: str
    elapsed_sec: float
    ok: bool
    retriever_debug: dict[str, Any] | None
    hop: int | None = None


@dataclass(frozen=True)
class QueryInvocationRecordInput:
    kind: str
    query: str
    docs: list[Document] | None
    error: str | None
    elapsed_sec: float
    retriever_debug: dict[str, Any] | None
    hop: int | None = None


@dataclass(frozen=True)
class QueryInvocationRecordOutput:
    per_query_item: dict[str, Any]
    error_entry: str | None
    kind: str
    docs: list[Document]


def build_retrieval_per_query_item(payload: RetrievalPerQueryItemInput) -> dict[str, Any]:
    kind = payload.kind.strip() or "main"
    out: dict[str, Any] = {
        "kind": kind,
        "query_chars": len(payload.query),
        "query_tokens": num_tokens_from_string(payload.query),
        "elapsed_sec": round(payload.elapsed_sec, 3),
        "ok": payload.ok,
        "retriever_debug": payload.retriever_debug,
    }
    if payload.hop is not None:
        out["hop"] = payload.hop
    return out


def format_retrieval_error(kind: str, error: str | None) -> str:
    normalized_kind = kind.strip() or "main"
    return f"{normalized_kind}:{(error if error is not None else '')[:160]}"


def build_query_invocation_record(payload: QueryInvocationRecordInput) -> QueryInvocationRecordOutput:
    kind = payload.kind.strip() or "main"
    return QueryInvocationRecordOutput(
        per_query_item=build_retrieval_per_query_item(
            RetrievalPerQueryItemInput(
                kind=kind,
                query=payload.query,
                elapsed_sec=payload.elapsed_sec,
                ok=payload.error is None,
                retriever_debug=payload.retriever_debug,
                hop=payload.hop,
            )
        ),
        error_entry=(format_retrieval_error(kind, payload.error) if payload.error is not None else None),
        kind=kind,
        docs=list(payload.docs or []),
    )


def _retriever_for_query_kind(ctx: RetrievalRuntimeState, kind: str) -> Any:
    if kind == "main":
        return ctx.retriever
    if kind == "hyde":
        return ctx.retriever.model_copy(
            update={"enable_reranker": False, "retrieval_mode": "vector", "enable_weight_rerank": False}
        )
    return ctx.retriever.model_copy(update={"enable_reranker": False})


def _hierarchy_invocation_debug(docs: list[Document], debug: dict[str, Any] | None) -> dict[str, Any]:
    family_keys: list[str] = []
    for doc in docs:
        metadata = doc.metadata or {}
        family_key = next(
            (
                str(metadata.get(key)).strip()
                for key in ("hierarchy_family_key", "parent_id", "parent_node_id")
                if metadata.get(key)
            ),
            "",
        )
        if family_key:
            family_keys.append(family_key)
    distinct_families = len(set(family_keys)) if family_keys else 0
    result = dict((debug if debug is not None else {}))
    result["hierarchy_family"] = {
        "docs": len(docs),
        "docs_with_key": len(family_keys),
        "distinct_families": distinct_families,
        "duplicate_docs": max(0, len(family_keys) - distinct_families),
    }
    return result


def _invoke_retrieval_query(
    ctx: RetrievalRuntimeState,
    kind: str,
    query: str,
    retriever_obj: Any,
) -> tuple[str, list[Document], str | None, float, dict[str, Any] | None]:
    started = time.time()
    try:
        docs = annotate_documents_with_role(retriever_obj.invoke(query) or [], kind)
        debug = getattr(retriever_obj, "_last_debug_metrics", None)
        debug = _sanitize_retriever_debug(debug if isinstance(debug, dict) else None)
        if bool(ctx.hierarchy_recall_enabled) and docs:
            debug = _hierarchy_invocation_debug(docs, debug)
        return kind, docs, None, time.time() - started, debug
    except BM25IndexNotReadyError:
        raise
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_invoke_with_timing", exc)
        return kind, [], str(exc)[:200], time.time() - started, None


def _record_retrieval_query(
    ctx: RetrievalRuntimeState,
    *,
    query: str,
    invocation: tuple[str, list[Document], str | None, float, dict[str, Any] | None],
) -> QueryInvocationRecordOutput:
    kind, docs, error, elapsed, debug = invocation
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind=kind,
            query=query,
            docs=docs,
            error=error,
            elapsed_sec=elapsed,
            retriever_debug=debug,
        )
    )
    ctx.retrieval_per_query.append(record.per_query_item)
    if record.error_entry:
        ctx.retrieval_errors.append(record.error_entry)
    ctx.docs_by_query_kinds.append(record.kind)
    ctx.docs_by_query.append(record.docs)
    return record


def _summarize_decomposition_step(
    docs: list[Document],
    *,
    elapsed_sec: float,
    retrieval_mode: str,
    query: str,
    summarize: Callable[[list[dict[str, Any]]], str],
) -> str:
    try:
        citations = build_citations_from_docs(
            docs,
            retrieval_elapsed_sec=elapsed_sec,
            retrieval_mode=retrieval_mode,
            query=query,
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        citations = []
    return summarize(citations)


def _run_decomposition_chain(ctx: RetrievalRuntimeState) -> None:
    if not ctx.decompose_chain_requested:
        return
    try:
        from app.rag.retrieval.planning.decomposition import build_chained_query, summarize_chain_step

        chain_started = time.time()
        prior_findings: list[str] = []
        retrieval_mode = ctx.retriever_update["retrieval_mode"]
        for sub_question in ctx.sub_questions:
            chained_query = build_chained_query(sub_question, prior_findings)
            if not chained_query:
                continue
            ctx.decompose_chain_queries.append(chained_query)
            retriever_obj = ctx.retriever.model_copy(update={"enable_reranker": False})
            invocation = _invoke_retrieval_query(ctx, "subq", chained_query, retriever_obj)
            record = _record_retrieval_query(ctx, query=chained_query, invocation=invocation)
            summary = _summarize_decomposition_step(
                record.docs,
                elapsed_sec=invocation[3],
                retrieval_mode=retrieval_mode,
                query=chained_query,
                summarize=summarize_chain_step,
            )
            prior_findings.append(sub_question if not summary else f"{sub_question}: {summary}")
        ctx.decompose_chain_steps = len(ctx.decompose_chain_queries)
        ctx.decompose_chain_used = ctx.decompose_chain_steps > 0
        ctx.decompose_chain_elapsed = time.time() - chain_started
        if ctx.decompose_chain_used:
            ctx.retrieval_plan = [item for item in ctx.retrieval_plan if item[0] != "subq"]
    except BM25IndexNotReadyError:
        raise
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.decompose_chain_used = False
        ctx.decompose_chain_steps = 0
        ctx.decompose_chain_elapsed = 0.0
        ctx.decompose_chain_queries = []


def _run_retrieval_plan(ctx: RetrievalRuntimeState) -> None:
    if ctx.retrieval_parallelism <= 1 or len(ctx.retrieval_plan) <= 1:
        for kind, query, retriever_obj in ctx.retrieval_plan:
            invocation = _invoke_retrieval_query(ctx, kind, query, retriever_obj)
            _record_retrieval_query(ctx, query=query, invocation=invocation)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=ctx.retrieval_parallelism) as pool:
        futures = [
            (query, pool.submit(_invoke_retrieval_query, ctx, kind, query, retriever_obj))
            for kind, query, retriever_obj in ctx.retrieval_plan
        ]
        for query, future in futures:
            _record_retrieval_query(ctx, query=query, invocation=future.result())


def _run_retrieval_retrieval_execution_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.docs_by_query = []
    ctx.docs_by_query_kinds = []
    ctx.retrieval_errors = []
    ctx.retrieval_per_query = []
    ctx.retrieval_parallelism = max(1, int(settings.RETRIEVAL_QUERY_PARALLELISM))
    ctx.retrieval_plan = [(kind, query, _retriever_for_query_kind(ctx, kind)) for kind, query in ctx.query_plan.queries]
    started = time.time()
    _run_decomposition_chain(ctx)
    _run_retrieval_plan(ctx)
    ctx.retrieval_elapsed = time.time() - started
    return None

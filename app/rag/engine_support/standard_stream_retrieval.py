"""Retrieval phases for standard RAG streaming."""

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)


async def build_retriever_and_base_queries(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    # Step 1: Hybrid retrieval (LangChain Retriever).
    runtime.data.retrieval_message = "正在从知识库中检索相关资料..."
    yield {"type": "event", "data": {"message": runtime.data.retrieval_message}}
    runtime.data.status_event = runtime.engine._build_stream_status_event(
        stage="retrieval",
        state="running",
        message=runtime.data.retrieval_message,
        attempt=1,
        max_attempts=runtime.data.corrective_max_attempts,
    )
    if runtime.data.status_event is not None:
        yield runtime.data.status_event
    runtime.data.retriever_update: dict[str, Any] = {
        "k": runtime.data.top_k,
        "score_threshold": runtime.data.score_threshold_used,
        "alpha": runtime.data.alpha_val,
        "fusion_strategy": str(runtime.data.fusion_strategy or "").strip().lower()
        or settings.RETRIEVAL_FUSION_STRATEGY,
        "fusion_budgets": runtime.data.fusion_budgets,
        "fusion_min_scores": runtime.data.fusion_min_scores,
        "fusion_weights": runtime.data.fusion_weights,
        "retrieval_overfetch_multiplier": runtime.data.retrieval_overfetch_multiplier,
        "retrieval_overfetch_max_k": runtime.data.retrieval_overfetch_max_k,
        "tenant_id": runtime.data.tenant_id,
        "account_id": runtime.data.account_id,
        "dataset_id": runtime.data.dataset_id,
        "dataset_ids": runtime.data.dataset_ids,
        "document_ids": runtime.data.document_ids,
        "metadata_filter": runtime.data.metadata_filter,
        "lexical_db_hybrid_fallback_only": runtime.data.lexical_db_hybrid_fallback_only,
        "lexical_db_hybrid_metadata_exact_fallback_enabled": (
            runtime.data.lexical_db_hybrid_metadata_exact_fallback_enabled
        ),
        "metadata_exact_db_fallback_enabled": runtime.data.metadata_exact_db_fallback_enabled,
        "retrieval_mode": runtime.data.mode_used,
        "retrieval_profile": runtime.data.profile_norm or None,
        "sparse_retrieval_enabled": runtime.data.sparse_retrieval_enabled,
        "sparse_retrieval_provider": runtime.data.sparse_retrieval_provider,
        "context_neighbor_window": runtime.data.profile_applied.get("context_neighbor_window"),
        "context_neighbor_max_added": runtime.data.profile_applied.get("context_neighbor_max_added"),
        "context_neighbor_score_driven": runtime.data.profile_applied.get("context_neighbor_score_driven"),
        "context_neighbor_high_threshold": runtime.data.profile_applied.get("context_neighbor_high_threshold"),
        "context_neighbor_mid_threshold": runtime.data.profile_applied.get("context_neighbor_mid_threshold"),
        "context_neighbor_high_span": runtime.data.profile_applied.get("context_neighbor_high_span"),
        "context_neighbor_mid_span": runtime.data.profile_applied.get("context_neighbor_mid_span"),
        "enable_weight_rerank": runtime.data.weight_rerank,
        "vector_weight": runtime.data.vec_w,
        "keyword_weight": runtime.data.kw_w,
        "mmr_lambda": runtime.data.mmr_lambda_val,
        "enable_reranker": runtime.data.rerank_on,
        "reranker_provider": runtime.data.rerank_provider,
        "reranker_top_n": runtime.data.rerank_top_n,
        "enable_hierarchy_recall": bool(runtime.data.enable_hierarchy_recall),
        "hierarchy_family_collapse": bool(runtime.data.hierarchy_family_collapse),
        "hierarchy_overfetch_factor": int(runtime.data.hierarchy_overfetch_factor or 1),
    }
    if runtime.module.is_recall_first_profile(runtime.data.profile_norm):
        # Recall-first profiles: do not drop candidates due to dedup/diversity heuristics.
        runtime.data.retriever_update.update(
            {
                "dedup_enabled": False,
                "max_chunks_per_doc": 0,
                "max_chunks_per_page": 0,
                "min_distinct_docs": 0,
            }
        )

    runtime.data.retriever = runtime.module.hybrid_retriever.model_copy(update=runtime.data.retriever_update)

    runtime.data.retrieval_queries_base: list[tuple[str, str]] = [("main", runtime.data.query_for_retrieval)]
    for runtime.data.q in runtime.data.alias_queries:
        runtime.data.retrieval_queries_base.append(("alias", runtime.data.q))
    for runtime.data.e in runtime.data.dict_expansions:
        runtime.data.q = runtime.data.e.get("expanded_text") if isinstance(runtime.data.e, dict) else None
        if runtime.data.q:
            runtime.data.retrieval_queries_base.append(("dict", str(runtime.data.q)))
    for runtime.data.q in runtime.data.kg_query_expansion_queries:
        runtime.data.retrieval_queries_base.append(("kgq", runtime.data.q))
    # Policy/manual "fast lane": when users mention clause numbers, add a clause-only
    # retrieval query to improve exact-match recall without invoking the LLM.
    for runtime.data.q in runtime.module.build_clause_fastlane_queries(runtime.data.query_for_retrieval):
        runtime.data.retrieval_queries_base.append(("clause", runtime.data.q))


async def extend_queries_and_prepare_plan(runtime: StandardStreamState) -> None:
    if bool(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED", False)):
        for runtime.data.q in runtime.module.build_lightweight_subquery_queries(
            runtime.data.query_for_retrieval,
            max_queries=int(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MAX_QUERIES", 3) or 3),
            min_query_chars=int(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MIN_QUERY_CHARS", 28) or 28),
        ):
            runtime.data.retrieval_queries_base.append(("lite_subq", runtime.data.q))
    if runtime.data.step_back_used and runtime.data.step_back_query:
        runtime.data.retrieval_queries_base.append(("step_back", runtime.data.step_back_query))
    for runtime.data.q in runtime.data.sub_questions:
        runtime.data.retrieval_queries_base.append(("subq", runtime.data.q))
    if runtime.data.hyde_used and runtime.data.hyde_text:
        runtime.data.retrieval_queries_base.append(("hyde", runtime.data.hyde_text))

    runtime.data.retrieval_queries: list[tuple[str, str]] = list(runtime.data.retrieval_queries_base)
    for runtime.data.q in runtime.data.multi_queries:
        runtime.data.retrieval_queries.append(("mq", runtime.data.q))
    runtime.data.retrieval_queries = runtime.engine._dedup_retrieval_queries(runtime.data.retrieval_queries)

    runtime.data.docs_by_query: list[list[Document]] = []
    runtime.data.docs_by_query_kinds: list[str] = []
    runtime.data.t_retrieval_start = time.time()
    runtime.data.retrieval_parallelism = max(1, int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1))
    runtime.data.retrieval_plan: list[tuple[str, str, Any]] = []


async def build_retrieval_plan(runtime: StandardStreamState) -> None:
    for runtime.data.kind, runtime.data.q in runtime.data.retrieval_queries:
        runtime.data.r = runtime.data.retriever
        if runtime.data.kind != "main":
            if runtime.data.kind == "hyde":
                runtime.data.r = runtime.data.retriever.model_copy(
                    update={
                        "enable_reranker": False,
                        "retrieval_mode": "vector",
                        "enable_weight_rerank": False,
                    }
                )
            else:
                runtime.data.r = runtime.data.retriever.model_copy(update={"enable_reranker": False})
        runtime.data.retrieval_plan.append((runtime.data.kind, runtime.data.q, runtime.data.r))

    runtime.data.retrieval_errors: list[str] = []
    runtime.data.retrieval_per_query: list[dict[str, Any]] = []

    async def _run_one(
        kind: str, q: str, r: Any
    ) -> tuple[str, list[Document], str | None, float, dict[str, Any] | None]:
        return await runtime.engine._run_stream_retrieval_query(
            kind=kind,
            query=q,
            retriever=r,
        )

    runtime.data.run_one = _run_one


async def execute_retrieval_plan(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    if runtime.data.retrieval_parallelism <= 1 or len(runtime.data.retrieval_plan) <= 1:
        for runtime.data.kind, runtime.data.q, runtime.data.r in runtime.data.retrieval_plan:
            (
                runtime.data.kind,
                runtime.data.docs_i,
                runtime.data.err,
                runtime.data.elapsed_i,
                runtime.data.dbg,
            ) = await runtime.data.run_one(runtime.data.kind, runtime.data.q, runtime.data.r)
            runtime.data.retrieval_per_query.append(
                {
                    "kind": runtime.data.kind,
                    "query_chars": len(runtime.data.q or ""),
                    "query_tokens": runtime.module.num_tokens_from_string(runtime.data.q or ""),
                    "elapsed_sec": round(runtime.data.elapsed_i, 3),
                    "ok": runtime.data.err is None,
                    "retriever_debug": runtime.data.dbg,
                }
            )
            if runtime.data.err:
                runtime.data.retrieval_errors.append(f"{runtime.data.kind}:{runtime.data.err[:160]}")
                if runtime.data.kind == "main":
                    yield {"type": "error", "data": {"message": f"retrieval failed: {runtime.data.err}"}}
            runtime.data.docs_by_query_kinds.append(runtime.data.kind)
            runtime.data.docs_by_query.append(
                runtime.engine._annotate_docs_with_role(runtime.data.docs_i or [], runtime.data.kind)
            )
    else:
        runtime.data.sem = asyncio.Semaphore(runtime.data.retrieval_parallelism)

        async def _guarded(
            kind: str, q: str, r: Any
        ) -> tuple[str, list[Document], str | None, float, dict[str, Any] | None]:
            async with runtime.data.sem:
                return await runtime.data.run_one(kind, q, r)

        runtime.data.results = await asyncio.gather(
            *[_guarded(kind, q, r) for kind, q, r in runtime.data.retrieval_plan]
        )
        for (runtime.data.kind, runtime.data.docs_i, runtime.data.err, runtime.data.elapsed_i, runtime.data.dbg), (
            runtime.data._,
            runtime.data.q,
            runtime.data._,
        ) in zip(runtime.data.results, runtime.data.retrieval_plan, strict=False):
            runtime.data.retrieval_per_query.append(
                {
                    "kind": runtime.data.kind,
                    "query_chars": len(runtime.data.q or ""),
                    "query_tokens": runtime.module.num_tokens_from_string(runtime.data.q or ""),
                    "elapsed_sec": round(runtime.data.elapsed_i, 3),
                    "ok": runtime.data.err is None,
                    "retriever_debug": runtime.data.dbg,
                }
            )
            if runtime.data.err:
                runtime.data.retrieval_errors.append(f"{runtime.data.kind}:{runtime.data.err[:160]}")
                if runtime.data.kind == "main":
                    yield {"type": "error", "data": {"message": f"retrieval failed: {runtime.data.err}"}}
            runtime.data.docs_by_query_kinds.append(runtime.data.kind)
            runtime.data.docs_by_query.append(
                runtime.engine._annotate_docs_with_role(runtime.data.docs_i or [], runtime.data.kind)
            )

    runtime.data.retrieval_elapsed = time.time() - runtime.data.t_retrieval_start
    runtime.data.mq_diversify_enabled = bool(getattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False)) and bool(
        runtime.data.mq_enabled
    )


async def initialize_fusion(runtime: StandardStreamState) -> None:
    try:
        runtime.data.mq_budget_raw = int(getattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0) or 0)
    except Exception:
        runtime.data.mq_budget_raw = 0
    runtime.data.mq_diversify_budget = max(0, min(int(runtime.data.mq_budget_raw or 0), int(runtime.data.top_k or 0)))
    runtime.data.mq_diversify_used = False
    runtime.data.mq_diversify_selected_mq = 0
    runtime.data.mq_diversify_selected_non_mq = 0
    runtime.data.mq_diversify_fill_from_fused = 0


def _partition_retrieval_docs(runtime: StandardStreamState) -> None:
    runtime.data.mq_lists = []
    runtime.data.non_mq_lists = []
    pairs = zip(runtime.data.docs_by_query_kinds, runtime.data.docs_by_query, strict=False)
    for kind, docs in pairs:
        if kind == "mq":
            runtime.data.mq_lists.append(docs or [])
        else:
            runtime.data.non_mq_lists.append(docs or [])


def _fuse_doc_lists(runtime: StandardStreamState, doc_lists: list[list[Document]]) -> list[Document]:
    if len(doc_lists) == 1:
        return doc_lists[0] or []
    return runtime.engine.fuse_docs_rrf(
        doc_lists,
        rrf_k=settings.RETRIEVAL_RRF_K,
        meta_prefix="query_expansion",
    )


def _select_non_mq_docs(runtime: StandardStreamState) -> None:
    for doc in runtime.data.docs_non_mq:
        key = runtime.engine._doc_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        if len(runtime.data.selected) >= runtime.data.want_non_mq:
            break
    runtime.data.mq_diversify_selected_non_mq = len(runtime.data.selected)


def _select_mq_docs(runtime: StandardStreamState) -> None:
    runtime.data.mq_added = 0
    for doc in runtime.data.docs_mq:
        if runtime.data.mq_added >= runtime.data.want_mq:
            break
        key = runtime.engine._doc_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        runtime.data.mq_added += 1
    runtime.data.mq_diversify_selected_mq = runtime.data.mq_added


def _fill_fused_docs(runtime: StandardStreamState) -> None:
    for doc in runtime.data.docs_fused_all:
        if len(runtime.data.selected) >= int(runtime.data.top_k or 0):
            break
        key = runtime.engine._doc_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        runtime.data.mq_diversify_fill_from_fused += 1


async def fuse_retrieval_results(runtime: StandardStreamState) -> None:
    if len(runtime.data.docs_by_query) <= 1:
        runtime.data.docs = runtime.data.docs_by_query[0] if runtime.data.docs_by_query else []
        return
    runtime.data.docs_fused_all = _fuse_doc_lists(runtime, runtime.data.docs_by_query)
    if not (runtime.data.mq_diversify_enabled and runtime.data.mq_diversify_budget > 0):
        runtime.data.docs = runtime.data.docs_fused_all
        return
    _partition_retrieval_docs(runtime)
    if not (runtime.data.mq_lists and runtime.data.non_mq_lists):
        runtime.data.docs = runtime.data.docs_fused_all
        return
    runtime.data.mq_diversify_used = True
    runtime.data.docs_non_mq = _fuse_doc_lists(runtime, runtime.data.non_mq_lists)
    runtime.data.docs_mq = _fuse_doc_lists(runtime, runtime.data.mq_lists)
    runtime.data.want_non_mq = max(0, int(runtime.data.top_k or 0) - runtime.data.mq_diversify_budget)
    runtime.data.want_mq = runtime.data.mq_diversify_budget
    runtime.data.selected = []
    runtime.data.selected_keys = set()
    _select_non_mq_docs(runtime)
    _select_mq_docs(runtime)
    _fill_fused_docs(runtime)
    runtime.data.docs = runtime.data.selected


async def initialize_kg_enrichment(runtime: StandardStreamState) -> None:
    runtime.data.docs = runtime.data.docs[: max(0, int(runtime.data.top_k or 0))] if runtime.data.docs else []

    # Optional: KG-assisted retrieval (inject KG-linked chunks as extra candidates).
    #
    # This turns KG entity linking (query->events->chunk_id) into structured chunk candidates,
    # improving precision without replacing the main retriever.
    runtime.data.kg_chunk_injection_enabled = (
        bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False))
        if runtime.data.enable_kg_chunk_injection is None
        else bool(runtime.data.enable_kg_chunk_injection)
    )
    try:
        runtime.data.kg_chunk_injection_max_chunks_i = (
            int(getattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5) or 5)
            if runtime.data.kg_chunk_injection_max_chunks is None
            else int(runtime.data.kg_chunk_injection_max_chunks or 0)
        )
    except Exception:
        runtime.data.kg_chunk_injection_max_chunks_i = int(
            getattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5) or 5
        )
    runtime.data.kg_chunk_injection_max_chunks_i = max(
        0, min(int(runtime.data.kg_chunk_injection_max_chunks_i or 0), 50)
    )
    runtime.data.kg_chunk_boost_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    runtime.data.kg_chunks_injected = 0


def _kg_chunk_injection_allowed(runtime: StandardStreamState) -> bool:
    has_scope = bool(
        runtime.data.kg_document_ids or runtime.data.kg_dataset_id is not None or runtime.data.kg_dataset_ids
    )
    return bool(
        runtime.data.kg_chunk_injection_enabled
        and getattr(settings, "KG_ENABLED", False)
        and getattr(settings, "KG_CHAT_ENABLED", False)
        and runtime.data.db is not None
        and runtime.data.tenant_id is not None
        and has_scope
    )


def _collect_kg_chunk_candidates(runtime: StandardStreamState) -> None:
    runtime.data.score_by_chunk = {}
    runtime.data.chunk_ids = []
    runtime.data.seen_chunk_ids = set()
    events = runtime.data.kg_events if isinstance(runtime.data.kg_events, list) else []
    for event in events:
        if not isinstance(event, dict) or event.get("chunk_id") is None:
            continue
        try:
            chunk_id = UUID(str(event.get("chunk_id")))
        except Exception:
            runtime.module.logger.debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if chunk_id in runtime.data.seen_chunk_ids:
            continue
        runtime.data.seen_chunk_ids.add(chunk_id)
        runtime.data.chunk_ids.append(chunk_id)
        try:
            runtime.data.score_by_chunk[str(chunk_id)] = float(event.get("score", 0.0) or 0.0)
        except Exception:
            runtime.data.score_by_chunk[str(chunk_id)] = 0.0
        if len(runtime.data.chunk_ids) >= runtime.data.max_chunks:
            break


def _kg_injection_fetch_kwargs(runtime: StandardStreamState) -> dict[str, Any]:
    fetch_kwargs = {
        "db": runtime.data.db,
        "tenant_id": runtime.data.tenant_id,
        "account_id": runtime.data.account_id,
        "dataset_id": runtime.data.kg_dataset_id,
        "document_ids": runtime.data.kg_document_ids,
        "chunk_ids": runtime.data.chunk_ids,
    }
    if runtime.data.kg_dataset_ids:
        fetch_kwargs["dataset_ids"] = runtime.data.kg_dataset_ids
    return fetch_kwargs


def _kg_document_from_chunk(runtime: StandardStreamState, chunk_id: UUID, chunk: Any) -> Document:
    metadata = dict(getattr(chunk, "doc_metadata", None) or {})
    metadata["retrieval_role"] = "kg"
    metadata.setdefault("document_id", str(getattr(chunk, "document_id", "") or ""))
    metadata.setdefault("chunk_id", str(getattr(chunk, "id", "") or ""))
    metadata.setdefault("chunk_index", getattr(chunk, "chunk_index", None))
    page_number = getattr(chunk, "page_number", None)
    if page_number is not None:
        metadata.setdefault("page", int(page_number))
        metadata.setdefault("page_number", int(page_number))
    start_char = getattr(chunk, "start_char", None)
    end_char = getattr(chunk, "end_char", None)
    if start_char is not None:
        metadata.setdefault("start_char", int(start_char))
    if end_char is not None:
        metadata.setdefault("end_char", int(end_char))
    if str(chunk_id) in runtime.data.score_by_chunk:
        score = float(runtime.data.score_by_chunk.get(str(chunk_id), 0.0) or 0.0)
        metadata.setdefault("retrieval_score", score)
        metadata.setdefault("score", score)
    return runtime.module.Document(
        page_content=str(getattr(chunk, "content", None) or ""),
        metadata=metadata,
        id=str(chunk_id),
    )


def _build_kg_injection_docs(runtime: StandardStreamState) -> list[Document]:
    documents = []
    for chunk_id in runtime.data.chunk_ids:
        chunk = runtime.data.chunk_by_id.get(chunk_id)
        if chunk is not None:
            documents.append(_kg_document_from_chunk(runtime, chunk_id, chunk))
    return documents


async def inject_kg_chunks(runtime: StandardStreamState) -> None:
    try:
        (
            runtime.data.kg_document_ids,
            runtime.data.kg_dataset_id,
            runtime.data.kg_dataset_ids,
        ) = runtime.module._resolve_kg_scope(
            {
                "document_ids": runtime.data.document_ids,
                "dataset_id": runtime.data.dataset_id,
                "dataset_ids": runtime.data.dataset_ids,
            }
        )
        if not _kg_chunk_injection_allowed(runtime):
            return
        runtime.data.kg_kwargs = {
            "query": runtime.data.query_for_retrieval,
            "tenant_id": runtime.data.tenant_id,
            "document_ids": runtime.data.kg_document_ids or None,
            "dataset_id": runtime.data.kg_dataset_id,
            "account_id": runtime.data.account_id if not runtime.data.kg_document_ids else None,
        }
        if runtime.data.kg_dataset_ids:
            runtime.data.kg_kwargs["dataset_ids"] = runtime.data.kg_dataset_ids
        runtime.data.kg_result_cached = runtime.data.kg_result_cached or await runtime.module.kg_search(
            **runtime.data.kg_kwargs
        )
        runtime.data.kg_events = (runtime.data.kg_result_cached or {}).get("events") or []
        runtime.data.max_chunks = int(runtime.data.kg_chunk_injection_max_chunks_i or 0) or 5
        _collect_kg_chunk_candidates(runtime)
        if not runtime.data.chunk_ids:
            return
        rows = runtime.module._fetch_document_chunks_for_kg_injection(**_kg_injection_fetch_kwargs(runtime))
        runtime.data.chunk_by_id = {
            chunk.id: chunk
            for chunk in (rows or [])
            if getattr(chunk, "id", None) is not None and getattr(chunk, "content", None) is not None
        }
        runtime.data.kg_docs = _build_kg_injection_docs(runtime)
        if runtime.data.kg_docs:
            runtime.data.docs = runtime.module._merge_kg_docs_preserving_main(
                runtime.data.docs,
                runtime.data.kg_docs,
            )
            runtime.data.kg_chunks_injected = len(runtime.data.kg_docs)
    except Exception:
        runtime.data.kg_result_cached = None
        runtime.data.kg_chunks_injected = 0


async def boost_kg_and_retrieve_images(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    try:
        runtime.data.kg_boost_enabled = (
            bool(getattr(settings, "RAG_KG_CHUNK_BOOST_ENABLED", False))
            if runtime.data.enable_kg_chunk_boost is None
            else bool(runtime.data.enable_kg_chunk_boost)
        )
        runtime.data.kg_boost_weight = (
            float(getattr(settings, "RAG_KG_CHUNK_BOOST_WEIGHT", 0.25) or 0.25)
            if runtime.data.kg_chunk_boost_weight is None
            else float(runtime.data.kg_chunk_boost_weight or 0.0)
        )
        runtime.data.kg_boost_max_promoted = (
            int(getattr(settings, "RAG_KG_CHUNK_BOOST_MAX_PROMOTED", 3) or 3)
            if runtime.data.kg_chunk_boost_max_promoted is None
            else int(runtime.data.kg_chunk_boost_max_promoted or 0)
        )
        runtime.data.docs, runtime.data.kg_chunk_boost_meta = runtime.module._apply_kg_chunk_boost(
            [d for d in (runtime.data.docs or []) if isinstance(d, runtime.module.Document)],
            enabled=bool(runtime.data.kg_boost_enabled),
            weight=max(0.0, min(float(runtime.data.kg_boost_weight), 1.0)),
            max_promoted=max(0, min(int(runtime.data.kg_boost_max_promoted), 20)),
        )
    except Exception:
        runtime.data.kg_chunk_boost_meta = {"enabled": False, "reason": "exception"}

    # Optional: Image bridge - inject bounded image/figure chunks (CLIP) as extra context.
    runtime.data.image_docs: list[Document] = []
    runtime.data.image_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
    if str(runtime.data.multimodal_modality or "text").strip().lower() == "image":
        try:
            from app.services.chat_image_service import build_chat_image_context_docs

            if runtime.data.db is None or runtime.data.tenant_id is None or runtime.data.dataset_id is None:
                runtime.data.image_meta = {"enabled": False, "used": False, "reason": "missing_scope"}
            else:
                # Best-effort progress signal (only when the feature is enabled).
                if bool(getattr(settings, "IMAGE_EMBEDDING_ENABLED", False)):
                    yield {"type": "event", "data": {"message": "检测到图片/图表问题，正在尝试图片检索（CLIP）..."}}
                runtime.data.image_docs, runtime.data.image_meta = build_chat_image_context_docs(
                    runtime.data.db,
                    tenant_id=runtime.data.tenant_id,
                    account_id=runtime.data.account_id,
                    dataset_id=runtime.data.dataset_id,
                    question=runtime.data.query_for_retrieval,
                    top_k=6,
                )
        except Exception as exc:  # noqa: BLE001
            runtime.data.image_docs = []
            runtime.data.image_meta = {"enabled": False, "used": False, "reason": f"image_exception:{str(exc)[:120]}"}
        finally:
            runtime.module._release_request_session(runtime.data.db)

    if runtime.data.image_docs:
        runtime.data.docs = (runtime.data.image_docs or []) + (runtime.data.docs or [])

    # Optional: Vision-native RAG (VLM-as-Reader) - read retrieved images and inject extracted text.
    runtime.data.vision_reader_docs: list[Document] = []
    runtime.data.vision_reader_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}


async def read_images_and_initialize_tag(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    if runtime.data.image_docs:
        try:
            if bool(getattr(settings, "VISION_RAG_READER_ENABLED", False)):
                # Only show progress when the feature is actually enabled.
                if bool(getattr(settings, "VISION_LLM_ENABLED", False)):
                    yield {"type": "event", "data": {"message": "正在使用视觉模型读取图片证据（VLM-as-Reader）..."}}
                # Reuse the same privacy knob as the main generation: if PII redaction is enabled,
                # avoid sending raw identifiers to external vision providers.
                runtime.data.pii_on_for_vision = bool(runtime.module.pii_redaction_enabled())
                runtime.data.q_for_vision = (
                    runtime.module.redact_text(runtime.data.question or "")
                    if runtime.data.pii_on_for_vision
                    else (runtime.data.question or "")
                )
                (
                    runtime.data.vision_reader_docs,
                    runtime.data.vision_reader_meta,
                ) = await runtime.module.build_vision_reader_context_docs(
                    image_docs=runtime.data.image_docs,
                    question=runtime.data.q_for_vision,
                    tenant_id=runtime.data.tenant_id,
                    http_client=runtime.engine.http_async_client,
                )
        except Exception as exc:  # noqa: BLE001
            runtime.data.vision_reader_docs = []
            runtime.data.vision_reader_meta = {
                "enabled": bool(getattr(settings, "VISION_RAG_READER_ENABLED", False)),
                "used": False,
                "reason": f"vision_reader_exception:{str(exc)[:160]}",
            }

    if runtime.data.vision_reader_docs:
        runtime.data.docs = (runtime.data.vision_reader_docs or []) + (runtime.data.docs or [])

    # Optional: Vision-native RAG (Vision generation) - generate the final answer with a VLM when
    # image evidence is present. Default off.
    runtime.data.vision_generation_meta: dict[str, Any] = {
        "enabled": bool(getattr(settings, "VISION_RAG_GENERATION_ENABLED", False)),
        "used": False,
        "reason": "not_run",
    }

    # Optional: TAG bridge - inject bounded table query results as extra context.
    runtime.data.tag_docs: list[Document] = []
    runtime.data.tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}


async def retrieve_tag_context(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    try:
        from app.services.chat_tag_service import build_chat_tag_context_docs

        if (
            str(runtime.data.multimodal_modality or "text").strip().lower() == "table"
            and runtime.data.db is not None
            and runtime.data.tenant_id is not None
            and runtime.data.document_ids
        ):
            # Only show TAG progress when the feature is actually enabled.
            if (
                bool(getattr(settings, "CHAT_TAG_ENABLED", False))
                and bool(getattr(settings, "TABLE_NL2SQL_ENABLED", False))
                and bool(getattr(settings, "TABLE_LLM_ALLOW_RESULT_EGRESS", False))
                and bool(str(getattr(settings, "LLM_API_KEY", "") or "").strip())
            ):
                yield {"type": "event", "data": {"message": "检测到表格资产，正在尝试表格查询（TAG）..."}}
            runtime.data.tag_docs, runtime.data.tag_meta = build_chat_tag_context_docs(
                runtime.data.db,
                tenant_id=runtime.data.tenant_id,
                document_ids=list(runtime.data.document_ids or []),
                question=runtime.data.question,
                must_recall_expected_source_keys=runtime.data.must_recall_expected_source_keys,
            )
        elif str(runtime.data.multimodal_modality or "text").strip().lower() != "table":
            runtime.data.tag_meta = {
                "enabled": False,
                "used": False,
                "reason": f"skipped_modality:{runtime.data.multimodal_modality}",
            }
    except Exception as exc:  # noqa: BLE001
        runtime.data.tag_docs = []
        runtime.data.tag_meta = {"enabled": False, "used": False, "reason": f"tag_exception:{str(exc)[:120]}"}

    # KG/image/TAG enrichment can reopen the request transaction. No later
    # engine stage needs that transaction, so return its connection before
    # corrective retrieval or answer-generation awaits.
    runtime.module._release_request_session(runtime.data.db)

    if runtime.data.tag_docs:
        runtime.data.docs = (runtime.data.tag_docs or []) + (runtime.data.docs or [])


RETRIEVAL_OPERATIONS = (
    StreamOperation(build_retriever_and_base_queries, streams=True),
    StreamOperation(extend_queries_and_prepare_plan, streams=False),
    StreamOperation(build_retrieval_plan, streams=False),
    StreamOperation(execute_retrieval_plan, streams=True),
    StreamOperation(initialize_fusion, streams=False),
    StreamOperation(fuse_retrieval_results, streams=False),
    StreamOperation(initialize_kg_enrichment, streams=False),
    StreamOperation(inject_kg_chunks, streams=False),
    StreamOperation(boost_kg_and_retrieve_images, streams=True),
    StreamOperation(read_images_and_initialize_tag, streams=True),
    StreamOperation(retrieve_tag_context, streams=True),
)

__all__ = ["RETRIEVAL_OPERATIONS"]

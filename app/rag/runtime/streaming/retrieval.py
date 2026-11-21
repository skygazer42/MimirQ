"""Retrieval phases for standard RAG streaming."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any
from uuid import UUID

import anyio
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.runtime.async_bridge import run_blocking_in_thread
from app.infrastructure.security.pii import pii_redaction_enabled, redact_text
from app.infrastructure.tokens import num_tokens_from_string
from app.rag.kg.pipeline import kg_search
from app.rag.llm.vision_reader import build_vision_reader_context_docs
from app.rag.retrieval.ranking.fusion import annotate_documents_with_role, fuse_doc_lists
from app.rag.retrieval.ranking.knowledge_graph import (
    _apply_kg_chunk_boost,
    _fetch_document_chunks_for_kg_injection,
    _merge_kg_docs_preserving_main,
    _resolve_kg_scope,
)
from app.rag.retrieval.recall.retriever import hybrid_retriever
from app.rag.retrieval.results import document_key
from app.rag.runtime.contracts import _release_request_session
from app.rag.runtime.streaming.state import StandardStreamState, StreamOperation

logger = logging.getLogger("rag.engine")
_ASYNC_CLEANUP_TIMEOUT_SEC = 5.0
_RetrievalResult = tuple[str, list[Document], str | None, float, dict[str, Any] | None]


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
    plan = runtime.data.query_plan
    runtime.data.retriever_update = dict(plan.retriever_options)
    runtime.data.retriever = hybrid_retriever.model_copy(update=runtime.data.retriever_update)
    runtime.data.retrieval_queries_base = [query for query in plan.queries if query[0] != "mq"]
    runtime.data.retrieval_queries = list(plan.queries)


async def extend_queries_and_prepare_plan(runtime: StandardStreamState) -> None:
    runtime.data.docs_by_query: list[list[Document]] = []
    runtime.data.docs_by_query_kinds: list[str] = []
    runtime.data.t_retrieval_start = time.time()
    runtime.data.retrieval_parallelism = max(1, int(settings.RETRIEVAL_QUERY_PARALLELISM))
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

    async def _run_one(kind: str, q: str, r: Any) -> _RetrievalResult:
        return await runtime.engine._run_stream_retrieval_query(
            kind=kind,
            query=q,
            retriever=r,
        )

    runtime.data.run_one = _run_one


async def _retrieval_plan_results(runtime: StandardStreamState) -> AsyncGenerator[tuple[str, _RetrievalResult], None]:
    if runtime.data.retrieval_parallelism <= 1 or len(runtime.data.retrieval_plan) <= 1:
        for kind, query, retriever in runtime.data.retrieval_plan:
            yield query, await runtime.data.run_one(kind, query, retriever)
        return

    semaphore = asyncio.Semaphore(runtime.data.retrieval_parallelism)

    async def _guarded(kind: str, query: str, retriever: Any) -> _RetrievalResult:
        async with semaphore:
            return await runtime.data.run_one(kind, query, retriever)

    tasks = [
        asyncio.create_task(_guarded(kind, query, retriever)) for kind, query, retriever in runtime.data.retrieval_plan
    ]
    pending = asyncio.gather(*tasks)
    try:
        results = await asyncio.shield(pending)
    except BaseException as error:
        try:
            with anyio.fail_after(_ASYNC_CLEANUP_TIMEOUT_SEC, shield=True):
                for task in tasks:
                    if not task.done() and not task.cancelling():
                        task.cancel()
                await asyncio.gather(pending, *tasks, return_exceptions=True)
        except BaseException as drain_error:
            error.add_note(f"Parallel retrieval cleanup failed: {type(drain_error).__name__}")
            logger.warning("Parallel retrieval cleanup failed while propagating an error", exc_info=True)
        raise
    for (_, query, _), result in zip(runtime.data.retrieval_plan, results, strict=False):
        yield query, result


async def execute_retrieval_plan(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    async with aclosing(_retrieval_plan_results(runtime)) as results:
        async for query, (kind, docs, error, elapsed, debug) in results:
            runtime.data.retrieval_per_query.append(
                {
                    "kind": kind,
                    "query_chars": len(query),
                    "query_tokens": num_tokens_from_string(query),
                    "elapsed_sec": round(elapsed, 3),
                    "ok": error is None,
                    "retriever_debug": debug,
                }
            )
            if error:
                runtime.data.retrieval_errors.append(f"{kind}:{error[:160]}")
                if kind == "main":
                    yield {"type": "error", "data": {"message": f"retrieval failed: {error}"}}
            runtime.data.docs_by_query_kinds.append(kind)
            runtime.data.docs_by_query.append(annotate_documents_with_role(docs or [], kind))

    runtime.data.retrieval_elapsed = time.time() - runtime.data.t_retrieval_start
    runtime.data.mq_diversify_enabled = bool(settings.MULTI_QUERY_DIVERSIFY_ENABLED) and bool(runtime.data.mq_enabled)


async def initialize_fusion(runtime: StandardStreamState) -> None:
    runtime.data.mq_budget_raw = settings.MULTI_QUERY_DIVERSIFY_BUDGET
    runtime.data.mq_diversify_budget = max(0, min(int(runtime.data.mq_budget_raw or 0), int(runtime.data.top_k)))
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


def _select_non_mq_docs(runtime: StandardStreamState) -> None:
    for doc in runtime.data.docs_non_mq:
        if len(runtime.data.selected) >= runtime.data.want_non_mq:
            break
        key = document_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
    runtime.data.mq_diversify_selected_non_mq = len(runtime.data.selected)


def _select_mq_docs(runtime: StandardStreamState) -> None:
    runtime.data.mq_added = 0
    for doc in runtime.data.docs_mq:
        if runtime.data.mq_added >= runtime.data.want_mq:
            break
        key = document_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        runtime.data.mq_added += 1
    runtime.data.mq_diversify_selected_mq = runtime.data.mq_added


def _fill_fused_docs(runtime: StandardStreamState) -> None:
    for doc in runtime.data.docs_fused_all:
        if len(runtime.data.selected) >= int(runtime.data.top_k):
            break
        key = document_key(doc)
        if key in runtime.data.selected_keys:
            continue
        runtime.data.selected_keys.add(key)
        runtime.data.selected.append(doc)
        runtime.data.mq_diversify_fill_from_fused += 1


async def fuse_retrieval_results(runtime: StandardStreamState) -> None:
    if len(runtime.data.docs_by_query) <= 1:
        runtime.data.docs = runtime.data.docs_by_query[0] if runtime.data.docs_by_query else []
        return
    runtime.data.docs_fused_all = fuse_doc_lists(
        runtime.data.docs_by_query,
        rrf_k=settings.RETRIEVAL_RRF_K,
    )
    if not (runtime.data.mq_diversify_enabled and runtime.data.mq_diversify_budget > 0):
        runtime.data.docs = runtime.data.docs_fused_all
        return
    _partition_retrieval_docs(runtime)
    if not (runtime.data.mq_lists and runtime.data.non_mq_lists):
        runtime.data.docs = runtime.data.docs_fused_all
        return
    runtime.data.mq_diversify_used = True
    runtime.data.docs_non_mq = fuse_doc_lists(
        runtime.data.non_mq_lists,
        rrf_k=settings.RETRIEVAL_RRF_K,
    )
    runtime.data.docs_mq = fuse_doc_lists(
        runtime.data.mq_lists,
        rrf_k=settings.RETRIEVAL_RRF_K,
    )
    runtime.data.want_non_mq = max(0, int(runtime.data.top_k) - runtime.data.mq_diversify_budget)
    runtime.data.want_mq = runtime.data.mq_diversify_budget
    runtime.data.selected = []
    runtime.data.selected_keys = set()
    _select_non_mq_docs(runtime)
    _select_mq_docs(runtime)
    _fill_fused_docs(runtime)
    runtime.data.docs = runtime.data.selected


async def initialize_kg_enrichment(runtime: StandardStreamState) -> None:
    runtime.data.docs = runtime.data.docs[: max(0, int(runtime.data.top_k))] if runtime.data.docs else []

    # Optional: KG-assisted retrieval (inject KG-linked chunks as extra candidates).
    #
    # This turns KG entity linking (query->events->chunk_id) into structured chunk candidates,
    # improving precision without replacing the main retriever.
    runtime.data.kg_chunk_injection_enabled = (
        bool(settings.RAG_KG_CHUNK_INJECTION_ENABLED)
        if runtime.data.enable_kg_chunk_injection is None
        else bool(runtime.data.enable_kg_chunk_injection)
    )
    runtime.data.kg_chunk_injection_max_chunks_i = (
        settings.RAG_KG_CHUNK_INJECTION_MAX_CHUNKS
        if runtime.data.kg_chunk_injection_max_chunks is None
        else runtime.data.kg_chunk_injection_max_chunks
    )
    runtime.data.kg_chunk_injection_max_chunks_i = max(0, min(int(runtime.data.kg_chunk_injection_max_chunks_i), 50))
    runtime.data.kg_chunk_boost_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    runtime.data.kg_chunks_injected = 0
    runtime.data.kg_chunk_injection_error = None


def _kg_chunk_injection_allowed(runtime: StandardStreamState) -> bool:
    has_scope = bool(
        runtime.data.kg_document_ids or runtime.data.kg_dataset_id is not None or runtime.data.kg_dataset_ids
    )
    return bool(
        runtime.data.kg_chunk_injection_enabled
        and runtime.data.kg_chunk_injection_max_chunks_i > 0
        and settings.KG_ENABLED
        and settings.KG_CHAT_ENABLED
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
            logger.debug("Skipping item after non-critical exception", exc_info=True)
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
    metadata = dict(chunk.doc_metadata or {})
    metadata["retrieval_role"] = "kg"
    metadata.setdefault("document_id", str(chunk.document_id))
    metadata.setdefault("chunk_id", str(chunk.id))
    metadata.setdefault("chunk_index", chunk.chunk_index)
    page_number = chunk.page_number
    if page_number is not None:
        metadata.setdefault("page", int(page_number))
        metadata.setdefault("page_number", int(page_number))
    start_char = chunk.start_char
    end_char = chunk.end_char
    if start_char is not None:
        metadata.setdefault("start_char", int(start_char))
    if end_char is not None:
        metadata.setdefault("end_char", int(end_char))
    if str(chunk_id) in runtime.data.score_by_chunk:
        score = float(runtime.data.score_by_chunk.get(str(chunk_id), 0.0) or 0.0)
        metadata.setdefault("retrieval_score", score)
        metadata.setdefault("score", score)
    return Document(
        page_content=chunk.content,
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
    (
        runtime.data.kg_document_ids,
        runtime.data.kg_dataset_id,
        runtime.data.kg_dataset_ids,
    ) = _resolve_kg_scope(
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
        "document_ids": runtime.data.kg_document_ids,
        "dataset_id": runtime.data.kg_dataset_id,
        "account_id": runtime.data.account_id,
    }
    if runtime.data.kg_dataset_ids:
        runtime.data.kg_kwargs["dataset_ids"] = runtime.data.kg_dataset_ids
    try:
        if runtime.data.kg_result_cached is None:
            runtime.data.kg_result_cached = await kg_search(**runtime.data.kg_kwargs)
        runtime.data.kg_events = runtime.data.kg_result_cached.get("events") or []
        runtime.data.max_chunks = runtime.data.kg_chunk_injection_max_chunks_i
        _collect_kg_chunk_candidates(runtime)
        if not runtime.data.chunk_ids:
            return
        rows = await run_blocking_in_thread(
            _fetch_document_chunks_for_kg_injection, **_kg_injection_fetch_kwargs(runtime)
        )
        runtime.data.chunk_by_id = {chunk.id: chunk for chunk in rows}
        runtime.data.kg_docs = _build_kg_injection_docs(runtime)
        if runtime.data.kg_docs:
            runtime.data.docs = _merge_kg_docs_preserving_main(runtime.data.docs, runtime.data.kg_docs)
            runtime.data.kg_chunks_injected = len(runtime.data.kg_docs)
    except Exception as exc:
        logger.debug("Optional KG chunk injection failed: %s", exc, exc_info=True)
        runtime.data.kg_chunk_injection_error = str(exc)[:200]


async def boost_kg_and_select_images(runtime: StandardStreamState) -> None:

    try:
        runtime.data.kg_boost_enabled = (
            bool(settings.RAG_KG_CHUNK_BOOST_ENABLED)
            if runtime.data.enable_kg_chunk_boost is None
            else bool(runtime.data.enable_kg_chunk_boost)
        )
        runtime.data.kg_boost_weight = (
            float(settings.RAG_KG_CHUNK_BOOST_WEIGHT)
            if runtime.data.kg_chunk_boost_weight is None
            else float(runtime.data.kg_chunk_boost_weight or 0.0)
        )
        runtime.data.kg_boost_max_promoted = (
            int(settings.RAG_KG_CHUNK_BOOST_MAX_PROMOTED)
            if runtime.data.kg_chunk_boost_max_promoted is None
            else int(runtime.data.kg_chunk_boost_max_promoted)
        )
        runtime.data.docs, runtime.data.kg_chunk_boost_meta = _apply_kg_chunk_boost(
            [d for d in (runtime.data.docs) if isinstance(d, Document)],
            enabled=bool(runtime.data.kg_boost_enabled),
            weight=max(0.0, min(float(runtime.data.kg_boost_weight), 1.0)),
            max_promoted=max(0, min(int(runtime.data.kg_boost_max_promoted), 20)),
        )
    except Exception:
        runtime.data.kg_chunk_boost_meta = {"enabled": False, "reason": "exception"}

    from app.rag.llm.vision_reader import select_image_evidence
    from app.services.documents.asset_access import filter_authorized_image_evidence

    runtime.data.image_docs = []
    db, tenant_id, account_id = runtime.data.db, runtime.data.tenant_id, runtime.data.account_id
    if (
        str(runtime.data.multimodal_modality or "text").strip().lower() == "image"
        and db is not None
        and tenant_id is not None
        and account_id is not None
    ):
        try:
            runtime.data.image_docs = await run_blocking_in_thread(
                filter_authorized_image_evidence,
                db=db,
                tenant_id=tenant_id,
                account_id=account_id,
                candidates=select_image_evidence(runtime.data.docs),
                max_images=max(settings.VISION_RAG_READER_MAX_IMAGES, settings.VISION_RAG_GENERATION_MAX_IMAGES),
            )
        finally:
            await run_blocking_in_thread(_release_request_session, db)
    runtime.data.image_meta = {
        "enabled": False,
        "used": bool(runtime.data.image_docs),
        "reason": "retrieved_document_images",
    }

    # Optional: Vision-native RAG (VLM-as-Reader) - read retrieved images and inject extracted text.
    runtime.data.vision_reader_docs: list[Document] = []
    runtime.data.vision_reader_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}


async def read_images_and_initialize_tag(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    if runtime.data.image_docs:
        try:
            if bool(settings.VISION_RAG_READER_ENABLED):
                # Only show progress when the feature is actually enabled.
                if bool(settings.VISION_LLM_ENABLED):
                    yield {"type": "event", "data": {"message": "正在使用视觉模型读取图片证据（VLM-as-Reader）..."}}
                # Reuse the same privacy knob as the main generation: if PII redaction is enabled,
                # avoid sending raw identifiers to external vision providers.
                runtime.data.pii_on_for_vision = bool(pii_redaction_enabled())
                runtime.data.q_for_vision = (
                    redact_text(runtime.data.question) if runtime.data.pii_on_for_vision else (runtime.data.question)
                )
                (
                    runtime.data.vision_reader_docs,
                    runtime.data.vision_reader_meta,
                ) = await build_vision_reader_context_docs(
                    image_docs=runtime.data.image_docs,
                    question=runtime.data.q_for_vision,
                    tenant_id=runtime.data.tenant_id,
                    http_client=runtime.engine.http_async_client,
                )
        except Exception as exc:  # noqa: BLE001
            runtime.data.vision_reader_docs = []
            runtime.data.vision_reader_meta = {
                "enabled": bool(settings.VISION_RAG_READER_ENABLED),
                "used": False,
                "reason": f"vision_reader_exception:{str(exc)[:160]}",
            }

    if runtime.data.vision_reader_docs:
        runtime.data.docs = (runtime.data.vision_reader_docs) + (runtime.data.docs)

    # Optional: Vision-native RAG (Vision generation) - generate the final answer with a VLM when
    # image evidence is present. Default off.
    runtime.data.vision_generation_meta: dict[str, Any] = {
        "enabled": bool(settings.VISION_RAG_GENERATION_ENABLED),
        "used": False,
        "reason": "not_run",
    }

    # Optional: TAG bridge - inject bounded table query results as extra context.
    runtime.data.tag_docs: list[Document] = []
    runtime.data.tag_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}


async def retrieve_tag_context(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    try:
        from app.services.tables.chat_context import build_chat_tag_context_docs

        if (
            str(runtime.data.multimodal_modality or "text").strip().lower() == "table"
            and runtime.data.db is not None
            and runtime.data.tenant_id is not None
            and runtime.data.document_ids
        ):
            # Only show TAG progress when the feature is actually enabled.
            if (
                bool(settings.CHAT_TAG_ENABLED)
                and bool(settings.TABLE_NL2SQL_ENABLED)
                and bool(settings.TABLE_LLM_ALLOW_RESULT_EGRESS)
                and bool(str(settings.LLM_API_KEY).strip())
            ):
                yield {"type": "event", "data": {"message": "检测到表格资产，正在尝试表格查询（TAG）..."}}
            runtime.data.tag_docs, runtime.data.tag_meta = await run_blocking_in_thread(
                build_chat_tag_context_docs,
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
    await run_blocking_in_thread(_release_request_session, runtime.data.db)

    if runtime.data.tag_docs:
        runtime.data.docs = (runtime.data.tag_docs) + (runtime.data.docs)


RETRIEVAL_OPERATIONS = (
    StreamOperation(build_retriever_and_base_queries, streams=True),
    StreamOperation(extend_queries_and_prepare_plan, streams=False),
    StreamOperation(build_retrieval_plan, streams=False),
    StreamOperation(execute_retrieval_plan, streams=True),
    StreamOperation(initialize_fusion, streams=False),
    StreamOperation(fuse_retrieval_results, streams=False),
    StreamOperation(initialize_kg_enrichment, streams=False),
    StreamOperation(inject_kg_chunks, streams=False),
    StreamOperation(boost_kg_and_select_images, streams=False),
    StreamOperation(read_images_and_initialize_tag, streams=True),
    StreamOperation(retrieve_tag_context, streams=True),
)

__all__ = ["RETRIEVAL_OPERATIONS"]

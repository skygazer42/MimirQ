"""Inject graph evidence and annotate graph ranking features."""

import asyncio
import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.retrieval.ranking.knowledge_graph import (
    _apply_kg_chunk_boost,
    _fetch_document_chunks_for_kg_injection,
    _merge_kg_docs_preserving_main,
    _resolve_kg_scope,
)
from app.rag.retrieval.results import _log_orchestrator_fallback, _safe_float, _safe_int
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.types.document_metadata import metadata_text

if TYPE_CHECKING:
    from app.models.documents.records import DocumentChunk
from app.rag.retrieval.results import _RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE

logger = logging.getLogger("app.rag.retrieval.orchestrator")


_kg_provenance_logger = logging.getLogger("app.rag.retrieval.orchestrator_support_hierarchy")
_KG_PROVENANCE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical retrieval orchestrator fallback failure: %s"


def _bounded_kg_path_text(value: Any, *, limit: int) -> str | None:
    if value is None:
        return None
    return str(value).strip()[:limit]


def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    out: dict[str, Any] = {}
    schema = _bounded_kg_path_text(raw.get("schema"), limit=80)
    if schema:
        out["schema"] = schema
    kind = _bounded_kg_path_text(raw.get("kind"), limit=50)
    if kind:
        out["kind"] = kind
    try:
        if raw.get("hops") is not None:
            out["hops"] = int(raw.get("hops") or 0)
    except Exception as exc:  # noqa: BLE001
        _kg_provenance_logger.debug(_KG_PROVENANCE_FALLBACK_LOG_MESSAGE, exc)

    nodes = _safe_kg_path_items(
        raw.get("nodes"),
        allowed_keys=("entity_id", "type", "event_id", "document_id", "chunk_id"),
    )
    if nodes:
        out["nodes"] = nodes

    edges = _safe_kg_path_items(
        raw.get("edges"),
        allowed_keys=(
            "entity_id",
            "event_id",
            "document_id",
            "chunk_id",
            "relation_id",
            "predicate",
            "confidence_bucket",
            "evidence_source",
        ),
    )
    if edges:
        out["edges"] = edges

    return out


def _safe_kg_path_items(raw_items: Any, *, allowed_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list) or not raw_items:
        return []
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        item: dict[str, Any] = {}
        kind = _bounded_kg_path_text(raw_item.get("kind"), limit=30)
        if kind:
            item["kind"] = kind
        for key in allowed_keys:
            value = raw_item.get(key)
            if value is None:
                continue
            text = _bounded_kg_path_text(value, limit=200)
            if text:
                item[key] = text
        if item:
            items.append(item)
        if len(items) >= 10:
            break
    return items


def _run_kg_search_sync(kg_kwargs: dict[str, Any]) -> Any:
    from app.rag.kg.pipeline import kg_search

    coro = kg_search(**kg_kwargs)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    if loop is not None:
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


def _kg_path_steps(raw_path: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_path, list):
        return []
    path: list[dict[str, Any]] = []
    for step in raw_path:
        if not isinstance(step, dict):
            continue
        entity_id = metadata_text(step, "entity_id")
        if not entity_id:
            continue
        entry: dict[str, Any] = {"entity_id": entity_id}
        entity_type = metadata_text(step, "type")
        if entity_type:
            entry["type"] = entity_type[:100]
        path.append(entry)
        if len(path) >= 6:
            break
    return path


def _kg_event_features(event: dict[str, Any]) -> dict[str, Any]:
    features = {
        key: event.get(key)
        for key in ("kg_path_length", "kg_shared_events", "kg_evidence_anchored")
        if event.get(key) is not None
    }
    path = _kg_path_steps(event.get("kg_path"))
    if path:
        features["kg_path"] = path
    provenance = _safe_kg_path_provenance(event.get("kg_path_provenance"))
    if provenance:
        features["kg_path_provenance"] = provenance
    return features


def _kg_event_candidate(event: Any) -> tuple[UUID, float, dict[str, Any]] | None:
    if not isinstance(event, dict) or event.get("chunk_id") is None:
        return None
    try:
        chunk_id = UUID(str(event.get("chunk_id")))
    except (TypeError, ValueError):
        return None
    try:
        score = float(event.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return chunk_id, score, _kg_event_features(event)


def _collect_kg_injection_candidates(
    events: Any,
    *,
    limit: int,
) -> tuple[list[UUID], dict[str, float], dict[str, dict[str, Any]]]:
    chunk_ids: list[UUID] = []
    scores: dict[str, float] = {}
    features: dict[str, dict[str, Any]] = {}
    seen: set[UUID] = set()
    for event in events if isinstance(events, list) else []:
        candidate = _kg_event_candidate(event)
        if candidate is None:
            continue
        chunk_id, score, chunk_features = candidate
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk_ids.append(chunk_id)
        scores[str(chunk_id)] = score
        if chunk_features:
            features[str(chunk_id)] = chunk_features
        if len(chunk_ids) >= limit:
            break
    return chunk_ids, scores, features


def _fetch_kg_injection_rows(
    ctx: RetrievalRuntimeState,
    *,
    tenant_id: UUID,
    account_id: str | None,
    dataset_id: UUID | None,
    dataset_ids: list[UUID],
    document_ids: list[UUID] | None,
    chunk_ids: list[UUID],
) -> list["DocumentChunk"]:
    db = ctx.state.get("db")
    owns_db = db is None
    if owns_db:
        from app.infrastructure.database.connection import SessionLocal

        db = SessionLocal()
    try:
        fetch_kwargs = {
            "db": db,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "dataset_id": dataset_id,
            "document_ids": document_ids,
            "chunk_ids": chunk_ids,
        }
        if dataset_ids:
            fetch_kwargs["dataset_ids"] = dataset_ids
        return _fetch_document_chunks_for_kg_injection(**fetch_kwargs)
    finally:
        if owns_db:
            try:
                db.close()
            except Exception as exc:
                logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)


def _kg_chunk_row_map(rows: list["DocumentChunk"]) -> dict[UUID, "DocumentChunk"]:
    return {chunk.id: chunk for chunk in rows}


def _kg_document_from_chunk(
    chunk_id: UUID,
    chunk: "DocumentChunk",
    *,
    scores: dict[str, float],
    features: dict[str, dict[str, Any]],
) -> Document:
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
    score = scores.get(str(chunk_id))
    if score is not None:
        metadata.setdefault("retrieval_score", score)
        metadata.setdefault("score", score)
    for key, value in features.get(str(chunk_id), {}).items():
        if value is not None:
            metadata[key] = value
    return Document(
        page_content=chunk.content,
        metadata=metadata,
        id=str(chunk_id),
    )


def _build_kg_injection_docs(
    chunk_ids: list[UUID],
    rows: list["DocumentChunk"],
    *,
    scores: dict[str, float],
    features: dict[str, dict[str, Any]],
) -> list[Document]:
    chunks = _kg_chunk_row_map(rows)
    return [
        _kg_document_from_chunk(chunk_id, chunks[chunk_id], scores=scores, features=features)
        for chunk_id in chunk_ids
        if chunk_id in chunks
    ]


def _run_kg_injection(ctx: RetrievalRuntimeState) -> list[Document]:
    if ctx.query_plan.kg.failure is not None:
        raise ctx.query_plan.kg.failure
    tenant_id = UUID(str(ctx.state["tenant_id"]))
    account_id = ctx.state.get("account_id")
    document_ids, dataset_id, dataset_ids = _resolve_kg_scope(ctx.state)
    kg_result = ctx.kg_result_cached
    if kg_result is None:
        kg_kwargs = {
            "query": ctx.query_for_retrieval,
            "tenant_id": tenant_id,
            "document_ids": document_ids,
            "dataset_id": dataset_id,
            "account_id": account_id,
        }
        if dataset_ids:
            kg_kwargs["dataset_ids"] = dataset_ids
        kg_result = _run_kg_search_sync(kg_kwargs)
    chunk_ids, scores, features = _collect_kg_injection_candidates(
        (kg_result or {}).get("events") or [],
        limit=ctx.kg_chunk_injection_max_chunks,
    )
    if not chunk_ids:
        return []
    rows = _fetch_kg_injection_rows(
        ctx,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        dataset_ids=dataset_ids,
        document_ids=document_ids,
        chunk_ids=chunk_ids,
    )
    return _build_kg_injection_docs(chunk_ids, rows, scores=scores, features=features)


def _run_retrieval_kg_injection_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    injection_requested = ctx.state.get("enable_kg_chunk_injection")
    ctx.kg_chunk_injection_enabled = (
        settings.RAG_KG_CHUNK_INJECTION_ENABLED if injection_requested is None else injection_requested
    )
    ctx.kg_chunk_injection_max_chunks = _safe_int(
        ctx.state.get("kg_chunk_injection_max_chunks"),
        default=int(settings.RAG_KG_CHUNK_INJECTION_MAX_CHUNKS),
        minimum=0,
        maximum=50,
    )
    ctx.kg_chunks_injected = 0
    ctx.kg_chunk_injection_error: str | None = None
    enabled = (
        bool(ctx.kg_chunk_injection_enabled)
        and ctx.kg_chunk_injection_max_chunks > 0
        and bool(settings.KG_ENABLED)
        and bool(settings.KG_CHAT_ENABLED)
        and ctx.state.get("tenant_id") is not None
        and any(_resolve_kg_scope(ctx.state))
    )
    if enabled:
        try:
            kg_docs = _run_kg_injection(ctx)
            if kg_docs:
                ctx.docs = _merge_kg_docs_preserving_main(ctx.docs, kg_docs)
                ctx.kg_chunks_injected = len(kg_docs)
        except Exception as exc:  # noqa: BLE001 - optional KG enrichment reports failure without changing main evidence.
            _log_orchestrator_fallback("kg_chunk_injection", exc)
            ctx.kg_chunk_injection_error = str(exc)[:200]
            return None
    return None


def _tag_document(raw: Any) -> Document | None:
    if isinstance(raw, Document):
        return raw
    if not isinstance(raw, dict):
        return None
    content = raw.get("page_content")
    if content is None:
        content = raw.get("content")
    if content is None:
        return None
    metadata = raw.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    try:
        return Document(
            page_content=str(content),
            metadata=metadata,
            id=raw.get("id") or metadata.get("chunk_id"),
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        return None


def _tag_documents(raw: Any) -> list[Document]:
    if not isinstance(raw, list):
        return []
    return [document for item in raw[:10] if (document := _tag_document(item)) is not None]


def _safe_metadata_float(metadata: dict[str, Any], key: str, *, fallback_key: str | None = None) -> float:
    raw = metadata.get(key)
    if raw is None and fallback_key is not None:
        raw = metadata.get(fallback_key)
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _safe_metadata_int(metadata: dict[str, Any], key: str, *, default: int) -> int:
    try:
        return int(metadata.get(key)) if metadata.get(key) is not None else default
    except (TypeError, ValueError):
        return default


def _kg_confidence_buckets(score: float) -> tuple[float, float, float]:
    if score >= 0.75:
        return 0.0, 0.0, 1.0
    if score >= 0.5:
        return 0.0, 1.0, 0.0
    if score > 0.0:
        return 1.0, 0.0, 0.0
    return 0.0, 0.0, 0.0


def _annotate_kg_ranking_features(doc: Document) -> None:
    metadata = doc.metadata or {}
    role = str(metadata.get("retrieval_role") or "main").strip().lower() or "main"
    has_kg_signal = _safe_metadata_float(metadata, "kg_pagerank") > 0.0
    if role != "kg" and not has_kg_signal:
        return
    kg_score = _safe_metadata_float(metadata, "kg_pagerank", fallback_key="score")
    metadata["kg_pagerank"] = kg_score
    metadata["kg_path_length"] = max(
        1,
        min(_safe_metadata_int(metadata, "kg_path_length", default=1), 5),
    )
    metadata["kg_shared_events"] = max(
        0,
        min(_safe_metadata_int(metadata, "kg_shared_events", default=1), 5),
    )
    metadata["kg_evidence_anchored"] = bool(metadata.get("kg_evidence_anchored", True))
    low, mid, high = _kg_confidence_buckets(kg_score)
    metadata["kg_edge_conf_low"] = low
    metadata["kg_edge_conf_mid"] = mid
    metadata["kg_edge_conf_high"] = high


def _annotate_kg_ranking_docs(docs: list[Document]) -> None:
    try:
        for doc in docs:
            if doc is not None:
                _annotate_kg_ranking_features(doc)
    except Exception as exc:
        logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)


def _run_retrieval_tag_kg_boost_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    tag_docs = _tag_documents(ctx.state.get("tag_docs"))
    if tag_docs:
        ctx.docs = tag_docs + (ctx.docs)
    _annotate_kg_ranking_docs(ctx.docs)

    boost_requested = ctx.state.get("enable_kg_chunk_boost")
    kg_chunk_boost_enabled = settings.RAG_KG_CHUNK_BOOST_ENABLED if boost_requested is None else boost_requested
    kg_chunk_boost_weight = _safe_float(
        ctx.state.get("kg_chunk_boost_weight"),
        default=float(settings.RAG_KG_CHUNK_BOOST_WEIGHT),
        minimum=0.0,
        maximum=1.0,
    )
    kg_chunk_boost_max_promoted = _safe_int(
        ctx.state.get("kg_chunk_boost_max_promoted"),
        default=int(settings.RAG_KG_CHUNK_BOOST_MAX_PROMOTED),
        minimum=0,
        maximum=20,
    )
    ctx.docs, ctx.kg_chunk_boost_meta = _apply_kg_chunk_boost(
        [d for d in (ctx.docs) if isinstance(d, Document)],
        enabled=kg_chunk_boost_enabled,
        weight=kg_chunk_boost_weight,
        max_promoted=kg_chunk_boost_max_promoted,
    )
    return None

"""
Facade to run KG extraction + search inside the existing backend.
KG module can be toggled via settings.KG_ENABLED (env: KG_ENABLED).
"""

import asyncio
import logging
import threading
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.hashing import stable_hash
from app.rag.kg.engine import KGEngine
from app.rag.kg.search.cache import build_kg_search_cache_key, kg_search_cache
from app.rag.kg.search.query_mode import classify_kg_query_mode, normalize_kg_query_mode
from app.types.indexing import IndexingOptions

_engine: KGEngine | None = None
_engine_lock = threading.Lock()


def _resolve_doc_pipeline_fingerprint(*, tenant_id: UUID, document_ids: list[str]) -> str | None:
    """
    Best-effort helper for KG search cache key versioning.

    Returns a short, stable digest that changes when any scoped document's
    active_pipeline_hash (fallback pipeline_hash) changes.

    If version scope cannot be resolved cheaply/reliably, return None so callers
    can disable caching (safer than serving stale results).
    """
    if not document_ids:
        return None
    doc_uuids: list[UUID] = []
    for d in document_ids:
        try:
            doc_uuids.append(UUID(str(d)))
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    if not doc_uuids:
        return None

    # Keep query tight: only fetch id + active pipeline hash expression.
    # NOTE: mirror app.core.pipeline_versions.get_active_pipeline_hash semantics.
    from sqlalchemy import func

    active_expr = func.coalesce(
        DBDocument.doc_metadata["active_pipeline_hash"].astext,  # type: ignore[attr-defined]
        DBDocument.doc_metadata["pipeline_hash"].astext,  # type: ignore[attr-defined]
    )

    db = SessionLocal()
    try:
        rows = (
            db.query(DBDocument.id, active_expr)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(doc_uuids))
            .all()
        )
    except Exception:
        return None
    finally:
        db.close()

    # If any doc is missing (wrong tenant / deleted), don't cache.
    if not rows or len(rows) != len(set(doc_uuids)):
        return None

    # Hash doc_id:pipeline_hash pairs so the cache key invalidates when any doc flips versions.
    pairs: list[str] = []
    for doc_id, pipeline_hash in rows:
        ph = str(pipeline_hash or "").strip()
        pairs.append(f"{doc_id}:{ph}")
    joined = ",".join(sorted(pairs))
    return stable_hash(joined, length=32)


def _resolve_dataset_pipeline_fingerprint(*, tenant_id: UUID, dataset_ids: list[UUID]) -> str | None:
    """
    Version KG search cache entries for dataset-scoped retrieval.

    Dify external knowledge calls normally search by dataset scope rather than
    document scope. Use dataset updated_at as the invalidation token so repeated
    workflow nodes can reuse KG recall without serving stale results after ingest.
    """
    scoped_dataset_ids = []
    seen: set[UUID] = set()
    for dataset_id in dataset_ids or []:
        if dataset_id is None or dataset_id in seen:
            continue
        seen.add(dataset_id)
        scoped_dataset_ids.append(dataset_id)
    if not scoped_dataset_ids:
        return None

    db = SessionLocal()
    try:
        rows = (
            db.query(Dataset.id, Dataset.updated_at)
            .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(scoped_dataset_ids))
            .all()
        )
    except Exception:
        return None
    finally:
        db.close()

    if not rows or len(rows) != len(scoped_dataset_ids):
        return None

    pairs = [f"{dataset_id}:{updated_at.isoformat() if hasattr(updated_at, 'isoformat') else updated_at}" for dataset_id, updated_at in rows]
    return stable_hash(",".join(sorted(pairs)), length=32)


def reset_kg_engine() -> None:
    """Drop the cached process-wide KGEngine (used for tests and runtime toggles)."""
    global _engine
    with _engine_lock:
        _engine = None


def reset_kg_search_cache() -> None:
    """Clear the process-wide KG search cache (used for tests and runtime toggles)."""
    kg_search_cache.clear()


def _load_engine() -> KGEngine:
    global _engine
    if not settings.KG_ENABLED:
        # Ensure runtime toggles can't leave a live engine behind.
        reset_kg_engine()
        raise RuntimeError("KG plugin is disabled. Set KG_ENABLED=true to enable.")

    if _engine is not None:
        return _engine

    # Avoid double-init under concurrent first requests.
    with _engine_lock:
        if _engine is None:
            _engine = KGEngine()
        return _engine


def _dedupe_uuid_list(values: Iterable[UUID] | None) -> list[UUID]:
    out: list[UUID] = []
    seen: set[UUID] = set()
    for value in values or []:
        try:
            item = value if isinstance(value, UUID) else UUID(str(value))
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _kg_result_item_key(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = str(item.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return stable_hash(str(sorted(item.items())), length=24)


def _kg_item_score(item: dict[str, Any]) -> float:
    for field in ("score", "weight", "relevance_score"):
        try:
            return float(item.get(field) or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
    return 0.0


def _merge_kg_dataset_shard_results(
    shards: list[tuple[UUID, dict[str, Any] | None, str | None]],
) -> dict[str, Any]:
    events_by_key: dict[str, dict[str, Any]] = {}
    entities_by_key: dict[str, dict[str, Any]] = {}
    clues_by_key: dict[str, Any] = {}
    community_reports: list[Any] = []
    global_summaries: list[str] = []
    shard_stats: list[dict[str, Any]] = []
    errors = 0
    merge_order = 0

    for dataset_id, result, error in shards:
        if error:
            errors += 1
            shard_stats.append({"dataset_id": str(dataset_id), "error": str(error)[:200]})
            continue
        data = result if isinstance(result, dict) else {}
        events = data.get("events") if isinstance(data.get("events"), list) else []
        entities = data.get("entities") if isinstance(data.get("entities"), list) else []
        clues = data.get("clues") if isinstance(data.get("clues"), list) else []
        shard_stats.append(
            {
                "dataset_id": str(dataset_id),
                "events": len(events),
                "entities": len(entities),
                "clues": len(clues),
            }
        )

        for event in events:
            if not isinstance(event, dict):
                continue
            enriched = dict(event)
            enriched.setdefault("dataset_id", str(dataset_id))
            key = _kg_result_item_key(enriched, ("id", "event_id", "chunk_id"))
            current = events_by_key.get(key)
            if current is None:
                enriched["_merge_order"] = merge_order
                merge_order += 1
                events_by_key[key] = enriched
            elif _kg_item_score(enriched) > _kg_item_score(current):
                enriched["_merge_order"] = current.get("_merge_order", merge_order)
                events_by_key[key] = enriched

        for entity in entities:
            if not isinstance(entity, dict):
                continue
            key = _kg_result_item_key(entity, ("entity_id", "id", "name", "normalized_name"))
            current = entities_by_key.get(key)
            if current is None:
                enriched_entity = dict(entity)
                enriched_entity["_merge_order"] = merge_order
                merge_order += 1
                entities_by_key[key] = enriched_entity
            elif _kg_item_score(entity) > _kg_item_score(current):
                enriched_entity = dict(entity)
                enriched_entity["_merge_order"] = current.get("_merge_order", merge_order)
                entities_by_key[key] = enriched_entity

        for clue in clues:
            clues_by_key.setdefault(stable_hash(str(clue), length=24), clue)

        reports = data.get("community_reports")
        if isinstance(reports, list):
            community_reports.extend(reports)
        summary = str(data.get("global_summary") or "").strip()
        if summary:
            global_summaries.append(summary)

    max_events = max(1, int(getattr(settings, "KG_SEARCH_MULTI_DATASET_MAX_EVENTS", 80) or 80))
    max_entities = max(1, int(getattr(settings, "KG_SEARCH_MULTI_DATASET_MAX_ENTITIES", 80) or 80))
    events = sorted(
        events_by_key.values(),
        key=lambda item: (-_kg_item_score(item), int(item.get("_merge_order", 0) or 0)),
    )[:max_events]
    entities = sorted(
        entities_by_key.values(),
        key=lambda item: (-_kg_item_score(item), int(item.get("_merge_order", 0) or 0)),
    )[:max_entities]
    for item in [*events, *entities]:
        if isinstance(item, dict):
            item.pop("_merge_order", None)
    clues = list(clues_by_key.values())

    return {
        "events": events,
        "entities": entities,
        "clues": clues,
        "stats": {
            "multi_dataset_scope": True,
            "dataset_shards": len(shards),
            "dataset_shards_with_events": sum(1 for _dataset_id, result, _error in shards if result and result.get("events")),
            "dataset_shard_errors": errors,
            "dataset_shard_stats": shard_stats[:50],
            "candidates": len(events),
            "clues_returned": len(clues),
        },
        "community_reports": community_reports[:50],
        "global_summary": "\n\n".join(global_summaries[:5]),
        "query": {"scope": "multi_dataset"},
    }


async def extract_events(
    chunk_ids: Iterable[UUID],
    tenant_id: UUID | None = None,
    *,
    chunks: Sequence[DocumentChunk] | None = None,
    index_options: IndexingOptions | None = None,
    prompt_template_id: UUID | None = None,
    prompt_template_key: str | None = None,
    prompt_ab_experiment_key: str | None = None,
    ab_user_key: str | None = None,
    extract_relations: bool | None = None,
    extract_skills: bool | None = None,
    extraction_backend: str | None = None,
    kg_python_plugin: str | None = None,
    kg_python_params: dict | None = None,
    replace_existing: bool | None = None,
    prune_orphan_entities: bool | None = None,
):
    engine = _load_engine()
    return await engine.extract(
        chunk_ids,
        tenant_id=tenant_id,
        chunks=chunks,
        index_options=index_options,
        prompt_template_id=prompt_template_id,
        prompt_template_key=prompt_template_key,
        prompt_ab_experiment_key=prompt_ab_experiment_key,
        ab_user_key=ab_user_key,
        extract_relations=extract_relations,
        extract_skills=extract_skills,
        extraction_backend=extraction_backend,
        kg_python_plugin=kg_python_plugin,
        kg_python_params=kg_python_params,
        replace_existing=replace_existing,
        prune_orphan_entities=prune_orphan_entities,
    )


async def kg_search(
    query: str,
    tenant_id: UUID | None = None,
    document_ids: list[UUID] | None = None,
    dataset_id: UUID | None = None,
    dataset_ids: list[UUID] | None = None,
    account_id: str | None = None,
    query_mode: str | None = None,
) -> dict:
    scoped_dataset_ids = _dedupe_uuid_list(dataset_ids)
    if document_ids or dataset_id is not None:
        scoped_dataset_ids = []
    if len(scoped_dataset_ids) == 1:
        dataset_id = scoped_dataset_ids[0]
        scoped_dataset_ids = []
    if scoped_dataset_ids:
        max_concurrency = max(1, int(getattr(settings, "KG_SEARCH_MULTI_DATASET_MAX_CONCURRENCY", 4) or 4))
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _search_shard(scoped_dataset_id: UUID) -> tuple[UUID, dict[str, Any] | None, str | None]:
            async with semaphore:
                try:
                    result = await kg_search(
                        query=query,
                        tenant_id=tenant_id,
                        document_ids=None,
                        dataset_id=scoped_dataset_id,
                        dataset_ids=None,
                        account_id=account_id,
                        query_mode=query_mode,
                    )
                    return scoped_dataset_id, result if isinstance(result, dict) else {}, None
                except Exception as exc:  # noqa: BLE001
                    return scoped_dataset_id, None, str(exc)[:200]

        shards = await asyncio.gather(*[_search_shard(scoped_dataset_id) for scoped_dataset_id in scoped_dataset_ids])
        return _merge_kg_dataset_shard_results(list(shards))

    default_mode = str(getattr(settings, "KG_SEARCH_QUERY_MODE_DEFAULT", "auto") or "auto")
    requested_mode = normalize_kg_query_mode(query_mode, default=default_mode)
    classifier_enabled = bool(getattr(settings, "KG_SEARCH_QUERY_MODE_CLASSIFIER_ENABLED", True))
    mode_diag: dict[str, Any]
    if requested_mode == "auto" and classifier_enabled:
        mode_diag = classify_kg_query_mode(
            query=str(query or ""),
            document_ids=list(document_ids or []),
            dataset_id=dataset_id,
            default_mode="auto",
        )
    else:
        mode_diag = {
            "mode": normalize_kg_query_mode(requested_mode, default="global"),
            "confidence": ("forced" if requested_mode != "auto" else "disabled"),
            "reason_codes": (["query_mode_classifier_disabled"] if requested_mode == "auto" and not classifier_enabled else ["query_mode_requested"]),
        }
    resolved_mode = normalize_kg_query_mode(mode_diag.get("mode"), default="global")
    mode_diag["mode"] = resolved_mode

    cache_enabled = bool(getattr(settings, "KG_SEARCH_CACHE_ENABLED", False))
    ttl_sec = int(getattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 0) or 0)
    max_entries = int(getattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 0) or 0)

    cache_key: str | None = None
    if cache_enabled and ttl_sec > 0 and max_entries > 0:
        eff_tenant_id = tenant_id or settings.DEFAULT_TENANT_ID
        eff_doc_ids = [str(d) for d in (document_ids or []) if d is not None]
        pipeline_fp: str | None = None
        scoped_cache_dataset_id = dataset_id if dataset_id is not None else None
        try:
            if eff_doc_ids:
                pipeline_fp = _resolve_doc_pipeline_fingerprint(tenant_id=eff_tenant_id, document_ids=eff_doc_ids)
            elif scoped_cache_dataset_id is not None:
                pipeline_fp = _resolve_dataset_pipeline_fingerprint(
                    tenant_id=eff_tenant_id,
                    dataset_ids=[scoped_cache_dataset_id],
                )
        except Exception:
            pipeline_fp = None

        if pipeline_fp:
            cache_key = build_kg_search_cache_key(
                tenant_id=str(eff_tenant_id),
                account_id=str(account_id or ""),
                dataset_id=(str(scoped_cache_dataset_id) if scoped_cache_dataset_id is not None else None),
                document_ids=eff_doc_ids,
                pipeline_fingerprint=pipeline_fp,
                query=str(query or ""),
                search_config={
                    # Include settings that can change KG search behavior so runtime toggles do not
                    # serve stale cached results.
                    "KG_SEARCH_RELATION_EXPANSION_ENABLED": bool(
                        getattr(settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False)
                    ),
                    "KG_RELATION_ENABLED": bool(getattr(settings, "KG_RELATION_ENABLED", False)),
                    # GraphRAG-like global search (community summaries) is optional and must be part
                    # of the cache key to avoid mixing results across feature toggles.
                    "KG_COMMUNITY_ENABLED": bool(getattr(settings, "KG_COMMUNITY_ENABLED", False)),
                    "KG_COMMUNITY_REQUIRE_GLOBAL_PATTERN": bool(
                        getattr(settings, "KG_COMMUNITY_REQUIRE_GLOBAL_PATTERN", True)
                    ),
                    "KG_COMMUNITY_MAX_EVENTS": int(getattr(settings, "KG_COMMUNITY_MAX_EVENTS", 0) or 0),
                    "KG_COMMUNITY_MAX_ENTITIES_PER_EVENT": int(
                        getattr(settings, "KG_COMMUNITY_MAX_ENTITIES_PER_EVENT", 0) or 0
                    ),
                    "KG_COMMUNITY_MIN_EDGE_WEIGHT": float(getattr(settings, "KG_COMMUNITY_MIN_EDGE_WEIGHT", 0.0) or 0.0),
                    "KG_SEARCH_RELATION_MIN_CONFIDENCE": float(
                        getattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0) or 0.0
                    ),
                    "KG_SEARCH_RELATION_MAX_EDGES": int(getattr(settings, "KG_SEARCH_RELATION_MAX_EDGES", 0) or 0),
                    "KG_SEARCH_RELATION_MAX_NEIGHBORS": int(
                        getattr(settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 0) or 0
                    ),
                    "KG_SEARCH_MAX_RERANK_CANDIDATES": int(
                        getattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0) or 0
                    ),
                    "KG_SEARCH_EXPAND_BUDGET_SEC": float(
                        getattr(settings, "KG_SEARCH_EXPAND_BUDGET_SEC", 0.0) or 0.0
                    ),
                    "KG_SEARCH_QUERY_MODE": str(resolved_mode),
                    "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS": int(
                        getattr(settings, "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS", 0) or 0
                    ),
                    "KG_SEARCH_SERVING_LAYER_ENABLED": bool(
                        getattr(settings, "KG_SEARCH_SERVING_LAYER_ENABLED", True)
                    ),
                    "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK": int(
                        getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK", 0) or 0
                    ),
                    "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT": int(
                        getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT", 0) or 0
                    ),
                    "KG_SEARCH_SERVING_MIN_SCORE": float(
                        getattr(settings, "KG_SEARCH_SERVING_MIN_SCORE", 0.0) or 0.0
                    ),
                    "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER": int(
                        getattr(settings, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER", 0) or 0
                    ),
                },
            )
            cached, _age_ms = kg_search_cache.get(cache_key, ttl_sec=ttl_sec)
            if cached is not None:
                return cached

    engine = _load_engine()
    result = await engine.search(
        query=query,
        tenant_id=tenant_id,
        document_ids=document_ids,
        dataset_id=dataset_id,
        account_id=account_id,
        query_mode=resolved_mode,
        query_mode_reason_codes=list(mode_diag.get("reason_codes") or []),
        query_mode_confidence=str(mode_diag.get("confidence") or ""),
    )
    if isinstance(result, dict):
        result["query_mode"] = {
            "requested": str(requested_mode),
            "resolved": str(resolved_mode),
            "confidence": str(mode_diag.get("confidence") or ""),
            "reason_codes": [str(x) for x in (mode_diag.get("reason_codes") or []) if str(x).strip()][:8],
        }
        stats = result.get("stats")
        if isinstance(stats, dict):
            stats["query_mode"] = str(resolved_mode)
            stats["query_mode_confidence"] = str(mode_diag.get("confidence") or "")
            stats["query_mode_reason_codes"] = [str(x) for x in (mode_diag.get("reason_codes") or []) if str(x).strip()][:8]
            result["stats"] = stats
    if cache_key is not None and isinstance(result, dict):
        kg_search_cache.set(cache_key, dict(result), ttl_sec=ttl_sec, max_entries=max_entries)
    return result

"""
Facade to run KG extraction + search inside the existing backend.
KG module can be toggled via settings.KG_ENABLED (env: KG_ENABLED).
"""

import threading
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
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
        replace_existing=replace_existing,
        prune_orphan_entities=prune_orphan_entities,
    )


async def kg_search(
    query: str,
    tenant_id: UUID | None = None,
    document_ids: list[UUID] | None = None,
    dataset_id: UUID | None = None,
    account_id: str | None = None,
    query_mode: str | None = None,
) -> dict:
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
        if eff_doc_ids:
            pipeline_fp: str | None = None
            try:
                pipeline_fp = _resolve_doc_pipeline_fingerprint(tenant_id=eff_tenant_id, document_ids=eff_doc_ids)
            except Exception:
                pipeline_fp = None

            if pipeline_fp:
                cache_key = build_kg_search_cache_key(
                    tenant_id=str(eff_tenant_id),
                    account_id=str(account_id or ""),
                    dataset_id=(str(dataset_id) if dataset_id is not None else None),
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
                        "KG_SEARCH_QUERY_MODE": str(resolved_mode),
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

"""Bounded, PII-safe sanitizers for retrieval debug payloads.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

from typing import Any

from app.rag.retrieval.orchestration.common import _safe_float, _safe_int


def _copy_present_debug_keys(out: dict[str, Any], source: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = source.get(key)
        if value is not None:
            out[key] = value


def _sanitize_query_normalization_debug(raw: Any) -> dict[str, Any] | None:
    qn = raw if isinstance(raw, dict) else {}
    normalized = qn.get("normalized") if isinstance(qn.get("normalized"), str) else ""
    applied_rules = qn.get("applied_rules") if isinstance(qn.get("applied_rules"), list) else []
    if not normalized and not applied_rules:
        return None
    return {
        "applied_rules": [str(x) for x in applied_rules if x is not None][:20],
        "original_chars": len(str(qn.get("original") or "")),
        "normalized_chars": len(str(normalized or "")),
    }


def _sanitize_diversity_debug(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, int] = {}
    for key in (
        "max_chunks_per_doc",
        "max_chunks_per_page",
        "min_distinct_docs",
        "pre_unique_docs",
        "post_unique_docs",
        "pre_unique_pages",
        "post_unique_pages",
        "moved_out",
        "moved_in",
    ):
        if key in raw:
            out[key] = _safe_int(raw.get(key), minimum=0, maximum=1_000_000_000)
    return out or None


def _bounded_string_sample(raw: Any, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        if len(out) >= limit:
            break
    return out


def _sanitize_metadata_filter_ops(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    ops: dict[str, int] = {}
    for op_key, op_value in raw.items():
        if not isinstance(op_key, str) or not op_key.startswith("$"):
            continue
        ops[op_key] = _safe_int(op_value)
        if len(ops) >= 30:
            break
    return dict(sorted(ops.items(), key=lambda item: item[0]))


def _sanitize_metadata_filter_debug(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    keys_count = raw.get("keys_count")
    return {
        "keys_count": (_safe_int(keys_count) if keys_count is not None else None),
        "keys_sample": _bounded_string_sample(raw.get("keys_sample"), limit=10),
        "ops": _sanitize_metadata_filter_ops(raw.get("ops")),
    }


def _sanitize_enrich_pass_debug(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out = {
        "input_results": _safe_int(raw.get("input_results")),
        "output_results": _safe_int(raw.get("output_results")),
        "filtered_orphaned": _safe_int(raw.get("filtered_orphaned")),
        "filtered_acl": _safe_int(raw.get("filtered_acl")),
        "filtered_dataset": _safe_int(raw.get("filtered_dataset")),
        "filtered_not_ready": _safe_int(raw.get("filtered_not_ready")),
        "filtered_embedding_space": _safe_int(raw.get("filtered_embedding_space")),
        "filtered_pipeline_version": _safe_int(raw.get("filtered_pipeline_version")),
        "filtered_metadata_filter": _safe_int(raw.get("filtered_metadata_filter")),
    }
    for key in ("metadata_filter_blocked", "metadata_filter_matched"):
        if raw.get(key) is not None:
            out[key] = _safe_int(raw.get(key))
    metadata_filter = _sanitize_metadata_filter_debug(raw.get("metadata_filter"))
    if metadata_filter is not None:
        out["metadata_filter"] = metadata_filter
    return out


def _sanitize_timing_debug(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "vector_ms": _safe_float(raw.get("vector_ms")),
        "bm25_ms": _safe_float(raw.get("bm25_ms")),
        "lexical_ms": _safe_float(raw.get("lexical_ms")),
        "fusion_ms": _safe_float(raw.get("fusion_ms")),
    }


def _sanitize_counts_debug(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "vector_candidates": _safe_int(raw.get("vector_candidates")),
        "bm25_candidates": _safe_int(raw.get("bm25_candidates")),
    }


def _sanitize_governance_policy_debug(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("enabled", "prefer_authority", "prefer_latest", "filter_superseded", "reordered"):
        if key in raw:
            out[key] = bool(raw.get(key))
    for key in ("input_results", "output_results", "candidate_docs", "filtered_superseded"):
        if key in raw:
            out[key] = _safe_int(raw.get(key))
    for key in ("avg_boost", "max_boost"):
        if key in raw:
            out[key] = _safe_float(raw.get(key))
    skip_reason = str(raw.get("skip_reason") or "").strip() if raw.get("skip_reason") is not None else ""
    if skip_reason:
        out["skip_reason"] = skip_reason[:80]
    return out or None


def _sanitize_retriever_debug(dbg: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Shrink retriever debug payloads for API responses / metrics.

    Rationale:
    - Debug payloads may include large generated queries (HyDE) and verbose internal stats.
    - Evidence API returns metrics to downstream systems; keep payloads bounded and avoid leaking scope identifiers.
    """
    if not isinstance(dbg, dict) or not dbg:
        return None

    out: dict[str, Any] = {}
    _copy_present_debug_keys(out, dbg, (
        "requested_k",
        "search_k",
        "fetch_k",
        "overfetch_enabled",
        "overfetch_reasons",
        "overfetch_multiplier",
        "overfetch_cap_k",
        "milvus_doc_id_pushdown_skipped",
        "milvus_expr_max_doc_ids",
    ))

    qn = _sanitize_query_normalization_debug(dbg.get("query_normalization"))
    if qn is not None:
        out["query_normalization"] = qn

    # Doc/page diversity caps (PII-safe): expose only bounded numeric counters/settings.
    diversity = _sanitize_diversity_debug(dbg.get("diversity"))
    if diversity:
        out["diversity"] = diversity

    for key in ("enrich_pass1", "enrich_pass2"):
        enrich = _sanitize_enrich_pass_debug(dbg.get(key))
        if enrich is not None:
            out[key] = enrich

    timing = _sanitize_timing_debug(dbg.get("timing"))
    if timing is not None:
        out["timing"] = timing

    counts = _sanitize_counts_debug(dbg.get("counts"))
    if counts is not None:
        out["counts"] = counts

    governance_policy = _sanitize_governance_policy_debug(dbg.get("governance_policy"))
    if governance_policy is not None:
        out["governance_policy"] = governance_policy

    channels = dbg.get("channels")
    if isinstance(channels, dict):
        out["channels"] = channels

    return out or None

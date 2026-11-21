"""Project owned retriever diagnostics into bounded fields without query text or scope IDs."""

from typing import Any


def _copy_present_debug_keys(out: dict[str, Any], source: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = source.get(key)
        if value is not None:
            out[key] = value


def _sanitize_query_normalization_debug(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    return {
        "applied_rules": raw["applied_rules"][:20],
        "original_chars": len(raw["original"]),
        "normalized_chars": len(raw["normalized"]),
    }


def _sanitize_diversity_debug(raw: dict[str, int] | None) -> dict[str, int] | None:
    if raw is None:
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
            out[key] = min(max(0, raw[key]), 1_000_000_000)
    return out if out else None


def _sanitize_metadata_filter_debug(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    return {
        "keys_count": raw["keys_count"],
        "keys_sample": raw["keys_sample"][:10],
        "ops": dict(sorted(raw["ops"].items())[:30]),
    }


def _sanitize_enrich_pass_debug(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    out: dict[str, Any] = {}
    _copy_present_debug_keys(
        out,
        raw,
        (
            "input_results",
            "output_results",
            "filtered_orphaned",
            "filtered_acl",
            "filtered_dataset",
            "filtered_not_ready",
            "filtered_embedding_space",
            "filtered_pipeline_version",
            "filtered_metadata_filter",
            "metadata_filter_blocked",
            "metadata_filter_matched",
        ),
    )
    metadata_filter = _sanitize_metadata_filter_debug(raw.get("metadata_filter"))
    if metadata_filter is not None:
        out["metadata_filter"] = metadata_filter
    return out


def _sanitize_timing_debug(raw: dict[str, float] | None) -> dict[str, float] | None:
    if raw is None:
        return None
    return {key: raw[key] for key in ("vector_ms", "bm25_ms", "lexical_ms", "fusion_ms")}


def _sanitize_counts_debug(raw: dict[str, int] | None) -> dict[str, int] | None:
    if raw is None:
        return None
    return {key: raw[key] for key in ("vector_candidates", "bm25_candidates")}


def _sanitize_governance_policy_debug(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    out: dict[str, Any] = {}
    _copy_present_debug_keys(
        out,
        raw,
        (
            "enabled",
            "prefer_authority",
            "prefer_latest",
            "filter_superseded",
            "reordered",
            "input_results",
            "output_results",
            "candidate_docs",
            "filtered_superseded",
            "avg_boost",
            "max_boost",
        ),
    )
    return out if out else None


def _sanitize_retriever_debug(dbg: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Shrink retriever debug payloads for API responses / metrics.

    Rationale:
    - Debug payloads may include large generated queries (HyDE) and verbose internal stats.
    - Evidence API returns metrics to downstream systems; keep payloads bounded and avoid leaking scope identifiers.
    """
    if dbg is None:
        return None

    out: dict[str, Any] = {}
    _copy_present_debug_keys(
        out,
        dbg,
        (
            "requested_k",
            "search_k",
            "fetch_k",
            "overfetch_enabled",
            "overfetch_reasons",
            "overfetch_multiplier",
            "overfetch_cap_k",
            "milvus_doc_id_pushdown_skipped",
            "milvus_expr_max_doc_ids",
        ),
    )

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
    if channels is not None:
        out["channels"] = dict(channels)

    return out

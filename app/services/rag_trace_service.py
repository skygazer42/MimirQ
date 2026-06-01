"""
RAG trace reader (from metrics JSONL) for History/Graph visualization.

We intentionally do *not* return raw question/query/chunk text, even when
METRICS_LOG_INCLUDE_TEXT=true, because this endpoint is meant for UI tooling
and should stay PII-safe by construction.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.trace_schema import (
    RagTrace,
    RagTraceCitation,
    RagTraceListResponse,
    RagTraceRerank,
    RagTraceRetrieval,
    RagTraceRetrievalQuery,
    RagTraceStep,
)


def _to_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _to_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _to_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return None


_SAFE_ENRICH_STATS_KEYS = {
    "input_results",
    "filtered_orphaned",
    "filtered_acl",
    "filtered_dataset",
    "filtered_not_ready",
    "filtered_embedding_space",
    "filtered_pipeline_version",
    "filtered_metadata_filter",
    "metadata_filter_blocked",
    "metadata_filter_matched",
    "metadata_filter",
    "output_results",
    "exception",
}


def _compact_dict(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw.items() if v not in (None, [], {})}


def _bounded_safe_strings(raw: Any, *, max_items: int, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        safe = _safe_str(item, max_len=max_len)
        if safe is not None:
            out.append(safe)
        if len(out) >= max_items:
            break
    return out


def _safe_sorted_int_map(raw: Any, *, key_prefix: str | None = None, max_items: int = 30) -> dict[str, int]:
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        key_str = str(key)
        if key_prefix is not None and not key_str.startswith(key_prefix):
            continue
        safe_value = _to_int(value)
        if safe_value is None:
            continue
        out[key_str] = int(safe_value)
        if len(out) >= max_items:
            break
    return dict(sorted(out.items(), key=lambda item: item[0]))


def _safe_metadata_filter(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    metadata_filter = {
        "keys_count": _to_int(raw.get("keys_count")),
        "keys_sample": _bounded_safe_strings(raw.get("keys_sample"), max_items=10, max_len=120),
        "ops": _safe_sorted_int_map(raw.get("ops"), key_prefix="$", max_items=30),
    }
    return _compact_dict(metadata_filter) or None


def _safe_enrich_stats(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for k in _SAFE_ENRICH_STATS_KEYS:
        if k not in raw:
            continue
        if k == "metadata_filter":
            mf = _safe_metadata_filter(raw.get(k))
            if mf:
                out[k] = mf
            continue
        if k == "exception":
            s = (str(raw.get(k) or "")).strip()
            out[k] = s[:200] if s else None
            continue
        out[k] = _to_int(raw.get(k))
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def _safe_str(v: Any, *, max_len: int = 120) -> str | None:
    s = (str(v) if v is not None else "").strip()
    return s[:max_len] if s else None


def _safe_int(v: Any, *, lo: int = 0, hi: int = 1_000_000_000) -> int | None:
    n = _to_int(v)
    if n is None:
        return None
    if n < lo:
        n = lo
    if n > hi:
        n = hi
    return int(n)


def _safe_float(v: Any, *, lo: float = 0.0, hi: float = 1_000_000.0, digits: int = 3) -> float | None:
    n = _to_float(v)
    if n is None:
        return None
    if n < lo:
        n = lo
    if n > hi:
        n = hi
    try:
        return round(float(n), int(digits))
    except Exception:
        return None


def _add_safe_bools(out: dict[str, Any], raw: dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        if key not in raw:
            continue
        value = _to_bool(raw.get(key))
        if value is not None:
            out[key] = value


def _add_safe_ints(out: dict[str, Any], raw: dict[str, Any], keys: Iterable[str]) -> None:
    for key in keys:
        value = _safe_int(raw.get(key))
        if value is not None:
            out[key] = value


def _add_safe_strings(out: dict[str, Any], raw: dict[str, Any], specs: Iterable[tuple[str, int]]) -> None:
    for key, max_len in specs:
        value = _safe_str(raw.get(key), max_len=max_len)
        if value is not None:
            out[key] = value


def _safe_lexical_db_methods(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict) or not raw:
        return {}
    methods: dict[str, int] = {}
    for method_key, method_value in sorted(raw.items(), key=lambda kv: str(kv[0]))[:10]:
        safe_key = _safe_str(method_key, max_len=40)
        safe_value = _safe_int(method_value)
        if safe_key is not None and safe_value is not None:
            methods[safe_key] = safe_value
    return methods


def _safe_provider_status(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return {}
    status: dict[str, Any] = {}
    _add_safe_strings(
        status,
        raw,
        (
            ("requested_provider", 80),
            ("requested_provider_normalized", 80),
            ("effective_provider", 80),
            ("status", 40),
            ("reason", 80),
            ("outcome", 40),
        ),
    )
    _add_safe_bools(status, raw, ("provider_supported", "model_required", "model_configured"))
    return status


def _safe_lexical_db_box_fields(box_raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fts_config = _safe_str(box_raw.get("fts_config"), max_len=50)
    if fts_config is not None:
        out["fts_config"] = fts_config
    methods = _safe_lexical_db_methods(box_raw.get("methods"))
    if methods:
        out["methods"] = methods
    return out


def _safe_sparse_box_fields(box_raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    provider = _safe_str(box_raw.get("provider"), max_len=80)
    if provider is not None:
        out["provider"] = provider
    provider_status = _safe_provider_status(box_raw.get("provider_status"))
    if provider_status:
        out["provider_status"] = provider_status
    return out


def _safe_colbert_ann_box_fields(box_raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _add_safe_strings(out, box_raw, (("provider", 80), ("skipped_reason", 80)))
    _add_safe_ints(out, box_raw, ("docs_n", "max_docs"))
    return out


def _safe_channel_box(box_raw: Any, *, kind: str) -> dict[str, Any] | None:
    if not isinstance(box_raw, dict) or not box_raw:
        return None
    box: dict[str, Any] = {}
    _add_safe_bools(
        box,
        box_raw,
        ("enabled", "used", "filter_applied", "index_enabled", "trgm_enabled", "pg_trgm_available"),
    )

    candidates = _safe_int(box_raw.get("candidates"))
    if candidates is not None:
        box["candidates"] = candidates

    if kind == "lexical_db":
        box.update(_safe_lexical_db_box_fields(box_raw))

    if kind == "sparse":
        box.update(_safe_sparse_box_fields(box_raw))

    if kind == "colbert_ann":
        box.update(_safe_colbert_ann_box_fields(box_raw))

    return box or None


def _safe_float_bucket(raw: Any, keys: Iterable[str], *, lo: float, hi: float, digits: int) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, float] = {}
    for key in keys:
        value = _safe_float(raw.get(key), lo=lo, hi=hi, digits=digits)
        if value is not None:
            out[key] = value
    return out


def _safe_int_bucket(raw: Any, keys: Iterable[str]) -> dict[str, int]:
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, int] = {}
    _add_safe_ints(out, raw, keys)
    return out


def _safe_fusion_weights(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, float] = {}
    for key, value in sorted(raw.items(), key=lambda kv: str(kv[0]))[:10]:
        safe_key = _safe_str(key, max_len=40)
        safe_value = _safe_float(value, lo=-1e9, hi=1e9, digits=6)
        if safe_key is not None and safe_value is not None:
            out[safe_key] = safe_value
    return out


def _safe_rerank_channel(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, Any] = {}
    _add_safe_bools(out, raw, ("enabled", "used"))
    _add_safe_ints(out, raw, ("top_n_config", "candidates_n"))
    elapsed = _safe_float(raw.get("elapsed_sec"), lo=0.0, hi=10_000.0, digits=3)
    if elapsed is not None:
        out["elapsed_sec"] = elapsed
    _add_safe_strings(out, raw, (("provider", 120), ("model_used", 120), ("skip_reason", 120)))
    error = _safe_str(raw.get("error"), max_len=200)
    if error is not None:
        out["error"] = error
    return out


def _safe_numeric_bool_bucket(raw: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        key_str = str(key)
        if key_str not in allowed:
            continue
        converted = _safe_bucket_value(key_str, value)
        if converted is not None:
            cleaned[key_str] = converted
    return dict(sorted(cleaned.items(), key=lambda kv: kv[0]))


def _safe_bucket_value(key: str, value: Any) -> bool | int | None:
    if isinstance(value, bool):
        return value
    bool_value = _to_bool(value)
    if bool_value is not None and key.endswith("_enabled"):
        return bool_value
    int_value = _safe_int(value)
    return int_value if int_value is not None else None


def _safe_router_layer_row(item: Any, *, level: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    row: dict[str, Any] = {}
    decision = _safe_str(item.get("decision"), max_len=40)
    if decision is not None:
        row["decision"] = decision
    used = _to_bool(item.get("used"))
    if used is not None:
        row["used"] = used
    reason_codes = _bounded_safe_strings(item.get("reason_codes"), max_items=8, max_len=40)
    if reason_codes:
        row["reason_codes"] = reason_codes
    if level == "entity":
        partition_keys = _bounded_safe_strings(item.get("partition_keys"), max_items=8, max_len=120)
        if partition_keys:
            row["partition_keys"] = partition_keys
    return row


def _safe_scope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    tenant_present = bool(str(raw.get("tenant_id") or "").strip())
    dataset_present = bool(str(raw.get("dataset_id") or "").strip())
    scope: dict[str, Any] = {
        "account_id_present": _to_bool(raw.get("account_id_present")),
        "document_ids_count": _to_int(raw.get("document_ids_count")),
        "kind": (str(raw.get("kind")) if raw.get("kind") is not None else None),
        "tenant_id_present": tenant_present if tenant_present else None,
        "dataset_id_present": dataset_present if dataset_present else None,
    }
    return {k: v for k, v in scope.items() if v is not None}


def _safe_debug_diversity(raw: Any) -> dict[str, int]:
    return _safe_int_bucket(
        raw,
        (
            "max_chunks_per_doc",
            "max_chunks_per_page",
            "min_distinct_docs",
            "pre_unique_docs",
            "post_unique_docs",
            "pre_unique_pages",
            "post_unique_pages",
            "moved_out",
            "moved_in",
        ),
    )


def _safe_retriever_channels(ch_raw: Any) -> dict[str, Any] | None:
    """
    Sanitize HybridRetriever per-call channel metrics for UI exposure.

    We keep only low-cardinality counters/booleans/settings; no ids or text evidence.
    """
    if not isinstance(ch_raw, dict) or not ch_raw:
        return None

    out_ch: dict[str, Any] = {}

    _add_safe_strings(out_ch, ch_raw, (("retrieval_mode", 80), ("fusion_strategy", 80), ("vector_backend", 80)))
    _add_safe_ints(out_ch, ch_raw, ("rrf_k", "merged_pre_dedup", "merged_post_dedup", "merged_post_rerank", "returned_top_k"))

    timing = _safe_float_bucket(ch_raw.get("timing"), ("vector_ms", "colbert_ms", "bm25_ms", "fusion_ms"), lo=0.0, hi=1_000_000.0, digits=2)
    if timing:
        out_ch["timing"] = timing

    counts = _safe_int_bucket(ch_raw.get("counts"), ("vector_candidates", "colbert_candidates", "bm25_candidates", "sparse_candidates"))
    if counts:
        out_ch["counts"] = counts

    fusion_weights = _safe_fusion_weights(ch_raw.get("fusion_weights"))
    if fusion_weights:
        out_ch["fusion_weights"] = fusion_weights

    for key in ("vector", "colbert_ann", "bm25", "lexical_db", "sparse"):
        box = _safe_channel_box(ch_raw.get(key), kind=key)
        if box:
            out_ch[key] = box

    rerank = _safe_rerank_channel(ch_raw.get("rerank"))
    if rerank:
        out_ch["rerank"] = rerank

    # Numeric/bool-only buckets.
    for bucket_key, allowed in (
        ("attribution", {"vector", "bm25", "lexical_db", "multi", "sparse"}),
        (
            "diversity",
            {
                "before",
                "after",
                "dropped",
                "moved_out",
                "moved_in",
                "pre_unique_docs",
                "post_unique_docs",
                "pre_unique_pages",
                "post_unique_pages",
            },
        ),
        (
            "dedup",
            {"near_dedup_enabled", "near_dedup_dropped", "near_dedup_hamming_threshold", "near_dedup_max_compare"},
        ),
        ("cache", {"hit", "store_ok"}),
    ):
        cleaned = _safe_numeric_bool_bucket(ch_raw.get(bucket_key), allowed)
        if cleaned:
            out_ch[bucket_key] = cleaned

    return out_ch or None


def _safe_router_layers(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    schema = str(raw.get("schema") or "").strip()
    if schema != "mimirq.router_layers.v1":
        return None
    out: dict[str, Any] = {"schema": "mimirq.router_layers.v1"}
    for level in ("entity", "intent", "composite"):
        row = _safe_router_layer_row(raw.get(level), level=level)
        if row:
            out[level] = row
    return out if len(out) > 1 else None


def _safe_retriever_debug(raw: Any) -> dict[str, Any] | None:
    """
    Sanitize retriever-side debug metrics for UI exposure.

    Rules:
    - Keep counters/booleans only.
    - Strip tenant/dataset identifiers (present-ness is kept as a boolean).
    - Keep shapes stable and small.
    """
    if not isinstance(raw, dict):
        return None

    out: dict[str, Any] = {}

    for key in (
        "requested_k",
        "search_k",
        "overfetch_multiplier",
        "overfetch_cap_k",
        "milvus_expr_max_doc_ids",
        "hybrid_results",
        "neighbors_delta",
        "parent_child_merge_delta",
        "final_results",
        "final_docs",
    ):
        if key in raw:
            out[key] = _to_int(raw.get(key))

    _add_safe_bools(out, raw, ("overfetch_enabled", "milvus_doc_id_pushdown_skipped"))

    scope = _safe_scope(raw.get("scope"))
    if scope:
        out["scope"] = scope

    for key in ("enrich_pass1", "enrich_pass2"):
        stats = _safe_enrich_stats(raw.get(key))
        if stats:
            out[key] = stats

    diversity = _safe_debug_diversity(raw.get("diversity"))
    if diversity:
        out["diversity"] = diversity

    channels = _safe_retriever_channels(raw.get("channels"))
    if channels:
        out["channels"] = channels

    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def _tail_start(path: Path, *, max_bytes: int) -> tuple[int, int] | None:
    try:
        size = int(path.stat().st_size)
    except Exception:
        return None
    return max(0, size - max(1, int(max_bytes or 0))), size


def _read_tail_bytes(path: Path, *, start: int) -> bytes | None:
    try:
        with path.open("rb") as file:
            if start:
                file.seek(start)
            return file.read()
    except Exception:
        return None


def _drop_partial_first_line(raw: bytes, *, truncated: bool) -> bytes:
    if not truncated:
        return raw
    newline_index = raw.find(b"\n")
    return raw[newline_index + 1 :] if newline_index >= 0 else raw


def _decode_jsonl_tail(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _parse_jsonl_dicts(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = (line or "").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _read_jsonl_tail(path: Path, *, max_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    """
    Return: (records, truncated)
    `truncated=true` means we did not read the entire file, so results might be incomplete.
    """
    tail_bounds = _tail_start(path, max_bytes=max_bytes)
    if tail_bounds is None:
        return [], False

    start, _size = tail_bounds
    truncated = start > 0
    raw = _read_tail_bytes(path, start=start)
    if raw is None:
        return [], truncated

    text = _decode_jsonl_tail(_drop_partial_first_line(raw, truncated=truncated))
    if text is None:
        return [], truncated
    return _parse_jsonl_dicts(text), truncated


_SAFE_CITATION_FIELDS = {
    "chunk_id",
    "document_id",
    "chunk_index",
    "page_number",
    "start_char",
    "end_char",
    "retrieval_role",
    "neighbor_of",
    "doc_pipeline_key",
    "pipeline_hash",
    "relevance_score",
    "vector_score",
    "bm25_score",
    "lexical_score",
    "sparse_score",
    "colbert_score",
    "keyword_score",
    "kg_path",
    "kg_path_provenance",
    "rerank_score",
    "retrieval_score",
    "reranker_provider",
    "rerank_elapsed_sec",
    "rerank_model_used",
    "retrieval_mode",
    "vector_backend",
    "retrieval_elapsed_sec",
    "hit_type",
    "has_image",
}


def _safe_kg_path(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for step in raw:
        if not isinstance(step, dict):
            continue
        ent_id = str(step.get("entity_id") or "").strip()
        if not ent_id:
            continue
        typ = str(step.get("type") or "").strip()
        entry: dict[str, Any] = {"entity_id": ent_id}
        if typ:
            entry["type"] = typ[:100]
        out.append(entry)
        if len(out) >= 6:
            break
    return out or None


def _safe_prefixed_str(raw: Any, *, max_len: int) -> str | None:
    value = str(raw).strip() if raw is not None else ""
    return value[:max_len] if value else None


def _copy_safe_str_fields(out: dict[str, Any], raw: dict[str, Any], keys: Iterable[str], *, max_len: int) -> None:
    for key in keys:
        value = _safe_prefixed_str(raw.get(key), max_len=max_len)
        if value:
            out[key] = value


def _safe_kg_provenance_node(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    node: dict[str, Any] = {}
    kind = _safe_prefixed_str(raw.get("kind"), max_len=30)
    if kind:
        node["kind"] = kind
    _copy_safe_str_fields(node, raw, ("entity_id", "type", "event_id", "document_id", "chunk_id"), max_len=200)
    return node


def _safe_kg_provenance_edge(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    edge: dict[str, Any] = {}
    kind = _safe_prefixed_str(raw.get("kind"), max_len=30)
    if kind:
        edge["kind"] = kind
    _copy_safe_str_fields(
        edge,
        raw,
        (
            "entity_id",
            "event_id",
            "document_id",
            "chunk_id",
            "relation_id",
            "predicate",
            "confidence_bucket",
            "evidence_source",
        ),
        max_len=200,
    )
    return edge


def _safe_kg_provenance_entries(raw: Any, *, item_builder: Any, max_items: int = 10) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        safe_item = item_builder(item)
        if safe_item:
            out.append(safe_item)
        if len(out) >= max_items:
            break
    return out


def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    """
    Sanitize a shortest-path provenance payload for UI exposure.

    Rules:
    - Keep identifiers + small, low-cardinality fields only.
    - Drop any text evidence (quotes, entity names, etc).
    - Bound list sizes.
    """
    if not isinstance(raw, dict) or not raw:
        return None

    out: dict[str, Any] = {}
    schema = str(raw.get("schema") or "").strip()
    if schema:
        out["schema"] = schema[:80]
    kind = str(raw.get("kind") or "").strip()
    if kind:
        out["kind"] = kind[:50]
    try:
        if raw.get("hops") is not None:
            out["hops"] = int(raw.get("hops") or 0)
    except Exception:
        pass

    nodes = _safe_kg_provenance_entries(raw.get("nodes"), item_builder=_safe_kg_provenance_node)
    if nodes:
        out["nodes"] = nodes

    edges = _safe_kg_provenance_entries(raw.get("edges"), item_builder=_safe_kg_provenance_edge)
    if edges:
        out["edges"] = edges

    return out or None


def _safe_citation_payload(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: raw.get(key) for key in _SAFE_CITATION_FIELDS if key in raw}


def _build_safe_citation(safe: dict[str, Any]) -> RagTraceCitation:
    return RagTraceCitation(
        document_id=str(safe.get("document_id")) if safe.get("document_id") is not None else None,
        chunk_id=str(safe.get("chunk_id")) if safe.get("chunk_id") is not None else None,
        chunk_index=_to_int(safe.get("chunk_index")),
        page_number=_to_int(safe.get("page_number")),
        start_char=_to_int(safe.get("start_char")),
        end_char=_to_int(safe.get("end_char")),
        retrieval_role=(str(safe.get("retrieval_role")) if safe.get("retrieval_role") is not None else None),
        neighbor_of=(str(safe.get("neighbor_of")) if safe.get("neighbor_of") is not None else None),
        doc_pipeline_key=(str(safe.get("doc_pipeline_key")) if safe.get("doc_pipeline_key") is not None else None),
        pipeline_hash=(str(safe.get("pipeline_hash")) if safe.get("pipeline_hash") is not None else None),
        relevance_score=_to_float(safe.get("relevance_score")),
        vector_score=_to_float(safe.get("vector_score")),
        bm25_score=_to_float(safe.get("bm25_score")),
        lexical_score=_to_float(safe.get("lexical_score")),
        sparse_score=_to_float(safe.get("sparse_score")),
        colbert_score=_to_float(safe.get("colbert_score")),
        keyword_score=_to_float(safe.get("keyword_score")),
        kg_path=_safe_kg_path(safe.get("kg_path")),
        kg_path_provenance=_safe_kg_path_provenance(safe.get("kg_path_provenance")),
        rerank_score=_to_float(safe.get("rerank_score")),
        retrieval_score=_to_float(safe.get("retrieval_score")),
        reranker_provider=(str(safe.get("reranker_provider")) if safe.get("reranker_provider") is not None else None),
        rerank_elapsed_sec=_to_float(safe.get("rerank_elapsed_sec")),
        rerank_model_used=(str(safe.get("rerank_model_used")) if safe.get("rerank_model_used") is not None else None),
        retrieval_mode=(str(safe.get("retrieval_mode")) if safe.get("retrieval_mode") is not None else None),
        vector_backend=(str(safe.get("vector_backend")) if safe.get("vector_backend") is not None else None),
        retrieval_elapsed_sec=_to_float(safe.get("retrieval_elapsed_sec")),
        hit_type=(str(safe.get("hit_type")) if safe.get("hit_type") is not None else None),
        has_image=bool(safe.get("has_image") or False),
    )


def _safe_citations(raw: Any) -> list[RagTraceCitation]:
    if not isinstance(raw, list):
        return []
    out: list[RagTraceCitation] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        out.append(_build_safe_citation(_safe_citation_payload(c)))
    return out


def _max_float(values: Iterable[float | None]) -> float | None:
    best: float | None = None
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        if best is None or fv > best:
            best = fv
    return best


def _safe_retrieval_per_query(raw: Any) -> list[RagTraceRetrievalQuery]:
    if not isinstance(raw, list):
        return []
    out: list[RagTraceRetrievalQuery] = []
    for query in raw:
        if not isinstance(query, dict):
            continue
        out.append(
            RagTraceRetrievalQuery(
                kind=(str(query.get("kind")) if query.get("kind") is not None else None),
                query_chars=_to_int(query.get("query_chars")),
                elapsed_sec=_to_float(query.get("elapsed_sec")),
                ok=_to_bool(query.get("ok")),
                retriever_debug=_safe_retriever_debug(query.get("retriever_debug")),
            )
        )
    return out


def _retrieval_elapsed(raw_retrieval: dict[str, Any], citations: list[RagTraceCitation], per_query: list[RagTraceRetrievalQuery]) -> float | None:
    elapsed = _to_float(raw_retrieval.get("elapsed_sec"))
    if elapsed is not None:
        return elapsed
    elapsed = _max_float(citation.retrieval_elapsed_sec for citation in citations)
    if elapsed is not None:
        return elapsed
    return _max_float(query.elapsed_sec for query in per_query)


def _first_rerank_model_used(citations: list[RagTraceCitation]) -> str | None:
    for citation in citations:
        if citation.rerank_model_used:
            return citation.rerank_model_used
    return None


def _safe_retrieval_errors(raw: Any) -> list[str]:
    return [str(error) for error in raw if error is not None] if isinstance(raw, list) else []


def _retrieval_config_hash(raw: Any) -> str | None:
    return (str(raw).strip() if raw is not None else None) or None


def _build_trace_steps(
    *,
    retrieval: RagTraceRetrieval,
    rerank: RagTraceRerank,
    citations_count: int,
    distinct_docs: int,
) -> list[RagTraceStep]:
    steps: list[RagTraceStep] = [
        RagTraceStep(
            key="retrieve",
            label="Retrieve",
            elapsed_sec=retrieval.elapsed_sec,
            meta={
                "mode": retrieval.mode,
                "query_count": retrieval.query_count,
                "errors": len(retrieval.errors or []),
            },
        ),
    ]
    if rerank.enabled or rerank.elapsed_sec is not None:
        steps.append(
            RagTraceStep(
                key="rerank",
                label="Rerank",
                elapsed_sec=rerank.elapsed_sec,
                meta={"provider": rerank.provider, "top_n": rerank.top_n},
            )
        )
    steps.append(
        RagTraceStep(
            key="citations",
            label="Citations",
            elapsed_sec=None,
            meta={"count": citations_count, "distinct_documents": distinct_docs},
        )
    )
    return steps


def _disabled_trace_response(*, path: str, window_minutes: int) -> RagTraceListResponse:
    return RagTraceListResponse(
        enabled=False,
        path=path,
        window_minutes=window_minutes,
        truncated=False,
        returned=0,
        items=[],
    )


def _matches_trace_record(record: dict[str, Any], *, tenant_key: str, conversation_key: str, cutoff_ms: int) -> bool:
    if str(record.get("event") or "") != "rag_trace":
        return False
    if str(record.get("tenant_id") or "") != tenant_key:
        return False
    if str(record.get("conversation_id") or "") != conversation_key:
        return False
    ts_ms = _to_int(record.get("ts_ms")) or 0
    return not (ts_ms and ts_ms < cutoff_ms)


def _filter_trace_records(
    raw_records: list[dict[str, Any]],
    *,
    tenant_key: str,
    conversation_key: str,
    cutoff_ms: int,
    limit: int,
) -> list[dict[str, Any]]:
    matches = [
        record
        for record in raw_records
        if _matches_trace_record(record, tenant_key=tenant_key, conversation_key=conversation_key, cutoff_ms=cutoff_ms)
    ]
    matches.sort(key=lambda record: _to_int(record.get("ts_ms")) or 0, reverse=True)
    return matches[:limit]


def _normalize_trace_items(records: list[dict[str, Any]]) -> list[RagTrace]:
    items: list[RagTrace] = []
    for record in records:
        try:
            items.append(normalize_rag_trace_record(record))
        except Exception:
            continue
    return items


def normalize_rag_trace_record(record: dict[str, Any]) -> RagTrace:
    ts_ms = _to_int(record.get("ts_ms")) or 0
    request_id = record.get("request_id")
    conversation_id = record.get("conversation_id")

    raw_retrieval = record.get("retrieval") if isinstance(record.get("retrieval"), dict) else {}
    raw_citations = record.get("citations")

    citations = _safe_citations(raw_citations)
    citations_count = len(citations)

    retrieval_per_query = _safe_retrieval_per_query(raw_retrieval.get("per_query"))
    retrieval_elapsed_sec = _retrieval_elapsed(raw_retrieval, citations, retrieval_per_query)

    rerank_elapsed_sec = _max_float(c.rerank_elapsed_sec for c in citations)

    enable_reranker = _to_bool(raw_retrieval.get("enable_reranker"))
    reranker_provider = raw_retrieval.get("reranker_provider")
    reranker_top_n = _to_int(raw_retrieval.get("reranker_top_n"))
    retrieval_config_hash = _retrieval_config_hash(raw_retrieval.get("retrieval_config_hash"))
    rerank_model_used = _first_rerank_model_used(citations)

    retrieval = RagTraceRetrieval(
        mode=(str(raw_retrieval.get("mode")) if raw_retrieval.get("mode") is not None else None),
        requested_mode=(str(raw_retrieval.get("requested_mode")) if raw_retrieval.get("requested_mode") is not None else None),
        auto_routed=_to_bool(raw_retrieval.get("auto_routed")),
        router_layers=_safe_router_layers(raw_retrieval.get("router_layers") or record.get("router_layers")),
        retrieval_config_hash=retrieval_config_hash,
        top_k=_to_int(raw_retrieval.get("top_k")),
        query_parallelism=_to_int(raw_retrieval.get("query_parallelism")),
        query_count=_to_int(raw_retrieval.get("query_count")),
        per_query=retrieval_per_query,
        errors=_safe_retrieval_errors(raw_retrieval.get("errors")),
        enable_reranker=enable_reranker,
        reranker_provider=(str(reranker_provider) if reranker_provider is not None else None),
        reranker_top_n=reranker_top_n,
        elapsed_sec=retrieval_elapsed_sec,
    )

    rerank = RagTraceRerank(
        enabled=bool(enable_reranker or False),
        provider=(str(reranker_provider) if reranker_provider is not None else None),
        top_n=reranker_top_n,
        elapsed_sec=rerank_elapsed_sec,
        model_used=rerank_model_used,
    )

    distinct_docs = len({c.document_id for c in citations if c.document_id})
    steps = _build_trace_steps(
        retrieval=retrieval,
        rerank=rerank,
        citations_count=citations_count,
        distinct_docs=distinct_docs,
    )

    return RagTrace(
        ts_ms=ts_ms,
        request_id=(str(request_id) if request_id is not None else None),
        conversation_id=(str(conversation_id) if conversation_id is not None else None),
        retrieval=retrieval,
        rerank=rerank,
        citations=citations,
        citations_count=citations_count,
        steps=steps,
    )


def list_rag_traces(
    *,
    tenant_id: str,
    conversation_id: str,
    limit: int = 20,
    window_minutes: int = 60,
    max_bytes: int = 5_000_000,
) -> RagTraceListResponse:
    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
    path = Path(path_str)

    window_minutes = max(1, int(window_minutes or 0))
    cutoff_ms = int(time.time() * 1000) - (window_minutes * 60 * 1000)
    limit = max(1, min(int(limit or 0), 200))

    if not enabled:
        return _disabled_trace_response(path=path_str, window_minutes=window_minutes)

    raw_records, truncated_by_tail = _read_jsonl_tail(path, max_bytes=int(max_bytes or 0))

    matches = _filter_trace_records(
        raw_records,
        tenant_key=str(tenant_id),
        conversation_key=str(conversation_id),
        cutoff_ms=cutoff_ms,
        limit=limit,
    )
    items = _normalize_trace_items(matches)

    return RagTraceListResponse(
        enabled=True,
        path=path_str,
        window_minutes=window_minutes,
        truncated=bool(truncated_by_tail),
        returned=len(items),
        items=items,
    )

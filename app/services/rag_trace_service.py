"""
RAG trace reader (from metrics JSONL) for History/Graph visualization.

We intentionally do *not* return raw question/query/chunk text, even when
METRICS_LOG_INCLUDE_TEXT=true, because this endpoint is meant for UI tooling
and should stay PII-safe by construction.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

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


def _to_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _to_bool(v: Any) -> Optional[bool]:
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


def _safe_enrich_stats(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    for k in _SAFE_ENRICH_STATS_KEYS:
        if k not in raw:
            continue
        if k == "metadata_filter":
            mf_raw = raw.get(k)
            if not isinstance(mf_raw, dict):
                continue
            keys_count = _to_int(mf_raw.get("keys_count"))
            keys_sample_raw = mf_raw.get("keys_sample")
            keys_sample: list[str] = []
            if isinstance(keys_sample_raw, list):
                for x in keys_sample_raw:
                    if isinstance(x, str) and x.strip():
                        keys_sample.append(x.strip())
                    if len(keys_sample) >= 10:
                        break
            ops_raw = mf_raw.get("ops")
            ops: dict[str, int] = {}
            if isinstance(ops_raw, dict):
                for ok, ov in ops_raw.items():
                    if not isinstance(ok, str) or not ok.startswith("$"):
                        continue
                    val = _to_int(ov)
                    if val is None:
                        continue
                    ops[ok] = int(val)
                    if len(ops) >= 30:
                        break
                ops = dict(sorted(ops.items(), key=lambda x: x[0]))
            mf = {
                "keys_count": keys_count,
                "keys_sample": keys_sample,
                "ops": ops,
            }
            mf = {k3: v3 for k3, v3 in mf.items() if v3 not in (None, [], {})}
            if mf:
                out[k] = mf
            continue
        if k == "exception":
            s = (str(raw.get(k) or "")).strip()
            out[k] = s[:200] if s else None
            continue
        out[k] = _to_int(raw.get(k))
    # Drop empty dicts to keep payload small.
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


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

    for k in (
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
        if k in raw:
            out[k] = _to_int(raw.get(k))

    for k in ("overfetch_enabled", "milvus_doc_id_pushdown_skipped"):
        if k in raw:
            out[k] = _to_bool(raw.get(k))

    scope_raw = raw.get("scope")
    if isinstance(scope_raw, dict):
        tenant_present = bool(str(scope_raw.get("tenant_id") or "").strip())
        dataset_present = bool(str(scope_raw.get("dataset_id") or "").strip())
        scope: dict[str, Any] = {
            "account_id_present": _to_bool(scope_raw.get("account_id_present")),
            "document_ids_count": _to_int(scope_raw.get("document_ids_count")),
            "kind": (str(scope_raw.get("kind")) if scope_raw.get("kind") is not None else None),
            "tenant_id_present": tenant_present if tenant_present else None,
            "dataset_id_present": dataset_present if dataset_present else None,
        }
        scope = {k: v for k, v in scope.items() if v is not None}
        if scope:
            out["scope"] = scope

    for key in ("enrich_pass1", "enrich_pass2"):
        stats = _safe_enrich_stats(raw.get(key))
        if stats:
            out[key] = stats

    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def _read_jsonl_tail(path: Path, *, max_bytes: int) -> tuple[list[dict[str, Any]], bool]:
    """
    Return: (records, truncated)
    `truncated=true` means we did not read the entire file, so results might be incomplete.
    """
    max_bytes = max(1, int(max_bytes or 0))
    try:
        st = path.stat()
        size = int(st.st_size)
    except Exception:
        return [], False

    start = max(0, size - max_bytes)
    truncated = start > 0

    try:
        with path.open("rb") as f:
            if start:
                f.seek(start)
            raw = f.read()
    except Exception:
        return [], truncated

    if start:
        # Drop partial first line when reading from the middle.
        nl = raw.find(b"\n")
        if nl >= 0:
            raw = raw[nl + 1 :]

    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return [], truncated

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
    return records, truncated


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

    nodes_raw = raw.get("nodes")
    if isinstance(nodes_raw, list) and nodes_raw:
        nodes: list[dict[str, Any]] = []
        for n in nodes_raw:
            if not isinstance(n, dict):
                continue
            node: dict[str, Any] = {}
            k = str(n.get("kind") or "").strip()
            if k:
                node["kind"] = k[:30]
            for key in ("entity_id", "type", "event_id", "document_id", "chunk_id"):
                v = n.get(key)
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                node[key] = s[:200]
            if node:
                nodes.append(node)
            if len(nodes) >= 10:
                break
        if nodes:
            out["nodes"] = nodes

    edges_raw = raw.get("edges")
    if isinstance(edges_raw, list) and edges_raw:
        edges: list[dict[str, Any]] = []
        for e in edges_raw:
            if not isinstance(e, dict):
                continue
            edge: dict[str, Any] = {}
            k = str(e.get("kind") or "").strip()
            if k:
                edge["kind"] = k[:30]
            for key in (
                "entity_id",
                "event_id",
                "document_id",
                "chunk_id",
                "relation_id",
                "predicate",
                "confidence_bucket",
                "evidence_source",
            ):
                v = e.get(key)
                if v is None:
                    continue
                s = str(v).strip()
                if not s:
                    continue
                edge[key] = s[:200]
            if edge:
                edges.append(edge)
            if len(edges) >= 10:
                break
        if edges:
            out["edges"] = edges

    return out or None


def _safe_citations(raw: Any) -> list[RagTraceCitation]:
    if not isinstance(raw, list):
        return []
    out: list[RagTraceCitation] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        safe = {k: c.get(k) for k in _SAFE_CITATION_FIELDS if k in c}
        out.append(
            RagTraceCitation(
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
        )
    return out


def _max_float(values: Iterable[Optional[float]]) -> Optional[float]:
    best: Optional[float] = None
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


def normalize_rag_trace_record(record: Dict[str, Any]) -> RagTrace:
    ts_ms = _to_int(record.get("ts_ms")) or 0
    request_id = record.get("request_id")
    conversation_id = record.get("conversation_id")

    raw_retrieval = record.get("retrieval") if isinstance(record.get("retrieval"), dict) else {}
    raw_citations = record.get("citations")

    citations = _safe_citations(raw_citations)
    citations_count = len(citations)

    retrieval_per_query: list[RagTraceRetrievalQuery] = []
    per_query_raw = raw_retrieval.get("per_query")
    if isinstance(per_query_raw, list):
        for q in per_query_raw:
            if not isinstance(q, dict):
                continue
            retrieval_per_query.append(
                RagTraceRetrievalQuery(
                    kind=(str(q.get("kind")) if q.get("kind") is not None else None),
                    query_chars=_to_int(q.get("query_chars")),
                    elapsed_sec=_to_float(q.get("elapsed_sec")),
                    ok=_to_bool(q.get("ok")),
                    retriever_debug=_safe_retriever_debug(q.get("retriever_debug")),
                )
            )

    retrieval_elapsed_sec = _to_float(raw_retrieval.get("elapsed_sec"))
    if retrieval_elapsed_sec is None:
        retrieval_elapsed_sec = _max_float(c.retrieval_elapsed_sec for c in citations)
    if retrieval_elapsed_sec is None:
        retrieval_elapsed_sec = _max_float(q.elapsed_sec for q in retrieval_per_query)

    rerank_elapsed_sec = _max_float(c.rerank_elapsed_sec for c in citations)

    enable_reranker = _to_bool(raw_retrieval.get("enable_reranker"))
    reranker_provider = raw_retrieval.get("reranker_provider")
    reranker_top_n = _to_int(raw_retrieval.get("reranker_top_n"))
    retrieval_config_hash = raw_retrieval.get("retrieval_config_hash")
    retrieval_config_hash = (str(retrieval_config_hash).strip() if retrieval_config_hash is not None else None) or None

    rerank_model_used = None
    for c in citations:
        if c.rerank_model_used:
            rerank_model_used = c.rerank_model_used
            break

    retrieval = RagTraceRetrieval(
        mode=(str(raw_retrieval.get("mode")) if raw_retrieval.get("mode") is not None else None),
        requested_mode=(str(raw_retrieval.get("requested_mode")) if raw_retrieval.get("requested_mode") is not None else None),
        auto_routed=_to_bool(raw_retrieval.get("auto_routed")),
        retrieval_config_hash=retrieval_config_hash,
        top_k=_to_int(raw_retrieval.get("top_k")),
        query_parallelism=_to_int(raw_retrieval.get("query_parallelism")),
        query_count=_to_int(raw_retrieval.get("query_count")),
        per_query=retrieval_per_query,
        errors=[str(e) for e in (raw_retrieval.get("errors") or []) if e is not None] if isinstance(raw_retrieval.get("errors"), list) else [],
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
    steps: list[RagTraceStep] = [
        RagTraceStep(
            key="retrieve",
            label="Retrieve",
            elapsed_sec=retrieval_elapsed_sec,
            meta={
                "mode": retrieval.mode,
                "query_count": retrieval.query_count,
                "errors": len(retrieval.errors or []),
            },
        ),
    ]
    if rerank.enabled or rerank_elapsed_sec is not None:
        steps.append(
            RagTraceStep(
                key="rerank",
                label="Rerank",
                elapsed_sec=rerank_elapsed_sec,
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
        return RagTraceListResponse(
            enabled=False,
            path=path_str,
            window_minutes=window_minutes,
            truncated=False,
            returned=0,
            items=[],
        )

    raw_records, truncated_by_tail = _read_jsonl_tail(path, max_bytes=int(max_bytes or 0))

    tenant_key = str(tenant_id)
    conv_key = str(conversation_id)

    matches: list[dict[str, Any]] = []
    for r in raw_records:
        if str(r.get("event") or "") != "rag_trace":
            continue
        if str(r.get("tenant_id") or "") != tenant_key:
            continue
        if str(r.get("conversation_id") or "") != conv_key:
            continue
        ts_ms = _to_int(r.get("ts_ms")) or 0
        if ts_ms and ts_ms < cutoff_ms:
            continue
        matches.append(r)

    # Prefer latest traces first.
    matches.sort(key=lambda x: _to_int(x.get("ts_ms")) or 0, reverse=True)
    matches = matches[:limit]

    items: list[RagTrace] = []
    for r in matches:
        try:
            items.append(normalize_rag_trace_record(r))
        except Exception:
            # Best-effort: keep the endpoint usable even with a few bad lines.
            continue

    return RagTraceListResponse(
        enabled=True,
        path=path_str,
        window_minutes=window_minutes,
        truncated=bool(truncated_by_tail),
        returned=len(items),
        items=items,
    )


from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

FUSION_WEIGHT_OBSERVABILITY_SCHEMA = "mimirq.fusion_weight_observability.v1"
TENANT_FUSION_WEIGHTS_SCHEMA = "mimirq.tenant_fusion_weights.v1"
_CHANNELS = ("vector", "bm25", "lexical", "sparse")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _normalize_tenant_id(value: Any) -> str:
    return str(value or "").strip()


def _extract_trace_payload(row: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if str(row.get("event") or "").strip() == "rag_trace":
        return dict(row), "trace"
    if str(row.get("schema") or "").strip() == "mimirq.training_export_row.v1":
        snap = row.get("trace_snapshot")
        if isinstance(snap, dict):
            return dict(snap), "training_export"
    return None, ""


def _iter_filtered_traces(rows: Sequence[Mapping[str, Any]], *, tenant_id: str | None) -> list[tuple[dict[str, Any], Mapping[str, Any], str]]:
    out: list[tuple[dict[str, Any], Mapping[str, Any], str]] = []
    tenant_norm = _normalize_tenant_id(tenant_id)
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        trace, source = _extract_trace_payload(row)
        if not isinstance(trace, dict):
            continue
        trace_tenant = _normalize_tenant_id(trace.get("tenant_id") or row.get("tenant_id"))
        if tenant_norm and trace_tenant and trace_tenant != tenant_norm:
            continue
        out.append((trace, row, source))
    return out


def _extract_channels(trace: Mapping[str, Any]) -> dict[str, Any]:
    retrieval = trace.get("retrieval")
    if not isinstance(retrieval, Mapping):
        return {}
    per_query = retrieval.get("per_query")
    if isinstance(per_query, list):
        for item in per_query:
            if not isinstance(item, Mapping):
                continue
            dbg = item.get("retriever_debug")
            if not isinstance(dbg, Mapping):
                continue
            channels = dbg.get("channels")
            if isinstance(channels, Mapping):
                return dict(channels)
    channels = retrieval.get("channels")
    if isinstance(channels, Mapping):
        return dict(channels)
    return {}


def summarize_fusion_weight_observability(
    rows: Sequence[Mapping[str, Any]],
    *,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    filtered = _iter_filtered_traces(rows, tenant_id=tenant_id)

    strategy_hist = Counter()
    rrf_hist = Counter()
    channel_signal_coverage = Counter()
    weight_profiles = Counter()
    ltr_training_ready_rows = 0

    for trace, row, _source in filtered:
        channels = _extract_channels(trace)
        strategy = str(channels.get("fusion_strategy") or "").strip().lower()
        if strategy:
            strategy_hist[strategy] += 1
        rrf_k = channels.get("rrf_k")
        if rrf_k is not None:
            rrf_hist[str(int(_as_float(rrf_k, 0.0)))] += 1

        fusion_weights = channels.get("fusion_weights")
        if isinstance(fusion_weights, Mapping) and fusion_weights:
            profile = ",".join(
                f"{key}:{round(_as_float(fusion_weights.get(key)), 3):.3f}"
                for key in _CHANNELS
                if fusion_weights.get(key) is not None
            )
            if profile:
                weight_profiles[profile] += 1

        citations = trace.get("citations")
        if isinstance(citations, list):
            for citation in citations:
                if not isinstance(citation, Mapping):
                    continue
                for channel in _CHANNELS:
                    if _as_float(citation.get(f"{channel}_score"), 0.0) > 0.0:
                        channel_signal_coverage[channel] += 1

        if (
            str(row.get("schema") or "").strip() == "mimirq.training_export_row.v1"
            and isinstance(row.get("reference_sources"), list)
            and isinstance(trace.get("citations"), list)
            and row.get("reference_sources")
            and trace.get("citations")
        ):
            ltr_training_ready_rows += 1

    return {
        "schema": FUSION_WEIGHT_OBSERVABILITY_SCHEMA,
        "tenant_id": _normalize_tenant_id(tenant_id) or None,
        "summary": {
            "observed_rows": int(len(filtered)),
            "ltr_training_ready_rows": int(ltr_training_ready_rows),
            "fusion_strategy_histogram": dict(sorted(strategy_hist.items())),
            "rrf_k_histogram": dict(sorted(rrf_hist.items(), key=lambda item: int(item[0]))),
            "channel_signal_coverage": {key: int(channel_signal_coverage.get(key, 0)) for key in _CHANNELS},
            "observed_weight_profiles": dict(sorted(weight_profiles.items())),
        },
    }


def _reference_keyset(reference_sources: Any) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    if not isinstance(reference_sources, list):
        return out
    for item in reference_sources:
        if not isinstance(item, Mapping):
            continue
        doc_id = str(item.get("document_id") or "").strip()
        chunk_id = str(item.get("chunk_id") or "").strip()
        if doc_id or chunk_id:
            out.add((doc_id, chunk_id))
    return out


def _is_positive_citation(citation: Mapping[str, Any], refs: set[tuple[str, str]]) -> bool:
    doc_id = str(citation.get("document_id") or "").strip()
    chunk_id = str(citation.get("chunk_id") or "").strip()
    if (doc_id, chunk_id) in refs:
        return True
    if chunk_id and any(ref_chunk == chunk_id for _ref_doc, ref_chunk in refs):
        return True
    if doc_id and any(ref_doc == doc_id for ref_doc, _ref_chunk in refs):
        return True
    return False


def suggest_tenant_fusion_weights(
    rows: Sequence[Mapping[str, Any]],
    *,
    tenant_id: str | None = None,
    min_rows: int = 5,
) -> dict[str, Any]:
    filtered = _iter_filtered_traces(rows, tenant_id=tenant_id)

    positives = defaultdict(list)
    negatives = defaultdict(list)
    used_rows = 0

    for trace, row, source in filtered:
        if source != "training_export":
            continue
        refs = _reference_keyset(row.get("reference_sources"))
        citations = trace.get("citations")
        if not refs or not isinstance(citations, list) or not citations:
            continue
        used_rows += 1
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            target = positives if _is_positive_citation(citation, refs) else negatives
            for channel in _CHANNELS:
                score = _as_float(citation.get(f"{channel}_score"), 0.0)
                if score > 0.0:
                    target[channel].append(score)

    separation: dict[str, float] = {}
    for channel in _CHANNELS:
        pos_avg = sum(positives[channel]) / len(positives[channel]) if positives[channel] else 0.0
        neg_avg = sum(negatives[channel]) / len(negatives[channel]) if negatives[channel] else 0.0
        separation[channel] = max(0.0, pos_avg - neg_avg)

    total_sep = sum(separation.values())
    if used_rows < max(1, int(min_rows or 0)) or total_sep <= 0.0:
        weights = {"vector": 0.4, "bm25": 0.2, "lexical": 0.2, "sparse": 0.2}
        weight_source = "fallback_default"
    else:
        weights = {channel: round(separation[channel] / total_sep, 6) for channel in _CHANNELS}
        weight_source = "feedback_trace_snapshot"

    # Normalize defensively after rounding.
    total = sum(weights.values())
    if total > 0.0:
        weights = {channel: round(weights.get(channel, 0.0) / total, 6) for channel in _CHANNELS}
        total = sum(weights.values())
        if total > 0.0:
            weights = {channel: round(value / total, 6) for channel, value in weights.items()}

    return {
        "schema": TENANT_FUSION_WEIGHTS_SCHEMA,
        "tenant_id": _normalize_tenant_id(tenant_id) or None,
        "fusion_weights": weights,
        "summary": {
            "training_rows": int(used_rows),
            "weight_source": weight_source,
            "channel_positive_avg": {channel: round(sum(positives[channel]) / len(positives[channel]), 6) if positives[channel] else 0.0 for channel in _CHANNELS},
            "channel_negative_avg": {channel: round(sum(negatives[channel]) / len(negatives[channel]), 6) if negatives[channel] else 0.0 for channel in _CHANNELS},
            "channel_separation": {channel: round(separation[channel], 6) for channel in _CHANNELS},
        },
    }


__all__ = [
    "FUSION_WEIGHT_OBSERVABILITY_SCHEMA",
    "TENANT_FUSION_WEIGHTS_SCHEMA",
    "suggest_tenant_fusion_weights",
    "summarize_fusion_weight_observability",
]

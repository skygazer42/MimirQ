from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.rag.core.hashing import stable_json_hash

EVIDENCE_CAPSULE_SCHEMA_V1 = "mimirq.evidence_capsule.v1"


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _sanitize_citation(citation: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "citation_hash",
        "evidence_anchor_hash",
        "document_id",
        "chunk_id",
        "page_number",
        "chunk_index",
        "start_char",
        "end_char",
        "evidence_start_char",
        "evidence_end_char",
        "retrieval_role",
        "hit_type",
        "table_id",
        "sheet_index",
        "sheet_name",
        "row_source_table",
        "row_source_sync_token",
        "row_source_pk_hashes",
        "sql_generation_mode",
        "tag_schema_link_score",
        "tag_schema_link_strategy",
        "relevance_score",
        "retrieval_score",
        "vector_score",
        "bm25_score",
        "lexical_score",
        "sparse_score",
        "colbert_score",
        "rerank_score",
        "rerank_score_calibrated",
        "reranker_provider",
    ):
        if key not in citation:
            continue
        value = citation.get(key)
        if value is None:
            continue
        out[key] = value
    if "citation_hash" not in out:
        out["citation_hash"] = stable_json_hash(out, length=16)
    return out


def _capsule_payload_without_hash(
    *,
    query_for_retrieval: str,
    citations: list[dict[str, Any]],
    metrics: dict[str, Any],
    retrieval_trace: dict[str, Any] | None,
    query_debug: dict[str, Any] | None,
    request_context: dict[str, Any] | None,
) -> dict[str, Any]:
    sanitized_citations = [_sanitize_citation(c) for c in citations if isinstance(c, dict)]
    citation_hashes = [str(c.get("citation_hash") or "") for c in sanitized_citations if str(c.get("citation_hash") or "").strip()]
    must_recall = {
        "status": str(metrics.get("must_recall_status") or ""),
        "passed": _coerce_bool(metrics.get("must_recall_passed")),
        "enabled": _coerce_bool(metrics.get("must_recall_enabled")),
        "missing_source_keys": list(metrics.get("must_recall_missing_source_keys") or []),
        "required_anchor_fields": list(metrics.get("must_recall_required_anchor_fields") or []),
        "anchor_missing_counts": dict(metrics.get("must_recall_anchor_missing_counts") or {}),
        "fail_reasons": list(metrics.get("must_recall_fail_reasons") or []),
    }
    retrieval_contract = {
        "mode": str(metrics.get("retrieval_contract_mode") or ""),
        "policy": dict(metrics.get("retrieval_contract_policy") or {}),
        "hard_fallback_used": _coerce_bool(metrics.get("hard_fallback_used")),
        "secondary_pass_used": _coerce_bool(metrics.get("must_recall_second_pass_used")),
    }
    quality = {
        "parse_risk_level": str(metrics.get("parse_risk_level") or ""),
        "parse_risk_score": _coerce_float(metrics.get("parse_risk_score")),
        "parse_quality_alert": _coerce_bool(metrics.get("parse_quality_alert")),
        "parse_quality_gate_blocked": _coerce_bool(metrics.get("parse_quality_gate_blocked")),
    }
    retrieval_summary = {
        "retrieval_mode": str(metrics.get("retrieval_mode") or ""),
        "retrieval_elapsed_sec": _coerce_float(metrics.get("retrieval_elapsed_sec")),
        "retrieval_config_hash": str(metrics.get("retrieval_config_hash") or ""),
        "citations_count": int(len(sanitized_citations)),
        "top_relevance_score": _coerce_float(metrics.get("top_relevance_score")),
        "abstain_triggered": _coerce_bool(metrics.get("abstain_triggered")),
        "abstain_reason": str(metrics.get("abstain_reason") or ""),
    }
    return {
        "schema": EVIDENCE_CAPSULE_SCHEMA_V1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_for_retrieval": str(query_for_retrieval or ""),
        "request_context": dict(request_context or {}),
        "retrieval_summary": retrieval_summary,
        "must_recall": must_recall,
        "retrieval_contract": retrieval_contract,
        "quality": quality,
        "citations": sanitized_citations,
        "citation_hashes": citation_hashes,
        "retrieval_trace": retrieval_trace if isinstance(retrieval_trace, dict) else None,
        "query_debug": query_debug if isinstance(query_debug, dict) else None,
    }


def build_evidence_capsule(
    *,
    query_for_retrieval: str,
    citations: list[dict[str, Any]],
    metrics: dict[str, Any] | None,
    retrieval_trace: dict[str, Any] | None,
    query_debug: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _capsule_payload_without_hash(
        query_for_retrieval=query_for_retrieval,
        citations=[c for c in citations if isinstance(c, dict)],
        metrics=metrics if isinstance(metrics, dict) else {},
        retrieval_trace=retrieval_trace,
        query_debug=query_debug,
        request_context=request_context,
    )
    capsule_hash = stable_json_hash(payload, length=24)
    payload["capsule_hash"] = capsule_hash
    return payload


def validate_evidence_capsule(capsule: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(capsule, dict):
        return False, "capsule_not_object"
    if str(capsule.get("schema") or "") != EVIDENCE_CAPSULE_SCHEMA_V1:
        return False, "invalid_schema"
    if not str(capsule.get("capsule_hash") or "").strip():
        return False, "missing_capsule_hash"
    if not isinstance(capsule.get("citations"), list):
        return False, "citations_not_list"
    return True, "ok"


__all__ = [
    "EVIDENCE_CAPSULE_SCHEMA_V1",
    "build_evidence_capsule",
    "validate_evidence_capsule",
]

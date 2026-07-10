
from datetime import UTC, datetime
from typing import Any

from app.rag.core.hashing import stable_json_hash, stable_json_hmac
from app.rag.core.logging import get_logger

logger = get_logger(__name__)

EVIDENCE_CAPSULE_SCHEMA_V1 = "mimirq.evidence_capsule.v1"
EVIDENCE_CAPSULE_SIGNATURE_SCHEMA_V1 = "mimirq.evidence_capsule_signature.v1"


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
    if "evidence_anchor_hash" not in out:
        anchor_payload = {
            "document_id": out.get("document_id"),
            "chunk_id": out.get("chunk_id"),
            "page_number": out.get("page_number"),
            "chunk_index": out.get("chunk_index"),
            "start_char": out.get("start_char"),
            "end_char": out.get("end_char"),
            "table_id": out.get("table_id"),
            "row_source_table": out.get("row_source_table"),
            "row_source_sync_token": out.get("row_source_sync_token"),
            "row_source_pk_hashes": out.get("row_source_pk_hashes"),
        }
        out["evidence_anchor_hash"] = stable_json_hash(anchor_payload, length=16)
    if "citation_hash" not in out:
        payload = dict(out)
        payload.pop("citation_hash", None)
        out["citation_hash"] = stable_json_hash(payload, length=16)
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
        "generated_at": datetime.now(UTC).isoformat(),
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


def recompute_capsule_hash(capsule: dict[str, Any]) -> str:
    payload = dict(capsule or {})
    payload.pop("capsule_hash", None)
    payload.pop("signature", None)
    return stable_json_hash(payload, length=24)


def _signing_secret_from_settings() -> str:
    try:
        from app.core.config import settings  # noqa: WPS433

        return str(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_SECRET", "") or "").strip()
    except Exception:
        return ""


def sign_evidence_capsule(
    capsule: dict[str, Any],
    *,
    secret: str,
    key_id: str = "default",
) -> dict[str, Any] | None:
    sec = str(secret or "").strip()
    if not sec:
        return None
    kid = str(key_id or "default").strip() or "default"
    payload = dict(capsule or {})
    payload.pop("signature", None)
    value = stable_json_hmac(payload, secret=sec, length=48)
    if not value:
        return None
    return {
        "schema": EVIDENCE_CAPSULE_SIGNATURE_SCHEMA_V1,
        "alg": "hmac_sha256",
        "key_id": kid,
        "value": value,
    }


def verify_evidence_capsule_signature(
    capsule: dict[str, Any],
    *,
    secret: str | None = None,
) -> tuple[bool, str]:
    sig = capsule.get("signature")
    if not isinstance(sig, dict):
        return False, "signature_missing"
    if str(sig.get("schema") or "") != EVIDENCE_CAPSULE_SIGNATURE_SCHEMA_V1:
        return False, "invalid_signature_schema"
    if str(sig.get("alg") or "").strip().lower() != "hmac_sha256":
        return False, "unsupported_signature_alg"
    value = str(sig.get("value") or "").strip()
    if not value:
        return False, "signature_value_missing"

    sec = str(secret or "").strip() or _signing_secret_from_settings()
    if not sec:
        return False, "signature_secret_missing"

    payload = dict(capsule or {})
    payload.pop("signature", None)
    expected = stable_json_hmac(payload, secret=sec, length=len(value))
    if expected != value:
        return False, "signature_mismatch"
    return True, "ok"


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
    try:
        from app.core.config import settings  # noqa: WPS433

        if bool(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_ENABLED", False)):
            secret = str(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_SECRET", "") or "").strip()
            key_id = str(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_KEY_ID", "default") or "default").strip() or "default"
            sig = sign_evidence_capsule(payload, secret=secret, key_id=key_id)
            if isinstance(sig, dict):
                payload["signature"] = sig
    except Exception as exc:
        logger.debug("Ignoring evidence capsule signature attachment failure: %s", exc)
    return payload


def validate_evidence_capsule(
    capsule: dict[str, Any],
    *,
    strict: bool | None = None,
    verify_signature: bool | None = None,
) -> tuple[bool, str]:
    if not isinstance(capsule, dict):
        return False, "capsule_not_object"
    if str(capsule.get("schema") or "") != EVIDENCE_CAPSULE_SCHEMA_V1:
        return False, "invalid_schema"
    capsule_hash = str(capsule.get("capsule_hash") or "").strip()
    if not capsule_hash:
        return False, "missing_capsule_hash"
    citations = capsule.get("citations")
    if not isinstance(citations, list):
        return False, "citations_not_list"

    if strict is None or verify_signature is None:
        try:
            from app.core.config import settings  # noqa: WPS433

            if strict is None:
                strict = bool(getattr(settings, "EVIDENCE_CAPSULE_STRICT_VALIDATION_ENABLED", True))
            if verify_signature is None:
                verify_signature = bool(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_ENABLED", False))
        except Exception:
            if strict is None:
                strict = False
            if verify_signature is None:
                verify_signature = False

    if bool(strict):
        recomputed = recompute_capsule_hash(capsule)
        if recomputed != capsule_hash:
            return False, "capsule_hash_mismatch"

        actual_hashes: list[str] = []
        for row in citations:
            if not isinstance(row, dict):
                continue
            anchor_hash = str(row.get("evidence_anchor_hash") or "").strip()
            if not anchor_hash:
                return False, "missing_evidence_anchor_hash"
            actual = str(row.get("citation_hash") or "").strip()
            if not actual:
                return False, "missing_citation_hash"
            rec = dict(row)
            rec.pop("citation_hash", None)
            expected = stable_json_hash(rec, length=len(actual))
            if expected != actual:
                return False, "citation_hash_mismatch"
            actual_hashes.append(actual)

        declared_hashes = [str(v).strip() for v in (capsule.get("citation_hashes") or []) if str(v).strip()]
        if declared_hashes and declared_hashes != actual_hashes:
            return False, "citation_hashes_mismatch"

    if bool(verify_signature):
        sig_ok, sig_reason = verify_evidence_capsule_signature(capsule)
        if not sig_ok:
            return False, sig_reason

    return True, "ok"


__all__ = [
    "EVIDENCE_CAPSULE_SCHEMA_V1",
    "EVIDENCE_CAPSULE_SIGNATURE_SCHEMA_V1",
    "build_evidence_capsule",
    "recompute_capsule_hash",
    "sign_evidence_capsule",
    "verify_evidence_capsule_signature",
    "validate_evidence_capsule",
]

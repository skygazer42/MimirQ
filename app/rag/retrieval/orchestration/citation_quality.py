"""Citation coverage proxy, empty-retrieval diagnosis, and parse-quality risk summaries.

Split out of ``app.rag.retrieval.orchestrator`` (see
``app.rag.retrieval.orchestration``).
"""

from typing import Any

from langchain_core.documents import Document

from app.rag.retrieval.orchestration.common import _safe_int


def _citation_coverage_lists(citations: list[Any]) -> tuple[int, list[str], list[str], list[str]]:
    total = 0
    doc_ids: list[str] = []
    pipeline_keys: list[str] = []
    roles: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        total += 1
        document_id = str(citation.get("document_id") or "").strip()
        pipeline_key = str(citation.get("doc_pipeline_key") or citation.get("pipeline_hash") or "").strip()
        role = str(citation.get("retrieval_role") or "").strip().lower()
        if document_id:
            doc_ids.append(document_id)
        if pipeline_key:
            pipeline_keys.append(pipeline_key)
        if role:
            roles.append(role)
    return total, doc_ids, pipeline_keys, roles


def _top_doc_share(doc_ids: list[str]) -> float | None:
    if not doc_ids:
        return None
    from collections import Counter  # local import: keep module import-light

    counts = Counter(doc_ids)
    if not counts:
        return None
    return round(float(max(counts.values())) / float(len(doc_ids)), 3)


def _coverage_proxy_from_citations(citations: Any) -> dict[str, Any] | None:
    """
    Compute a lightweight, PII-safe coverage proxy from citations.

    This is intentionally *not* a semantic quality metric; it is used for:
    - quick diagnosis (e.g., "all citations come from 1 doc")
    - low-cost gating/alerts
    """
    if not isinstance(citations, list) or not citations:
        return None

    total, doc_ids, pipeline_keys, roles = _citation_coverage_lists(citations)
    if total <= 0:
        return None

    out: dict[str, Any] = {
        "citations_total": int(total),
        "distinct_documents": int(len(set(doc_ids)) if doc_ids else 0),
        "distinct_pipeline_keys": int(len(set(pipeline_keys)) if pipeline_keys else 0),
        "distinct_roles": int(len(set(roles)) if roles else 0),
        "top_doc_share": _top_doc_share(doc_ids),
    }
    return {k: v for k, v in out.items() if v is not None} or None


def _main_retrieval_per_query_item(retrieval_per_query: Any) -> dict[str, Any] | None:
    if not isinstance(retrieval_per_query, list):
        return None
    for item in retrieval_per_query:
        if isinstance(item, dict) and item.get("kind") == "main":
            return item
    return None


def _retriever_enrichment_debug(debug_payload: Any) -> dict[str, Any] | None:
    if not isinstance(debug_payload, dict):
        return None
    enrich = debug_payload.get("enrich_pass2")
    if not isinstance(enrich, dict):
        enrich = debug_payload.get("enrich_pass1")
    return enrich if isinstance(enrich, dict) else None


def _empty_retrieval_reason_counts(enrich: dict[str, Any]) -> tuple[dict[str, int], list[tuple[str, int]]]:
    signals: dict[str, int] = {}
    reason_counts: list[tuple[str, int]] = []
    for key, reason in (
        ("filtered_metadata_filter", "metadata_filter"),
        ("filtered_acl", "acl"),
        ("filtered_dataset", "dataset"),
        ("filtered_pipeline_version", "pipeline_version"),
        ("filtered_embedding_space", "embedding_space"),
        ("filtered_not_ready", "not_ready"),
        ("filtered_orphaned", "orphaned_vectors"),
    ):
        count = _safe_int(enrich.get(key))
        if count > 0:
            signals[key] = int(count)
            reason_counts.append((reason, int(count)))
    reason_counts.sort(key=lambda item: (-item[1], item[0]))
    return signals, reason_counts


def _build_empty_retrieval_diagnosis(enrich: dict[str, Any], signals: dict[str, int], reason_counts: list[tuple[str, int]]) -> dict[str, Any] | None:
    if not reason_counts:
        return None
    diag: dict[str, Any] = {
        "reasons": [reason for reason, _count in reason_counts],
        "signals": signals,
    }
    for key in ("input_results", "output_results"):
        if enrich.get(key) is not None:
            diag[key] = _safe_int(enrich.get(key))
    return {key: value for key, value in diag.items() if value is not None} or None


def _diagnose_empty_retrieval(retrieval_per_query: Any) -> dict[str, Any] | None:
    """
    Best-effort diagnosis for "no citations returned" cases.

    This is intentionally PII-safe: it only reports counters from retriever_debug.
    """
    if not isinstance(retrieval_per_query, list) or not retrieval_per_query:
        return None

    main = _main_retrieval_per_query_item(retrieval_per_query)
    if main is None:
        return None

    enrich = _retriever_enrichment_debug(main.get("retriever_debug"))
    if enrich is None:
        return None
    signals, reason_counts = _empty_retrieval_reason_counts(enrich)
    return _build_empty_retrieval_diagnosis(enrich, signals, reason_counts)


def _extract_parse_quality_score(meta: Any) -> float | None:
    if not isinstance(meta, dict):
        return None

    candidates = [
        meta.get("doc_parse_quality_score"),
        meta.get("parse_quality_score"),
    ]
    pq = meta.get("parse_quality")
    if isinstance(pq, dict):
        candidates.append(pq.get("score"))
    elif pq is not None:
        candidates.append(pq)

    for raw in candidates:
        try:
            if raw is None:
                continue
            score = float(raw)
            if score < 0.0:
                score = 0.0
            if score > 1.0:
                score = 1.0
            return float(score)
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def _parse_quality_recommendation(*, low_ratio: float, considered: int) -> str | None:
    if considered <= 0:
        return "no_parse_quality_metadata"
    if low_ratio >= 0.8:
        return "high_parse_risk_reparse_documents"
    if low_ratio >= 0.5:
        return "medium_parse_risk_prioritize_low_quality_docs"
    if low_ratio >= 0.2:
        return "monitor_parse_quality_tail"
    return "parse_quality_healthy"


def _parse_quality_low_sample(doc: Document, *, rank: int, score: float) -> dict[str, Any]:
    meta = doc.metadata if isinstance(getattr(doc, "metadata", None), dict) else {}
    return {
        "rank": int(rank),
        "chunk_id": str(getattr(doc, "id", None) or meta.get("chunk_id") or ""),
        "document_id": str(meta.get("document_id") or ""),
        "score": round(float(score), 3),
    }


def _parse_quality_risk_counters(docs: list[Document] | None, *, low_threshold: float) -> tuple[int, int, list[float], list[dict[str, Any]]]:
    considered = 0
    low_count = 0
    scores: list[float] = []
    low_samples: list[dict[str, Any]] = []
    for index, doc in enumerate(list(docs or [])[:50]):
        meta = doc.metadata if isinstance(getattr(doc, "metadata", None), dict) else {}
        score = _extract_parse_quality_score(meta)
        if score is None:
            continue
        considered += 1
        scores.append(float(score))
        if float(score) < float(low_threshold):
            low_count += 1
            if len(low_samples) < 5:
                low_samples.append(_parse_quality_low_sample(doc, rank=index + 1, score=score))
    return considered, low_count, scores, low_samples


def _summarize_parse_quality_risk(
    docs: list[Document] | None,
    *,
    low_threshold: float,
    alert_ratio: float,
) -> dict[str, Any]:
    considered, low_count, scores, low_samples = _parse_quality_risk_counters(docs, low_threshold=low_threshold)
    low_ratio = (float(low_count) / float(considered)) if considered > 0 else 0.0
    avg_score = (float(sum(scores) / float(len(scores))) if scores else None)
    alert = bool(considered > 0 and low_ratio >= float(alert_ratio))
    recommendation = _parse_quality_recommendation(low_ratio=float(low_ratio), considered=int(considered))

    return {
        "enabled": True,
        "low_threshold": round(float(low_threshold), 3),
        "alert_ratio": round(float(alert_ratio), 3),
        "considered": int(considered),
        "low_count": int(low_count),
        "low_ratio": round(float(low_ratio), 3),
        "avg_score": (round(float(avg_score), 3) if avg_score is not None else None),
        "alert": bool(alert),
        "recommendation": recommendation,
        "low_samples": low_samples,
    }


def _classify_parse_risk(
    *,
    summary: dict[str, Any] | None,
    hardcase_min_low_ratio: float,
    hardcase_min_considered: int,
) -> dict[str, Any]:
    payload = summary if isinstance(summary, dict) else {}
    considered = int(payload.get("considered") or 0)
    low_ratio = float(payload.get("low_ratio") or 0.0)
    recommendation = str(payload.get("recommendation") or "").strip()

    level = _parse_risk_level(considered=considered, low_ratio=low_ratio, recommendation=recommendation)
    return {
        "level": level,
        "score": round(float(low_ratio), 3),
        "reason": recommendation or ("no_parse_quality_metadata" if considered <= 0 else "parse_quality_healthy"),
        "considered": int(considered),
        "low_ratio": round(float(low_ratio), 3),
        "hardcase_eligible": _parse_risk_hardcase_eligible(
            level=level,
            considered=considered,
            low_ratio=low_ratio,
            hardcase_min_low_ratio=hardcase_min_low_ratio,
            hardcase_min_considered=hardcase_min_considered,
        ),
    }


def _parse_risk_level(*, considered: int, low_ratio: float, recommendation: str) -> str:
    if considered <= 0:
        return "unknown"
    if recommendation == "high_parse_risk_reparse_documents" or low_ratio >= 0.8:
        return "high"
    if recommendation == "medium_parse_risk_prioritize_low_quality_docs" or low_ratio >= 0.5:
        return "medium"
    if recommendation == "monitor_parse_quality_tail" or low_ratio >= 0.2:
        return "low"
    return "healthy"


def _parse_risk_hardcase_eligible(
    *,
    level: str,
    considered: int,
    low_ratio: float,
    hardcase_min_low_ratio: float,
    hardcase_min_considered: int,
) -> bool:
    return bool(
        str(level) in {"high", "medium"}
        and considered >= int(max(1, hardcase_min_considered))
        and low_ratio >= float(max(0.0, hardcase_min_low_ratio))
    )


def _normalize_parse_repair_payload(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return {"actions": raw}
    if isinstance(raw, dict):
        return dict(raw)
    return None


def _count_parse_repair_actions(actions: list[Any]) -> tuple[dict[str, int], dict[str, int], dict[str, int], set[str]]:
    action_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    docs_seen: set[str] = set()
    for item in actions[:200]:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "reparse_document").strip().lower() or "reparse_document"
        status = str(item.get("status") or "scheduled").strip().lower() or "scheduled"
        priority = str(item.get("priority") or "medium").strip().lower() or "medium"
        action_counts[action] = int(action_counts.get(action, 0) + 1)
        status_counts[status] = int(status_counts.get(status, 0) + 1)
        priority_counts[priority] = int(priority_counts.get(priority, 0) + 1)
        doc_id = str(item.get("document_id") or "").strip()
        if doc_id:
            docs_seen.add(doc_id)
    return action_counts, status_counts, priority_counts, docs_seen


def _parse_repair_run_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("scheduler_run_id")
        or payload.get("schedule_run_id")
        or payload.get("run_id")
        or ""
    ).strip()


def _parse_repair_gate_passed(payload: dict[str, Any]) -> Any:
    gate_passed = payload.get("gate_passed")
    return payload.get("passed") if gate_passed is None else gate_passed


def _build_parse_repair_actions_summary(
    payload: dict[str, Any],
    *,
    action_counts: dict[str, int],
    status_counts: dict[str, int],
    priority_counts: dict[str, int],
    docs_seen: set[str],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "enabled": True,
        "actions_total": int(sum(action_counts.values())),
        "unique_documents": int(len(docs_seen)),
        "action_counts": dict(sorted(action_counts.items(), key=lambda item: item[0])),
        "status_counts": dict(sorted(status_counts.items(), key=lambda item: item[0])),
        "priority_counts": dict(sorted(priority_counts.items(), key=lambda item: item[0])),
        "high_priority_count": int(priority_counts.get("high", 0)),
    }
    run_id = _parse_repair_run_id(payload)
    source = str(payload.get("source") or payload.get("schema") or "").strip()
    gate_passed = _parse_repair_gate_passed(payload)
    if run_id:
        out["run_id"] = run_id[:120]
    if source:
        out["source"] = source[:120]
    if gate_passed is not None:
        out["gate_passed"] = bool(gate_passed)
    return out


def _sanitize_parse_repair_actions(raw: Any) -> dict[str, Any] | None:
    """
    Normalize parse-repair action payloads into bounded diagnostics.

    Expected input:
    - list[{"document_id", "action", "status", "priority", ...}]
    - {"actions":[...], "scheduler_run_id"/"run_id", "gate_passed", ...}
    """
    payload = _normalize_parse_repair_payload(raw)
    if payload is None:
        return None

    actions = payload.get("actions")
    if not isinstance(actions, list):
        actions = []

    action_counts, status_counts, priority_counts, docs_seen = _count_parse_repair_actions(actions)
    if not action_counts and not status_counts and not priority_counts and not docs_seen:
        return None

    return _build_parse_repair_actions_summary(
        payload,
        action_counts=action_counts,
        status_counts=status_counts,
        priority_counts=priority_counts,
        docs_seen=docs_seen,
    )

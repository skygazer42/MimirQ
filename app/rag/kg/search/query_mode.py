from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

_ALLOWED_MODES = {"auto", "local", "global", "drift"}
_QUOTE_CHARS = "\"“”'‘’`"
_QUOTE_CLASS = re.escape(_QUOTE_CHARS)

_DRIFT_RE = re.compile(
    r"(?i)\b(drift|delta|change|changed|trend|versus|vs\.?|compared to|year over year|month over month)\b"
    r"|漂移|变化|趋势|同比|环比|较上期|对比"
)
_GLOBAL_RE = re.compile(
    r"(?i)\b(overall|global|across|all\b|aggregate|distribution|summary|overview)\b"
    r"|总体|全局|全部|整体|汇总|总览|概览"
)
_LOCAL_RE = re.compile(
    r"(?i)\b(this row|that row|which row|exact|id\s*=|primary key|pk\b)\b"
    r"|哪一行|具体|主键|这一条|这条记录"
)
_DATASET_FACTOID_RE = re.compile(
    r"(?i)\b(which|what|who|where|when|identify|find|name)\b"
    r"|哪篇|哪一个|哪个|哪些|什么"
)
_DATASET_FACTOID_DOMAIN_RE = re.compile(
    r"(?i)\b(paper|article|survey|review|work|method|model|approach|introduc(?:e|ed|es)|propos(?:e|ed|es))\b"
    r"|论文|文章|综述|方法|模型|提出|介绍"
)
_QUOTED_RE = re.compile(rf"[{_QUOTE_CLASS}][^{_QUOTE_CLASS}]{{2,160}}[{_QUOTE_CLASS}]")


def normalize_kg_query_mode(mode: Any, *, default: str = "auto") -> str:
    raw = str(mode or "").strip().lower()
    if raw in _ALLOWED_MODES:
        return raw
    return str(default or "auto").strip().lower() if str(default or "auto").strip().lower() in _ALLOWED_MODES else "auto"


def _query_mode_result(mode: str, confidence: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "mode": mode,
        "confidence": confidence,
        "reason_codes": reasons,
    }


def classify_kg_query_mode(
    *,
    query: str,
    document_ids: list[Any] | None = None,
    dataset_id: Any = None,
    default_mode: str = "auto",
) -> dict[str, Any]:
    default_norm = normalize_kg_query_mode(default_mode, default="auto")
    if default_norm != "auto":
        return _query_mode_result(default_norm, "forced", ["default_mode_forced"])

    q = str(query or "").strip()
    q_fold = q.casefold()
    reasons: list[str] = []

    if _DRIFT_RE.search(q):
        reasons.append("drift_pattern")
        return _query_mode_result("drift", "high", reasons)

    has_local = bool(_LOCAL_RE.search(q))
    if has_local:
        reasons.append("local_pattern")

    if _QUOTED_RE.search(q):
        reasons.append("quoted_term")
        has_local = True

    if _GLOBAL_RE.search(q):
        reasons.append("global_pattern")
        # Global wins unless local is explicit and strong.
        if not has_local:
            return _query_mode_result("global", "medium", reasons)

    doc_count = len(list(document_ids or []))
    if doc_count == 1 and ("id=" in q_fold or "主键" in q or "row" in q_fold):
        reasons.append("single_doc_row_focus")
        return _query_mode_result("local", "high", reasons)

    if has_local:
        return _query_mode_result("local", "medium", reasons)

    if dataset_id is not None and doc_count == 0 and _DATASET_FACTOID_RE.search(q):
        reasons.append("dataset_factoid_scope")
        if _DATASET_FACTOID_DOMAIN_RE.search(q):
            reasons.append("dataset_factoid_domain")
        return _query_mode_result("local", "medium", reasons)

    if dataset_id is not None and doc_count == 0:
        reasons.append("dataset_scope_no_doc_ids")
        return _query_mode_result("global", "low", reasons)

    reasons.append("fallback_global")
    return _query_mode_result("global", "low", reasons)


def build_mode_aware_recall_overrides(
    *,
    mode: str,
    max_events: int,
    max_entities: int,
    final_entity_count: int,
    entity_weight_threshold: float,
    query_mode_confidence: str | None = None,
    query_mode_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    mode_norm = normalize_kg_query_mode(mode, default="global")

    max_events_out = max(1, int(max_events or 1))
    max_entities_out = max(1, int(max_entities or 1))
    final_entity_count_out = max(1, int(final_entity_count or 1))
    entity_weight_threshold_out = min(1.0, max(0.0, float(entity_weight_threshold or 0.0)))
    confidence = str(query_mode_confidence or "").strip().lower()
    input_reasons = {str(x).strip() for x in (query_mode_reason_codes or []) if str(x).strip()}
    reason_codes: list[str] = []

    if mode_norm == "local":
        max_events_out = min(
            int(max_events_out),
            max(1, int(getattr(settings, "KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS", 40) or 40)),
        )
        final_entity_count_out = min(final_entity_count_out, 20)
        bonus = float(getattr(settings, "KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS", 0.05) or 0.05)
        entity_weight_threshold_out = min(1.0, entity_weight_threshold_out + max(0.0, bonus))
        reason_codes.append("local_focus_budget")
    elif mode_norm == "global":
        is_low_confidence_fallback = (
            confidence == "low"
            and "global_pattern" not in input_reasons
            and "drift_pattern" not in input_reasons
        )
        if is_low_confidence_fallback:
            # Dataset-scoped factoid queries often resolve to "global" only because no
            # document ids were supplied. Keep those searches responsive; explicit
            # overview/global-pattern queries still use the broader coverage budget.
            max_events_out = min(
                int(max_events_out),
                max(1, int(getattr(settings, "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS", 80) or 80)),
            )
            reason_codes.append("low_confidence_global_budget")
        else:
            max_events_out = max(
                int(max_events_out),
                max(1, int(getattr(settings, "KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS", 120) or 120)),
            )
            max_entities_out = max(max_entities_out, 40)
            final_entity_count_out = max(final_entity_count_out, 25)
            reason_codes.append("global_coverage_budget")
    elif mode_norm == "drift":
        max_events_out = max(
            int(max_events_out),
            max(1, int(getattr(settings, "KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS", 140) or 140)),
        )
        max_entities_out = max(max_entities_out, 45)
        final_entity_count_out = max(final_entity_count_out, 30)
        reason_codes.append("drift_expanded_budget")

    return {
        "mode": mode_norm,
        "max_events": int(max_events_out),
        "max_entities": int(max_entities_out),
        "final_entity_count": int(final_entity_count_out),
        "entity_weight_threshold": round(float(entity_weight_threshold_out), 6),
        "reason_codes": reason_codes,
    }


__all__ = [
    "build_mode_aware_recall_overrides",
    "classify_kg_query_mode",
    "normalize_kg_query_mode",
]

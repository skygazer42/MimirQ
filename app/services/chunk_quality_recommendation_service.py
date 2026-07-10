
from collections.abc import Mapping, Sequence
from typing import Any

CHUNK_QUALITY_RECOMMENDATION_SCHEMA = "mimirq.chunk_quality_recommendation.v1"
CHUNKER_AUTOTUNE_PLAN_SCHEMA = "mimirq.chunker_autotune_plan.v1"

_SEVERITY_ORDER = {"healthy": 0, "info": 1, "warning": 2, "error": 3}
_PRIORITY_BY_SEVERITY = {"error": "high", "warning": "medium", "info": "low"}


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return int(default)
        return int(v)
    except Exception:
        return int(default)


def _as_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(max(0, numerator)) / float(denominator), 3)


def _priority(raw: str) -> str:
    return _PRIORITY_BY_SEVERITY.get(str(raw or "warning"), "medium")


def _next_severity(current: str, candidate: str) -> str:
    cur = str(current or "healthy")
    nxt = str(candidate or "healthy")
    if _SEVERITY_ORDER.get(nxt, 0) > _SEVERITY_ORDER.get(cur, 0):
        return nxt
    return cur


def _pipeline_defaults(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    base = dict(raw or {})
    chunk_size = max(1, _as_int(base.get("chunk_size"), 1000))
    chunk_overlap = max(0, _as_int(base.get("chunk_overlap"), 200))
    if chunk_overlap >= chunk_size:
        chunk_overlap = max(0, chunk_size - 1)
    return {
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "chunk_strategy": str(base.get("chunk_strategy") or "").strip() or None,
    }


def _sized_patch(defaults: Mapping[str, Any], *, multiplier: float) -> dict[str, Any]:
    chunk_size = max(1, _as_int(defaults.get("chunk_size"), 1000))
    chunk_overlap = max(0, _as_int(defaults.get("chunk_overlap"), 200))
    ratio = (float(chunk_overlap) / float(chunk_size)) if chunk_size > 0 else 0.2

    target_size = int(round(chunk_size * float(multiplier)))
    target_size = max(200, min(4000, target_size))
    target_overlap = int(round(target_size * ratio))
    target_overlap = max(0, min(1000, target_overlap))
    if target_overlap >= target_size:
        target_overlap = max(0, target_size - 1)

    patch = {
        "chunk_size": int(target_size),
        "chunk_overlap": int(target_overlap),
        "chunk_strategy_candidates": [
            "markdown_header",
            "outline",
            str(defaults.get("chunk_strategy") or "semantic_sentence"),
        ],
    }
    return patch


def _overlap_patch(defaults: Mapping[str, Any], *, target_ratio: float = 0.15) -> dict[str, Any]:
    chunk_size = max(1, _as_int(defaults.get("chunk_size"), 1000))
    target_overlap = int(round(chunk_size * float(target_ratio)))
    target_overlap = max(0, min(1000, target_overlap))
    if target_overlap >= chunk_size:
        target_overlap = max(0, chunk_size - 1)
    return {"chunk_overlap": int(target_overlap)}


def build_chunk_quality_recommendation(
    *,
    total_documents: int,
    chunk_quality_metrics: Mapping[str, Any] | None,
    recall_risk_hints: Sequence[Mapping[str, Any]] | None = None,
    parse_risk_summary: Mapping[str, Any] | None = None,
    pipeline_defaults: Mapping[str, Any] | None = None,
    max_recommendations: int = 8,
) -> dict[str, Any]:
    total_docs = max(0, int(total_documents or 0))
    metrics = dict(chunk_quality_metrics or {})
    gate_grade_docs = dict(metrics.get("gate_grade_docs") or {})
    defaults = _pipeline_defaults(pipeline_defaults)

    pass_docs = max(0, _as_int(gate_grade_docs.get("pass")))
    warn_docs = max(0, _as_int(gate_grade_docs.get("warn")))
    fail_docs = max(0, _as_int(gate_grade_docs.get("fail")))
    unknown_docs = max(0, _as_int(gate_grade_docs.get("unknown")))
    coverage_low_docs = max(0, _as_int(metrics.get("coverage_low_documents")))
    overlap_high_docs = max(0, _as_int(metrics.get("overlap_waste_high_documents")))
    token_stats_missing_docs = max(0, _as_int(metrics.get("token_stats_missing_documents")))
    fail_ratio = _as_ratio(fail_docs, total_docs)

    hints_by_key = {
        str(item.get("key") or "").strip(): dict(item)
        for item in (recall_risk_hints or [])
        if isinstance(item, Mapping) and str(item.get("key") or "").strip()
    }
    parse_summary = dict(parse_risk_summary or {})
    parse_recommendation = str(parse_summary.get("recommendation") or "").strip()

    recommendations: list[dict[str, Any]] = []
    severity = "healthy"

    def _push(
        *,
        key: str,
        level: str,
        message: str,
        patch: dict[str, Any] | None = None,
        target: str = "pipeline",
        signals: dict[str, Any] | None = None,
    ) -> None:
        nonlocal severity
        severity = _next_severity(severity, level)
        recommendations.append(
            {
                "key": key,
                "severity": level,
                "priority": _priority(level),
                "message": message,
                "target": target,
                "signals": dict(signals or {}),
                "patch": dict(patch or {}),
            }
        )

    short_chunks = hints_by_key.get("short_chunks_heavy")
    if short_chunks is not None:
        hint_severity = str(short_chunks.get("severity") or "warning").strip() or "warning"
        pct = _as_int((short_chunks.get("observed") or {}).get("short_chunk_pct"))
        _push(
            key="increase_chunk_size_or_structure_aware",
            level=hint_severity,
            message=f"短 chunk 占比偏高（{pct}%），建议增大 chunk_size 并优先改用结构化切分。",
            patch=_sized_patch(defaults, multiplier=1.25 if hint_severity == "error" else 1.15),
            signals={"short_chunk_pct": pct},
        )
    elif fail_ratio >= 0.25:
        _push(
            key="increase_chunk_size_or_structure_aware",
            level="warning",
            message="chunk_quality gate fail 占比偏高，建议增大 chunk_size 并复核切分策略。",
            patch=_sized_patch(defaults, multiplier=1.25),
            signals={"fail_ratio": fail_ratio},
        )

    if overlap_high_docs > 0:
        level = "warning" if overlap_high_docs < max(3, total_docs // 5 or 1) else "error"
        _push(
            key="reduce_chunk_overlap",
            level=level,
            message=f"高 overlap waste 文档数为 {overlap_high_docs}，建议下调 chunk_overlap 控制冗余 embedding 成本。",
            patch=_overlap_patch(defaults, target_ratio=0.15),
            signals={"overlap_waste_high_documents": overlap_high_docs},
        )

    if coverage_low_docs > 0:
        level = "error" if coverage_low_docs >= max(3, total_docs // 4 or 1) else "warning"
        _push(
            key="repair_coverage_before_reindex",
            level=level,
            message=f"存在 {coverage_low_docs} 份 coverage 偏低文档，建议先排查 parser/backend/治理规则，再重建索引。",
            patch={
                "review_parser_backend": True,
                "review_governance_drop_rules": True,
                "reindex_after_fix": True,
            },
            signals={"coverage_low_documents": coverage_low_docs},
        )

    if "low_lexical_diversity" in hints_by_key:
        hint = hints_by_key["low_lexical_diversity"]
        pct = _as_int((hint.get("observed") or {}).get("duplicate_docs_pct"))
        level = str(hint.get("severity") or "warning").strip() or "warning"
        _push(
            key="enable_duplicate_governance",
            level=level,
            message=f"重复/低多样性文档占比约 {pct}%，建议开启重复段落治理并复核 near_dedup。",
            patch={
                "governance_drop_duplicate_paragraphs": True,
                "near_dedup_review": True,
            },
            signals={"duplicate_docs_pct": pct},
        )

    if parse_recommendation in {
        "high_parse_risk_reparse_documents",
        "medium_parse_risk_prioritize_low_quality_docs",
    }:
        level = "error" if parse_recommendation == "high_parse_risk_reparse_documents" else "warning"
        _push(
            key="reparse_low_quality_documents",
            level=level,
            message="解析质量 tail 已影响 chunk 质量闭环，建议优先对低质量文档做重解析/OCR 回灌。",
            patch={
                "reparse_low_quality_documents": True,
                "prioritize_parse_quality_tail": True,
            },
            signals={
                "recommendation": parse_recommendation,
                "high_risk_documents": max(0, _as_int(parse_summary.get("high_risk_documents"))),
            },
        )

    if token_stats_missing_docs > 0:
        _push(
            key="backfill_chunk_token_stats",
            level="info",
            message=f"仍有 {token_stats_missing_docs} 份文档缺少 token 统计，建议补回填以提升后续闭环建议精度。",
            patch={"backfill_chunking_stats_tokens": True},
            signals={"token_stats_missing_documents": token_stats_missing_docs},
            target="ops",
        )

    recommendations.sort(
        key=lambda item: (
            -_SEVERITY_ORDER.get(str(item.get("severity") or "healthy"), 0),
            str(item.get("key") or ""),
        )
    )
    recommendations = recommendations[: max(0, int(max_recommendations or 0))]

    if recommendations and severity == "healthy":
        severity = "info"

    return {
        "schema": CHUNK_QUALITY_RECOMMENDATION_SCHEMA,
        "severity": severity,
        "summary": {
            "total_documents": int(total_docs),
            "pass_documents": int(pass_docs),
            "warn_documents": int(warn_docs),
            "fail_documents": int(fail_docs),
            "unknown_documents": int(unknown_docs),
            "fail_ratio": fail_ratio,
            "coverage_low_documents": int(coverage_low_docs),
            "overlap_waste_high_documents": int(overlap_high_docs),
            "token_stats_missing_documents": int(token_stats_missing_docs),
        },
        "recommendations": recommendations,
    }


def build_chunker_autotune_plan(
    *,
    total_documents: int,
    chunk_quality_metrics: Mapping[str, Any] | None,
    recall_risk_hints: Sequence[Mapping[str, Any]] | None = None,
    parse_risk_summary: Mapping[str, Any] | None = None,
    pipeline_defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    defaults = _pipeline_defaults(pipeline_defaults)
    recommendation = build_chunk_quality_recommendation(
        total_documents=total_documents,
        chunk_quality_metrics=chunk_quality_metrics,
        recall_risk_hints=recall_risk_hints,
        parse_risk_summary=parse_risk_summary,
        pipeline_defaults=defaults,
    )

    merged_defaults: dict[str, Any] = dict(defaults)
    source_keys: list[str] = []

    for item in recommendation.get("recommendations") or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("target") or "pipeline") != "pipeline":
            continue
        patch = dict(item.get("patch") or {})
        relevant: dict[str, Any] = {}
        if "chunk_size" in patch:
            relevant["chunk_size"] = max(1, _as_int(patch.get("chunk_size"), defaults.get("chunk_size", 1000)))
        if "chunk_overlap" in patch:
            relevant["chunk_overlap"] = max(0, _as_int(patch.get("chunk_overlap"), defaults.get("chunk_overlap", 200)))
        if "chunk_strategy_candidates" in patch:
            relevant["chunk_strategy_candidates"] = list(patch.get("chunk_strategy_candidates") or [])
        if not relevant:
            continue
        source_keys.append(str(item.get("key") or ""))
        merged_defaults.update(relevant)

    action = "retune_defaults" if source_keys else "no_change"
    if action == "no_change":
        merged_defaults = {
            "chunk_size": int(defaults["chunk_size"]),
            "chunk_overlap": int(defaults["chunk_overlap"]),
            "chunk_strategy": defaults.get("chunk_strategy"),
        }

    return {
        "schema": CHUNKER_AUTOTUNE_PLAN_SCHEMA,
        "action": action,
        "severity": str(recommendation.get("severity") or "healthy"),
        "recommended_defaults": merged_defaults,
        "source_recommendation_keys": source_keys,
        "summary": dict(recommendation.get("summary") or {}),
    }


__all__ = [
    "CHUNKER_AUTOTUNE_PLAN_SCHEMA",
    "CHUNK_QUALITY_RECOMMENDATION_SCHEMA",
    "build_chunk_quality_recommendation",
    "build_chunker_autotune_plan",
]

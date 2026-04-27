from __future__ import annotations

from typing import Any

from app.rag.kg.extraction.relation_processor import normalize_predicate

AUTO_GRAPH_R1_PLAN_SCHEMA_V1 = "mimirq.kg.auto_graph_r1_plan.v1"
_VALID_BACKENDS = {"llm", "gliner", "hybrid"}


def _normalize_backend(value: str | None) -> str:
    backend = str(value or "").strip().lower()
    if backend in _VALID_BACKENDS:
        return backend
    return "llm"


def _normalize_type_counts(entity_type_counts: dict[str, int] | None) -> list[dict[str, int | str]]:
    counts: dict[str, int] = {}
    for raw_key, raw_count in (entity_type_counts or {}).items():
        key = str(raw_key or "").strip().lower() or "unknown"
        try:
            count = max(0, int(raw_count or 0))
        except Exception:
            count = 0
        if count <= 0:
            continue
        counts[key] = counts.get(key, 0) + count

    return [
        {"entity_type": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _normalize_predicate_counts(predicate_counts: dict[str, int] | None) -> list[dict[str, int | str]]:
    counts: dict[str, int] = {}
    for raw_key, raw_count in (predicate_counts or {}).items():
        key = normalize_predicate(str(raw_key or ""))
        try:
            count = max(0, int(raw_count or 0))
        except Exception:
            count = 0
        if count <= 0:
            continue
        counts[key] = counts.get(key, 0) + count

    return [
        {"predicate": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_auto_graph_r1_plan(
    *,
    chunk_count: int = 0,
    entity_type_counts: dict[str, int] | None = None,
    predicate_counts: dict[str, int] | None = None,
    alias_candidate_count: int = 0,
    skill_candidate_count: int = 0,
    extraction_backend: str | None = None,
) -> dict[str, Any]:
    backend = _normalize_backend(extraction_backend)
    normalized_types = _normalize_type_counts(entity_type_counts)
    normalized_predicates = _normalize_predicate_counts(predicate_counts)

    total_entities = sum(int(row["count"]) for row in normalized_types)
    total_predicates = sum(int(row["count"]) for row in normalized_predicates)
    unknown_entities = sum(int(row["count"]) for row in normalized_types if row["entity_type"] == "unknown")
    unknown_predicates = sum(int(row["count"]) for row in normalized_predicates if row["predicate"] == "unknown")

    unknown_entity_ratio = (float(unknown_entities) / float(total_entities)) if total_entities > 0 else 0.0
    unknown_predicate_ratio = (float(unknown_predicates) / float(total_predicates)) if total_predicates > 0 else 0.0

    risk_flags: list[str] = []
    if unknown_predicate_ratio > 0.25:
        risk_flags.append("high_unknown_predicate_ratio")
    if unknown_entity_ratio >= 0.5:
        risk_flags.append("unknown_entity_type_heavy")
    if int(alias_candidate_count or 0) >= 8:
        risk_flags.append("alias_fragmentation")

    phases: list[dict[str, Any]] = [
        {
            "phase_id": "bootstrap_extraction",
            "objective": "run event/entity extraction on a representative corpus slice",
            "backend": backend,
            "chunk_budget": max(1, int(chunk_count or 0)),
        },
        {
            "phase_id": "ontology_bootstrap",
            "objective": "stabilize entity type taxonomy before large-scale graph loading",
            "focus_entity_types": [row["entity_type"] for row in normalized_types[:5]],
        },
    ]
    if int(chunk_count or 0) > 0 or normalized_predicates:
        phases.append(
            {
                "phase_id": "predicate_induction",
                "objective": "promote stable predicates and route unknown predicates to review",
                "unknown_ratio": round(unknown_predicate_ratio, 4),
                "top_predicates": [row["predicate"] for row in normalized_predicates[:5]],
            }
        )
    if int(alias_candidate_count or 0) > 0:
        phases.append(
            {
                "phase_id": "alias_consolidation",
                "objective": "merge duplicated surfaces before graph persistence",
                "candidate_count": int(alias_candidate_count or 0),
            }
        )
    if int(skill_candidate_count or 0) > 0:
        phases.append(
            {
                "phase_id": "skill_harvest",
                "objective": "capture SOP/process knowledge alongside entity-event extraction",
                "candidate_count": int(skill_candidate_count or 0),
            }
        )

    return {
        "schema": AUTO_GRAPH_R1_PLAN_SCHEMA_V1,
        "backend": backend,
        "chunk_count": max(0, int(chunk_count or 0)),
        "top_entity_types": normalized_types[:5],
        "top_predicates": normalized_predicates[:5],
        "risk_flags": risk_flags,
        "promotion_thresholds": {
            "promote_entity_type_min_support": 5,
            "promote_predicate_min_support": 3,
            "manual_review_unknown_ratio_gt": 0.25,
        },
        "phases": phases,
    }


__all__ = ["AUTO_GRAPH_R1_PLAN_SCHEMA_V1", "build_auto_graph_r1_plan"]

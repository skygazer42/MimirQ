import math
from collections import defaultdict
from statistics import pstdev
from typing import Any

from app.rag.evaluation.metrics.decomposition import compute_decomposition_metrics
from app.rag.evaluation.metrics.fusion import compute_fusion_metrics
from app.rag.evaluation.metrics.routing import compute_routing_accuracy


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        if math.isnan(out):
            return None
        return out
    except Exception:
        return None


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def _percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    idx = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
    return round(float(ordered[idx]), 4)


def _extract_eval_metric(row: dict[str, Any], *path: str) -> float | None:
    cur: Any = row.get("evaluators")
    if not isinstance(cur, dict):
        return None
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return _to_float(cur)


def _extract_row_hard_negative_drop(row: dict[str, Any]) -> float | None:
    ext = row.get("extensions") if isinstance(row.get("extensions"), dict) else {}
    return _to_float(ext.get("hard_negative_recall_drop"))


def _extract_subqueries(row: dict[str, Any], key: str) -> list[str] | None:
    ext = row.get("extensions") if isinstance(row.get("extensions"), dict) else {}
    raw = ext.get(key)
    return list(raw) if isinstance(raw, list) else None


def _is_correct_answer(row: dict[str, Any]) -> bool:
    answer_em = _extract_eval_metric(row, "answer_det", "answer_em")
    if answer_em is not None and answer_em >= 1.0:
        return True
    refusal_correct = None
    evaluators = row.get("evaluators") if isinstance(row.get("evaluators"), dict) else {}
    answer_det = evaluators.get("answer_det") if isinstance(evaluators.get("answer_det"), dict) else {}
    if "refusal_correct" in answer_det:
        refusal_correct = (
            bool(answer_det.get("refusal_correct")) if answer_det.get("refusal_correct") is not None else None
        )
    return bool(refusal_correct)


def _has_decision_trace(row: dict[str, Any]) -> bool:
    if isinstance(row.get("retrieval_trace"), dict):
        return True
    if isinstance(row.get("query_debug"), dict):
        return True
    ext = row.get("extensions") if isinstance(row.get("extensions"), dict) else {}
    return isinstance(ext.get("decision_trace"), dict)


def _metric_values(rows: list[dict[str, Any]], *path: str) -> list[float]:
    return [value for row in rows if (value := _extract_eval_metric(row, *path)) is not None]


def _faithfulness_values(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        val = _extract_eval_metric(row, "faithfulness", "score")
        if val is None:
            val = _extract_eval_metric(row, "ragas", "faithfulness")
        if val is not None:
            values.append(val)
    return values


def _fusion_dimension(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    fusion_rows: list[dict[str, Any]] = []
    fusion_conflict_values: list[float] = []
    fusion_gain_values: list[float] = []
    for row in rows:
        evaluators = row.get("evaluators") if isinstance(row.get("evaluators"), dict) else {}
        fusion_eval = evaluators.get("fusion") if isinstance(evaluators.get("fusion"), dict) else None
        if isinstance(fusion_eval, dict):
            conflict = _to_float(fusion_eval.get("conflict_rate"))
            gain = _to_float(fusion_eval.get("net_gain_over_best_single"))
            if conflict is not None:
                fusion_conflict_values.append(conflict)
            if gain is not None:
                fusion_gain_values.append(gain)
            continue
        fusion_rows.append(row)

    fusion = (
        compute_fusion_metrics(fusion_rows)
        if fusion_rows
        else {"conflict_rate": None, "net_gain_over_best_single": None}
    )
    return {
        "conflict_rate": _avg(fusion_conflict_values) if fusion_conflict_values else fusion.get("conflict_rate"),
        "net_gain_over_best_single": _avg(fusion_gain_values)
        if fusion_gain_values
        else fusion.get("net_gain_over_best_single"),
    }


def _abstain_dimension(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unanswerable_rows = [
        row
        for row in rows
        if str(row.get("query_type") or "").strip().lower() == "unanswerable"
        or _extract_eval_metric(row, "answer_det", "refusal_correct") is not None
    ]
    abstain_values: list[float] = []
    for row in unanswerable_rows:
        evaluators = row.get("evaluators") if isinstance(row.get("evaluators"), dict) else {}
        answer_det = evaluators.get("answer_det") if isinstance(evaluators.get("answer_det"), dict) else {}
        if answer_det.get("refusal_correct") is None:
            continue
        abstain_values.append(1.0 if bool(answer_det.get("refusal_correct")) else 0.0)
    return {
        "abstain_rate": _avg(abstain_values),
        "evaluated_unanswerable": int(len(abstain_values)),
    }


def _cost_dimension(rows: list[dict[str, Any]], *, token_cost_values: list[float]) -> dict[str, Any]:
    correct_count = sum(1 for row in rows if _is_correct_answer(row))
    cost_per_correct = None
    if token_cost_values and correct_count > 0:
        cost_per_correct = round(sum(token_cost_values) / float(correct_count), 4)
    return {
        "token_cost_avg": _avg(token_cost_values),
        "cost_per_correct": cost_per_correct,
    }


def _stability_dimension(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped_by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        sample_id = str(row.get("sample_id") or "").strip()
        if sample_id:
            grouped_by_sample[sample_id].append(row)

    answer_f1_std_values: list[float] = []
    latency_std_values: list[float] = []
    repeated_groups = 0
    for group in grouped_by_sample.values():
        if len(group) < 2:
            continue
        repeated_groups += 1
        answer_group = [
            value for row in group if (value := _extract_eval_metric(row, "answer_det", "answer_f1")) is not None
        ]
        latency_group = [value for row in group if (value := _to_float(row.get("latency_ms"))) is not None]
        if len(answer_group) >= 2:
            answer_f1_std_values.append(round(float(pstdev(answer_group)), 4))
        if len(latency_group) >= 2:
            latency_std_values.append(round(float(pstdev(latency_group)), 4))
    return {
        "sample_groups_with_repeats": int(repeated_groups),
        "answer_f1_std_avg": _avg(answer_f1_std_values),
        "latency_ms_std_avg": _avg(latency_std_values),
    }


def _trace_dimension(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trace_rows = sum(1 for row in rows if _has_decision_trace(row))
    trace_coverage = 0.0 if not rows else round(trace_rows / float(len(rows)), 4)
    return {"decision_trace_coverage": trace_coverage}


def _compute_dimensions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    routing = compute_routing_accuracy(rows)
    decomp_rows = [
        {
            "gold_subqueries": _extract_subqueries(row, "gold_subqueries"),
            "predicted_subqueries": _extract_subqueries(row, "predicted_subqueries"),
        }
        for row in rows
    ]
    decomposition = compute_decomposition_metrics(decomp_rows)
    recall_values = _metric_values(rows, "retrieval", "recall_at_k")
    mrr_values = _metric_values(rows, "retrieval", "mrr")
    ndcg_values = _metric_values(rows, "retrieval", "ndcg")
    citation_coverage_values = _metric_values(rows, "retrieval", "citation_coverage")
    citation_precision_values = _metric_values(rows, "retrieval", "citation_precision")
    answer_em_values = _metric_values(rows, "answer_det", "answer_em")
    answer_f1_values = _metric_values(rows, "answer_det", "answer_f1")
    faithfulness_values = _faithfulness_values(rows)
    fusion_quality = _fusion_dimension(rows)
    abstain_ability = _abstain_dimension(rows)
    hard_negative_values = [value for row in rows if (value := _extract_row_hard_negative_drop(row)) is not None]
    latency_values = [value for row in rows if (value := _to_float(row.get("latency_ms"))) is not None]
    token_cost_values = [value for row in rows if (value := _to_float(row.get("token_cost"))) is not None]
    cost = _cost_dimension(rows, token_cost_values=token_cost_values)
    stability = _stability_dimension(rows)
    explainability = _trace_dimension(rows)

    return {
        "routing_decision": {
            "routing_accuracy": routing.get("routing_accuracy"),
            "decomposition_f1": decomposition.get("decomposition_f1"),
            "exact_match_rate": decomposition.get("exact_match_rate"),
        },
        "retrieval_quality": {
            "recall_at_k_avg": _avg(recall_values),
            "mrr_avg": _avg(mrr_values),
            "ndcg_avg": _avg(ndcg_values),
        },
        "fusion_quality": fusion_quality,
        "answer_quality": {
            "answer_em_avg": _avg(answer_em_values),
            "answer_f1_avg": _avg(answer_f1_values),
            "faithfulness_avg": _avg(faithfulness_values),
        },
        "citation_quality": {
            "citation_coverage_avg": _avg(citation_coverage_values),
            "citation_precision_avg": _avg(citation_precision_values),
        },
        "abstain_ability": abstain_ability,
        "interference_resilience": {
            "hard_negative_recall_drop_avg": _avg(hard_negative_values),
        },
        "latency": {
            "p50_ms": (_percentile(latency_values, 50) if latency_values else None),
            "p95_ms": (_percentile(latency_values, 95) if latency_values else None),
            "p99_ms": (_percentile(latency_values, 99) if latency_values else None),
        },
        "cost": cost,
        "stability": stability,
        "explainability": explainability,
    }


def summarize_eval_dashboard_11d(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_rows = [dict(row or {}) for row in (rows or []) if isinstance(row, dict)]
    route_ids = sorted(
        {str(row.get("route_id") or "").strip() for row in normalized_rows if str(row.get("route_id") or "").strip()}
    )

    by_query_type: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        query_type = str(row.get("query_type") or "").strip()
        if not query_type:
            continue
        groups[query_type].append(row)

    for query_type, group in sorted(groups.items(), key=lambda kv: kv[0]):
        by_query_type[query_type] = {
            "sample_count": int(len(group)),
            "dimensions": _compute_dimensions(group),
        }

    return {
        "schema": "mimirq.eval.dashboard_11d.v1",
        "summary": {
            "sample_count": int(len(normalized_rows)),
            "route_ids": route_ids,
        },
        "dimensions": _compute_dimensions(normalized_rows),
        "by_query_type": by_query_type,
    }


__all__ = ["summarize_eval_dashboard_11d"]

from __future__ import annotations

from typing import Any


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        num = float(value)
        if num != num:
            return None
        return num
    except (TypeError, ValueError):
        return None


def _extract_answer_f1(row: dict[str, Any]) -> float | None:
    evaluators = row.get("evaluators")
    if not isinstance(evaluators, dict):
        return None
    answer_det = evaluators.get("answer_det")
    if not isinstance(answer_det, dict):
        return None
    return _to_float(answer_det.get("answer_f1"))


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def diff_online_shadow_runs(
    *,
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_id = {str(row.get("sample_id") or "").strip(): dict(row) for row in list(baseline or []) if str(row.get("sample_id") or "").strip()}
    candidate_by_id = {str(row.get("sample_id") or "").strip(): dict(row) for row in list(candidate or []) if str(row.get("sample_id") or "").strip()}

    shared_ids = sorted(set(baseline_by_id.keys()) & set(candidate_by_id.keys()))
    baseline_only = sorted(set(baseline_by_id.keys()) - set(candidate_by_id.keys()))
    candidate_only = sorted(set(candidate_by_id.keys()) - set(baseline_by_id.keys()))

    rows: list[dict[str, Any]] = []
    answer_f1_deltas: list[float] = []
    latency_deltas: list[float] = []
    token_cost_deltas: list[float] = []

    for sample_id in shared_ids:
        base = baseline_by_id[sample_id]
        cand = candidate_by_id[sample_id]
        base_answer_f1 = _extract_answer_f1(base)
        cand_answer_f1 = _extract_answer_f1(cand)
        base_latency = _to_float(base.get("latency_ms"))
        cand_latency = _to_float(cand.get("latency_ms"))
        base_cost = _to_float(base.get("token_cost"))
        cand_cost = _to_float(cand.get("token_cost"))

        deltas = {
            "answer_f1": round((cand_answer_f1 or 0.0) - (base_answer_f1 or 0.0), 4),
            "latency_ms": round((cand_latency or 0.0) - (base_latency or 0.0), 4),
            "token_cost": round((cand_cost or 0.0) - (base_cost or 0.0), 6),
        }
        answer_f1_deltas.append(float(deltas["answer_f1"]))
        latency_deltas.append(float(deltas["latency_ms"]))
        token_cost_deltas.append(float(deltas["token_cost"]))

        rows.append(
            {
                "sample_id": sample_id,
                "baseline": base,
                "candidate": cand,
                "deltas": deltas,
            }
        )

    return {
        "schema": "mimirq.online_shadow_diff.v1",
        "summary": {
            "compared": int(len(shared_ids)),
            "candidate_only": int(len(candidate_only)),
            "baseline_only": int(len(baseline_only)),
            "answer_f1_delta_avg": _average(answer_f1_deltas),
            "latency_ms_delta_avg": _average(latency_deltas),
            "token_cost_delta_avg": _average(token_cost_deltas),
        },
        "rows": rows,
        "candidate_only": candidate_only,
        "baseline_only": baseline_only,
    }


__all__ = ["diff_online_shadow_runs"]

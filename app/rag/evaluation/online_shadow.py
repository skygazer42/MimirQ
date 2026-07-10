
import hashlib
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


def _stable_rank(*, day_key: str, query_hash: str, dataset_id_hash: str) -> str:
    raw = f"{day_key}|{query_hash}|{dataset_id_hash}".encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def build_online_shadow_plan(
    *,
    replay_records: list[dict[str, Any]],
    day_key: str,
    sample_size: int,
    baseline_label: str,
    candidate_label: str,
) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    for row in replay_records or []:
        if not isinstance(row, dict):
            continue
        query_hash = str(row.get("query_hash") or "").strip()
        if not query_hash:
            continue
        rec = {
            "query_hash": query_hash,
            "dataset_id_hash": str(row.get("dataset_id_hash") or "").strip() or None,
            "retrieval_config_hash": str(row.get("retrieval_config_hash") or "").strip() or None,
            "rag_config": dict(row.get("rag_config") or {}),
            "seed": row.get("seed"),
        }
        sample_id = _stable_rank(
            day_key=str(day_key or "").strip(),
            query_hash=query_hash,
            dataset_id_hash=str(rec.get("dataset_id_hash") or ""),
        )[:16]
        rec["sample_id"] = sample_id
        eligible.append(rec)

    ranked = sorted(
        eligible,
        key=lambda row: (
            _stable_rank(
                day_key=str(day_key or "").strip(),
                query_hash=str(row.get("query_hash") or ""),
                dataset_id_hash=str(row.get("dataset_id_hash") or ""),
            ),
            str(row.get("sample_id") or ""),
        ),
    )

    limit = max(0, int(sample_size or 0))
    selected = ranked[:limit] if limit > 0 else []

    return {
        "schema": "mimirq.online_shadow_plan.v1",
        "day_key": str(day_key or "").strip() or None,
        "summary": {
            "eligible": int(len(eligible)),
            "selected": int(len(selected)),
        },
        "sample_ids": [str(row.get("sample_id") or "") for row in selected],
        "samples": selected,
        "baseline": {"label": str(baseline_label or "").strip() or None},
        "candidate": {"label": str(candidate_label or "").strip() or None},
    }


def diff_online_shadow_runs(
    *,
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_id = {str(row.get("sample_id") or "").strip(): dict(row) for row in baseline or [] if str(row.get("sample_id") or "").strip()}
    candidate_by_id = {str(row.get("sample_id") or "").strip(): dict(row) for row in candidate or [] if str(row.get("sample_id") or "").strip()}

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


__all__ = ["build_online_shadow_plan", "diff_online_shadow_runs"]

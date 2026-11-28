import hashlib
import math
from typing import Any, TypedDict


class _ShadowSample(TypedDict):
    query_hash: str
    dataset_id_hash: str | None
    retrieval_config_hash: str | None
    rag_config: dict[str, Any]
    seed: Any
    sample_id: str


class _ShadowDeltas(TypedDict):
    answer_f1: float | None
    latency_ms: float | None
    token_cost: float | None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        num = float(value)
        if not math.isfinite(num):
            return None
        return num
    except (OverflowError, TypeError, ValueError):
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
    eligible: list[tuple[str, _ShadowSample]] = []
    for row in replay_records or []:
        if not isinstance(row, dict):
            continue
        raw_hash = row.get("query_hash")
        if raw_hash is None:
            continue
        query_hash = str(raw_hash).strip()
        if not query_hash:
            continue
        dataset_id_hash = row.get("dataset_id_hash")
        rank = _stable_rank(day_key=day_key.strip(), query_hash=query_hash, dataset_id_hash=dataset_id_hash or "")
        sample: _ShadowSample = {
            "query_hash": query_hash,
            "dataset_id_hash": dataset_id_hash,
            "retrieval_config_hash": row.get("retrieval_config_hash"),
            "rag_config": dict(row.get("rag_config") or {}),
            "seed": row.get("seed"),
            "sample_id": rank[:16],
        }
        eligible.append((rank, sample))

    limit = max(0, int(sample_size or 0))
    eligible.sort(key=lambda pair: pair[0])
    selected = [sample for _, sample in eligible[:limit]]

    return {
        "schema": "mimirq.online_shadow_plan.v1",
        "day_key": day_key,
        "summary": {
            "eligible": len(eligible),
            "selected": len(selected),
        },
        "sample_ids": [row["sample_id"] for row in selected],
        "samples": selected,
        "baseline": {"label": baseline_label},
        "candidate": {"label": candidate_label},
    }


def diff_online_shadow_runs(
    *,
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_by_id = {
        str(row["sample_id"]).strip(): dict(row)
        for row in baseline or []
        if row.get("sample_id") is not None and str(row["sample_id"]).strip()
    }
    candidate_by_id = {
        str(row["sample_id"]).strip(): dict(row)
        for row in candidate or []
        if row.get("sample_id") is not None and str(row["sample_id"]).strip()
    }

    shared_ids = sorted(baseline_by_id.keys() & candidate_by_id.keys())
    baseline_only = sorted(baseline_by_id.keys() - candidate_by_id.keys())
    candidate_only = sorted(candidate_by_id.keys() - baseline_by_id.keys())

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

        deltas: _ShadowDeltas = {
            "answer_f1": round(cand_answer_f1 - base_answer_f1, 4)
            if cand_answer_f1 is not None and base_answer_f1 is not None
            else None,
            "latency_ms": round(cand_latency - base_latency, 4)
            if cand_latency is not None and base_latency is not None
            else None,
            "token_cost": round(cand_cost - base_cost, 6) if cand_cost is not None and base_cost is not None else None,
        }
        if deltas["answer_f1"] is not None:
            answer_f1_deltas.append(deltas["answer_f1"])
        if deltas["latency_ms"] is not None:
            latency_deltas.append(deltas["latency_ms"])
        if deltas["token_cost"] is not None:
            token_cost_deltas.append(deltas["token_cost"])

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
            "compared": len(shared_ids),
            "candidate_only": len(candidate_only),
            "baseline_only": len(baseline_only),
            "answer_f1_delta_avg": _average(answer_f1_deltas),
            "latency_ms_delta_avg": _average(latency_deltas),
            "token_cost_delta_avg": _average(token_cost_deltas),
            "answer_f1_compared": len(answer_f1_deltas),
            "latency_ms_compared": len(latency_deltas),
            "token_cost_compared": len(token_cost_deltas),
        },
        "rows": rows,
        "candidate_only": candidate_only,
        "baseline_only": baseline_only,
    }


__all__ = ["build_online_shadow_plan", "diff_online_shadow_runs"]

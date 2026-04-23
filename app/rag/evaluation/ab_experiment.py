from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.rag.core.hashing import stable_hash


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


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / float(len(values)), 4)


def assign_ab_variant(
    *,
    experiment_key: str,
    tenant_id: str,
    user_id: str,
    variants: list[str],
) -> dict[str, Any]:
    normalized_variants = [str(item).strip() for item in list(variants or []) if str(item).strip()]
    if not normalized_variants:
        raise ValueError("variants_empty")

    seed = f"{experiment_key}|{tenant_id}|{user_id}"
    digest = stable_hash(seed, length=16)
    bucket = int(digest, 16) % len(normalized_variants)
    return {
        "schema": "mimirq.ab_assignment.v1",
        "experiment_key": str(experiment_key or "").strip(),
        "tenant_id": str(tenant_id or "").strip(),
        "user_id": str(user_id or "").strip(),
        "variant": normalized_variants[bucket],
        "bucket": int(bucket),
    }


def summarize_ab_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"faithfulness": [], "latency_ms": []})
    counts: dict[str, int] = defaultdict(int)

    for row in list(rows or []):
        variant = str((row or {}).get("variant") or "").strip()
        if not variant:
            continue
        counts[variant] += 1
        faithfulness = _to_float((row or {}).get("faithfulness"))
        latency_ms = _to_float((row or {}).get("latency_ms"))
        if faithfulness is not None:
            grouped[variant]["faithfulness"].append(faithfulness)
        if latency_ms is not None:
            grouped[variant]["latency_ms"].append(latency_ms)

    variants_out: dict[str, dict[str, Any]] = {}
    for variant in sorted(counts.keys()):
        variants_out[variant] = {
            "samples": int(counts[variant]),
            "faithfulness_avg": _average(grouped[variant]["faithfulness"]),
            "latency_ms_avg": _average(grouped[variant]["latency_ms"]),
        }

    return {
        "schema": "mimirq.ab_summary.v1",
        "variants": variants_out,
    }


__all__ = ["assign_ab_variant", "summarize_ab_results"]

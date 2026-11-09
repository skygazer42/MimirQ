from collections import defaultdict
from typing import Any


def summarize_stage1_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_ids = sorted({str(row["route_id"]) for row in rows if row.get("route_id") is not None and str(row["route_id"])})
    sample_count = len(rows)
    latency_values = [float(row.get("latency_ms") or 0.0) for row in rows]
    latency_avg = round(sum(latency_values) / len(latency_values), 4) if latency_values else 0.0

    by_query_type: dict[str, dict[str, Any]] = defaultdict(lambda: {"sample_count": 0})
    for row in rows or []:
        raw_type = row.get("query_type")
        if raw_type is None:
            continue
        query_type = str(raw_type)
        if not query_type:
            continue
        by_query_type[query_type]["sample_count"] += 1

    return {
        "routes_evaluated": route_ids,
        "overall": {
            "sample_count": sample_count,
            "route_ids": route_ids,
            "latency_ms_avg": latency_avg,
        },
        "by_query_type": dict(by_query_type),
    }

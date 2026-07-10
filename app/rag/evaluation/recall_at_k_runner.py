
from typing import Any


def _normalize_ids(values: list[Any] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value or "").strip()]


def _mrr(expected_ids: list[str], retrieved_ids: list[str], *, top_k: int) -> float:
    expected = set(expected_ids)
    for idx, item in enumerate(retrieved_ids[: max(1, int(top_k or 1))], start=1):
        if item in expected:
            return round(1.0 / float(idx), 4)
    return 0.0


def run_recall_at_k_runner(
    rows: list[dict[str, Any]],
    *,
    top_k: int,
    benchmark_name: str,
) -> dict[str, Any]:
    out_rows: list[dict[str, Any]] = []
    for row in rows or []:
        expected_ids = _normalize_ids((row or {}).get("expected_document_ids"))
        retrieved_ids = _normalize_ids((row or {}).get("retrieved_document_ids"))
        expected = set(expected_ids)
        retrieved_top_k = retrieved_ids[: max(1, int(top_k or 1))]
        recall = 0.0 if not expected else round(len(expected & set(retrieved_top_k)) / len(expected), 4)
        mrr = _mrr(expected_ids, retrieved_ids, top_k=top_k)
        out_rows.append(
            {
                "query_id": str((row or {}).get("query_id") or ""),
                "query": str((row or {}).get("query") or ""),
                "expected_document_ids": expected_ids,
                "retrieved_document_ids": retrieved_ids,
                "hit_at_k": 1.0 if recall > 0.0 else 0.0,
                "recall_at_k": recall,
                "mrr": mrr,
                "latency_ms": float((row or {}).get("latency_ms") or 0.0),
                "cost_usd": float((row or {}).get("cost_usd") or 0.0),
            }
        )

    count = max(1, len(out_rows))
    summary = {
        "query_count": len(out_rows),
        "recall_at_k_mean": round(sum(row["recall_at_k"] for row in out_rows) / count, 4) if out_rows else 0.0,
        "mrr_mean": round(sum(row["mrr"] for row in out_rows) / count, 4) if out_rows else 0.0,
        "avg_latency_ms": round(sum(row["latency_ms"] for row in out_rows) / count, 3) if out_rows else 0.0,
        "avg_cost_usd": round(sum(row["cost_usd"] for row in out_rows) / count, 6) if out_rows else 0.0,
    }
    return {
        "schema": "mimirq.recall_at_k_runner.v1",
        "benchmark_name": str(benchmark_name or "").strip(),
        "top_k": int(top_k or 0),
        "summary": summary,
        "rows": out_rows,
    }


__all__ = ["run_recall_at_k_runner"]

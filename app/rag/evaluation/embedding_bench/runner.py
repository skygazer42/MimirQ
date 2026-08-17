import math
from typing import Any

EMBEDDING_BENCHMARK_SCHEMA = "mimirq.embedding_benchmark.v1"


def _normalize_ids(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if item and item not in out:
            out.append(item)
    return out


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return float(default)
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return float(default)
        return number
    except Exception:
        return float(default)


def _lookup_metric(mapping: Any, query_id: str) -> float:
    if isinstance(mapping, dict):
        return _to_float(mapping.get(query_id), 0.0)
    return _to_float(mapping, 0.0)


def _mrr(expected_ids: list[str], retrieved_ids: list[str], *, top_k: int) -> float:
    expected = set(expected_ids)
    for index, item in enumerate(retrieved_ids[: max(1, int(top_k or 1))], start=1):
        if item in expected:
            return round(1.0 / float(index), 4)
    return 0.0


def _mean(values: list[float], *, digits: int = 4) -> float:
    if not values:
        return 0.0
    return round(sum(values) / float(len(values)), digits)


def _cosine(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size <= 0:
        return 0.0
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for index in range(size):
        lval = float(left[index])
        rval = float(right[index])
        dot += lval * rval
        left_sq += lval * lval
        right_sq += rval * rval
    denom = math.sqrt(left_sq) * math.sqrt(right_sq)
    if denom <= 0.0:
        return 0.0
    return float(dot / denom)


def rank_corpus_by_cosine(
    *,
    query_embedding: list[float],
    corpus_embeddings: dict[str, list[float]],
    top_k: int,
) -> list[str]:
    scored: list[tuple[str, float]] = []
    for doc_id, embedding in (corpus_embeddings or {}).items():
        did = str(doc_id or "").strip()
        if not did:
            continue
        scored.append((did, _cosine(list(query_embedding or []), list(embedding or []))))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [doc_id for doc_id, _score in scored[: max(1, int(top_k or 1))]]


def _resolve_retrieved_ids(*, query_id: str, model_run: dict[str, Any], top_k: int) -> list[str]:
    retrievals = model_run.get("retrievals") if isinstance(model_run.get("retrievals"), dict) else {}
    direct = retrievals.get(query_id)
    if direct is not None:
        return _normalize_ids(direct)[: max(1, int(top_k or 1))]

    query_embeddings = model_run.get("query_embeddings") if isinstance(model_run.get("query_embeddings"), dict) else {}
    corpus_embeddings = (
        model_run.get("corpus_embeddings") if isinstance(model_run.get("corpus_embeddings"), dict) else {}
    )
    query_embedding = query_embeddings.get(query_id)
    if isinstance(query_embedding, list) and corpus_embeddings:
        return rank_corpus_by_cosine(
            query_embedding=[_to_float(item) for item in query_embedding],
            corpus_embeddings={
                str(doc_id): [_to_float(item) for item in embedding or []]
                for doc_id, embedding in corpus_embeddings.items()
                if isinstance(embedding, list)
            },
            top_k=top_k,
        )
    return []


def run_embedding_benchmark(
    *,
    benchmark_name: str,
    cases: list[dict[str, Any]],
    model_runs: dict[str, dict[str, Any]],
    top_k: int = 10,
) -> dict[str, Any]:
    top_k_eff = max(1, int(top_k or 1))
    normalized_cases = [
        {
            "query_id": str((case or {}).get("query_id") or "").strip(),
            "query": str((case or {}).get("query") or ""),
            "expected_document_ids": _normalize_ids((case or {}).get("expected_document_ids")),
        }
        for case in cases or []
        if str((case or {}).get("query_id") or "").strip()
    ]

    model_rows: list[dict[str, Any]] = []
    for model_id in sorted((model_runs or {}).keys()):
        run = model_runs.get(model_id) if isinstance(model_runs.get(model_id), dict) else {}
        rows: list[dict[str, Any]] = []
        for case in normalized_cases:
            query_id = case["query_id"]
            expected_ids = list(case["expected_document_ids"])
            retrieved_ids = _resolve_retrieved_ids(query_id=query_id, model_run=run, top_k=top_k_eff)
            expected = set(expected_ids)
            retrieved_top_k = retrieved_ids[:top_k_eff]
            recall = 0.0 if not expected else round(len(expected & set(retrieved_top_k)) / float(len(expected)), 4)
            hit = 1.0 if recall > 0.0 else 0.0
            rows.append(
                {
                    "query_id": query_id,
                    "query": case["query"],
                    "expected_document_ids": expected_ids,
                    "retrieved_document_ids": retrieved_top_k,
                    "hit_at_k": hit,
                    "recall_at_k": recall,
                    "mrr": _mrr(expected_ids, retrieved_top_k, top_k=top_k_eff),
                    "latency_ms": _lookup_metric(run.get("latency_ms"), query_id),
                    "cost_usd": _lookup_metric(run.get("cost_usd"), query_id),
                }
            )

        summary = {
            "query_count": len(rows),
            "hit_at_k_mean": _mean([float(row["hit_at_k"]) for row in rows]),
            "recall_at_k_mean": _mean([float(row["recall_at_k"]) for row in rows]),
            "mrr_mean": _mean([float(row["mrr"]) for row in rows]),
            "avg_latency_ms": _mean([float(row["latency_ms"]) for row in rows], digits=3),
            "total_cost_usd": round(sum(float(row["cost_usd"]) for row in rows), 6),
        }
        model_rows.append(
            {
                "model_id": str(model_id),
                "summary": summary,
                "rows": rows,
            }
        )

    best = None
    best_key = None
    for index, row in enumerate(model_rows):
        summary = row["summary"]
        key = (
            float(summary["recall_at_k_mean"]),
            float(summary["mrr_mean"]),
            float(summary["hit_at_k_mean"]),
            -float(summary["avg_latency_ms"]),
            -index,
        )
        if best_key is None or key > best_key:
            best_key = key
            best = row

    return {
        "schema": EMBEDDING_BENCHMARK_SCHEMA,
        "benchmark_name": str(benchmark_name or "").strip(),
        "top_k": top_k_eff,
        "best_model_id": str((best or {}).get("model_id") or ""),
        "models": model_rows,
    }


__all__ = ["EMBEDDING_BENCHMARK_SCHEMA", "rank_corpus_by_cosine", "run_embedding_benchmark"]

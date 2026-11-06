from collections import Counter
from typing import Any

from app.rag.evaluation.datasets.schema import normalize_eval_dataset_sample


def build_stage3_manifest(
    *,
    dataset_name: str,
    rows: list[dict[str, Any]],
    dataset_version: str,
    generated_at: str,
) -> dict[str, Any]:
    normalized_rows = [normalize_eval_dataset_sample(row) for row in (rows or []) if isinstance(row, dict)]
    query_counts = Counter(row["query_type"] for row in normalized_rows)
    source_counts = Counter(row["source_type"] for row in normalized_rows)
    return {
        "dataset_name": str(dataset_name or "").strip() or "stage3-dataset",
        "schema_version": "mimirq.eval.dataset.manifest.v1",
        "dataset_version": str(dataset_version or "").strip() or "unknown",
        "sample_count": len(normalized_rows),
        "source_type_counts": dict(sorted(source_counts.items(), key=lambda kv: kv[0])),
        "query_type_counts": dict(sorted(query_counts.items(), key=lambda kv: kv[0])),
        "generated_at": str(generated_at or "").strip() or None,
    }


__all__ = ["build_stage3_manifest"]

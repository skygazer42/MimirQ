from collections import Counter
from typing import Any

from app.rag.evaluation.datasets.schema import EVAL_DATASET_MANIFEST_SCHEMA_V1, normalize_eval_dataset_sample


def build_stage3_manifest(
    *,
    dataset_name: str,
    rows: list[dict[str, Any]],
    dataset_version: str,
    generated_at: str,
) -> dict[str, Any]:
    query_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for raw_row in rows or []:
        if not isinstance(raw_row, dict):
            continue
        row = normalize_eval_dataset_sample(raw_row)
        query_counts[row["query_type"]] += 1
        source_counts[row["source_type"]] += 1
    return {
        "dataset_name": dataset_name.strip() or "stage3-dataset",
        "schema_version": EVAL_DATASET_MANIFEST_SCHEMA_V1,
        "dataset_version": dataset_version.strip() or "unknown",
        "sample_count": sum(query_counts.values()),
        "source_type_counts": dict(sorted(source_counts.items())),
        "query_type_counts": dict(sorted(query_counts.items())),
        "generated_at": generated_at,
    }


__all__ = ["build_stage3_manifest"]

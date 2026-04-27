from __future__ import annotations

from collections import Counter
from typing import Any

from app.rag.evaluation.datasets.schema import EVAL_DATASET_SCHEMA_V1, normalize_eval_dataset_sample

_QUERY_TYPES = {"factual", "multi_hop", "structured", "unanswerable"}
_SOURCE_TYPES = {"real_log", "manual_seed", "adversarial", "synthetic"}
_ROUTES = {"retrieval", "kg", "hybrid", "agentic"}
_ANNOTATION_STATUS = {"todo", "labeled", "reviewed"}
_REVIEW_STATUS = {"pending", "reviewed", "approved"}
_MANIFEST_SCHEMA = "mimirq.eval.dataset.manifest.v1"


def validate_eval_dataset(*, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    normalized_rows = [normalize_eval_dataset_sample(row) for row in (rows or []) if isinstance(row, dict)]

    sample_ids: set[str] = set()
    query_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for index, row in enumerate(normalized_rows, start=1):
        if row["schema_version"] != EVAL_DATASET_SCHEMA_V1:
            errors.append(f"row[{index}].schema_version invalid")
        if not row["sample_id"]:
            errors.append(f"row[{index}].sample_id missing")
        elif row["sample_id"] in sample_ids:
            errors.append(f"row[{index}].sample_id duplicated")
        else:
            sample_ids.add(row["sample_id"])
        if not row["query"]:
            errors.append(f"row[{index}].query missing")
        if row["query_type"] not in _QUERY_TYPES:
            errors.append(f"row[{index}].query_type invalid")
        if row["source_type"] not in _SOURCE_TYPES:
            errors.append(f"row[{index}].source_type invalid")
        if row["annotation_status"] not in _ANNOTATION_STATUS:
            errors.append(f"row[{index}].annotation_status invalid")
        if row["review_status"] not in _REVIEW_STATUS:
            errors.append(f"row[{index}].review_status invalid")
        if row["expected_route"] is not None and row["expected_route"] not in _ROUTES:
            errors.append(f"row[{index}].expected_route invalid")
        if not row["is_unanswerable"] and not isinstance(row["gold_chunk_ids"], list):
            errors.append(f"row[{index}].gold_chunk_ids invalid")

        query_counts[row["query_type"]] += 1
        source_counts[row["source_type"]] += 1

    if str(manifest.get("schema_version") or "").strip() != _MANIFEST_SCHEMA:
        errors.append("manifest.schema_version invalid")
    if int(manifest.get("sample_count") or 0) != len(normalized_rows):
        errors.append("manifest.sample_count mismatch")
    if dict(manifest.get("query_type_counts") or {}) != dict(query_counts):
        errors.append("manifest.query_type_counts mismatch")
    if dict(manifest.get("source_type_counts") or {}) != dict(source_counts):
        errors.append("manifest.source_type_counts mismatch")

    return {"ok": not errors, "errors": errors, "rows": normalized_rows}


__all__ = ["validate_eval_dataset"]

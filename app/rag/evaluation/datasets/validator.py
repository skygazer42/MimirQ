from collections import Counter
from typing import Any

from app.rag.evaluation.datasets.schema import (
    _ANNOTATION_STATUS,
    _QUERY_TYPES,
    _REVIEW_STATUS,
    _SOURCE_TYPES,
    EVAL_DATASET_MANIFEST_SCHEMA_V1,
    normalize_eval_dataset_sample,
)


def _validate_row(
    *,
    row: dict[str, Any],
    index: int,
    sample_ids: set[str],
    query_counts: Counter[str],
    source_counts: Counter[str],
    errors: list[str],
) -> None:
    row_prefix = f"row[{index}]"
    sample_id = row["sample_id"]
    if not sample_id:
        errors.append(f"{row_prefix}.sample_id missing")
    elif sample_id in sample_ids:
        errors.append(f"{row_prefix}.sample_id duplicated")
    else:
        sample_ids.add(sample_id)

    if not row["query"]:
        errors.append(f"{row_prefix}.query missing")

    for field, value, allowed in (
        ("query_type", row["query_type"], _QUERY_TYPES),
        ("source_type", row["source_type"], _SOURCE_TYPES),
        ("annotation_status", row["annotation_status"], _ANNOTATION_STATUS),
        ("review_status", row["review_status"], _REVIEW_STATUS),
    ):
        if value not in allowed:
            errors.append(f"{row_prefix}.{field} invalid")

    query_counts[row["query_type"]] += 1
    source_counts[row["source_type"]] += 1


def _validate_manifest(
    *,
    manifest: dict[str, Any],
    normalized_count: int,
    query_counts: Counter[str],
    source_counts: Counter[str],
    errors: list[str],
) -> None:
    if manifest.get("schema_version") != EVAL_DATASET_MANIFEST_SCHEMA_V1:
        errors.append("manifest.schema_version invalid")
    sample_count = manifest.get("sample_count")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        errors.append("manifest.sample_count invalid")
    elif sample_count != normalized_count:
        errors.append("manifest.sample_count mismatch")
    if manifest.get("query_type_counts") != dict(query_counts):
        errors.append("manifest.query_type_counts mismatch")
    if manifest.get("source_type_counts") != dict(source_counts):
        errors.append("manifest.source_type_counts mismatch")


def validate_eval_dataset(*, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    normalized_rows = []

    sample_ids: set[str] = set()
    query_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for index, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, dict):
            errors.append(f"row[{index}] must be an object")
            continue
        row = normalize_eval_dataset_sample(raw_row)
        normalized_rows.append(row)
        _validate_row(
            row=row,
            index=index,
            sample_ids=sample_ids,
            query_counts=query_counts,
            source_counts=source_counts,
            errors=errors,
        )

    _validate_manifest(
        manifest=manifest,
        normalized_count=len(normalized_rows),
        query_counts=query_counts,
        source_counts=source_counts,
        errors=errors,
    )

    return {"ok": not errors, "errors": errors, "rows": normalized_rows}


__all__ = ["validate_eval_dataset"]

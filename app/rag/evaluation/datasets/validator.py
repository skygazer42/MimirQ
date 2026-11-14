from collections import Counter
from typing import Any

from app.rag.evaluation.datasets.schema import (
    _ANNOTATION_STATUS,
    _QUERY_TYPES,
    _REVIEW_STATUS,
    _SOURCE_TYPES,
    normalize_eval_dataset_sample,
)

_MANIFEST_SCHEMA = "mimirq.eval.dataset.manifest.v1"


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
    if not row["sample_id"]:
        errors.append(f"{row_prefix}.sample_id missing")
    elif row["sample_id"] in sample_ids:
        errors.append(f"{row_prefix}.sample_id duplicated")
    else:
        sample_ids.add(row["sample_id"])

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
    normalized_rows: list[dict[str, Any]],
    query_counts: Counter[str],
    source_counts: Counter[str],
    errors: list[str],
) -> None:
    if manifest.get("schema_version") != _MANIFEST_SCHEMA:
        errors.append("manifest.schema_version invalid")
    if int(manifest.get("sample_count") or 0) != len(normalized_rows):
        errors.append("manifest.sample_count mismatch")
    if dict(manifest.get("query_type_counts") or {}) != dict(query_counts):
        errors.append("manifest.query_type_counts mismatch")
    if dict(manifest.get("source_type_counts") or {}) != dict(source_counts):
        errors.append("manifest.source_type_counts mismatch")


def validate_eval_dataset(*, rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    normalized_rows = [normalize_eval_dataset_sample(row) for row in (rows or []) if isinstance(row, dict)]

    sample_ids: set[str] = set()
    query_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    for index, row in enumerate(normalized_rows, start=1):
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
        normalized_rows=normalized_rows,
        query_counts=query_counts,
        source_counts=source_counts,
        errors=errors,
    )

    return {"ok": not errors, "errors": errors, "rows": normalized_rows}


__all__ = ["validate_eval_dataset"]

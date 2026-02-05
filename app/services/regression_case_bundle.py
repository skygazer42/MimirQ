from __future__ import annotations

from typing import Any, Iterable, Sequence
from uuid import UUID


REGRESSION_CASE_BUNDLE_SCHEMA_V1 = "mimirq.regression_cases.v1"


def export_case_bundle(cases: Sequence[Any], dataset_id: UUID) -> dict[str, Any]:
    """
    Export a dataset-scoped regression case bundle.

    Notes:
    - Omits internal identifiers (case id / tenant id) for portability.
    - Enforces all input cases belong to the provided dataset_id to avoid accidental cross-dataset mixes.
    """
    ds_id = UUID(str(dataset_id))

    items: list[dict[str, Any]] = []
    for case in cases or []:
        case_ds = getattr(case, "dataset_id", None)
        if case_ds is None or UUID(str(case_ds)) != ds_id:
            raise ValueError("All cases must belong to the same dataset_id")

        items.append(
            {
                "question": str(getattr(case, "question", "") or ""),
                "expected_answer": getattr(case, "expected_answer", None),
                "tags": list(getattr(case, "tags", []) or []),
                "reference_sources": list(getattr(case, "reference_sources", []) or []),
            }
        )

    # Stable ordering is useful for diffs/reviews.
    items.sort(key=lambda it: (it.get("question") or ""))

    return {
        "schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1,
        "dataset_id": str(ds_id),
        "items": items,
    }


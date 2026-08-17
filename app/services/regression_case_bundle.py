from collections.abc import Sequence
from typing import Any
from uuid import UUID

REGRESSION_CASE_BUNDLE_SCHEMA_V1 = "mimirq.regression_cases.v1"


def _coerce_bundle_item(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict):
        return dict(raw)
    return {
        "question": getattr(raw, "question", None),
        "expected_answer": getattr(raw, "expected_answer", None),
        "tags": getattr(raw, "tags", None),
        "reference_sources": getattr(raw, "reference_sources", None),
        "reasoning_hops": getattr(raw, "reasoning_hops", None),
        "evidence_chain": getattr(raw, "evidence_chain", None),
        "extra": getattr(raw, "extra", None),
    }


def _portable_extra(extra: Any) -> dict[str, Any]:
    if not isinstance(extra, dict):
        return {}
    out = dict(extra)
    out.pop("reasoning_hops", None)
    out.pop("evidence_chain", None)
    return out


def _is_review_only_local_sample_item(payload: dict[str, Any]) -> bool:
    extra = payload.get("extra")
    extra = extra if isinstance(extra, dict) else {}
    if extra.get("review_only") is True:
        return True
    return str(extra.get("reference_source_mode") or "").strip() == "local_sample_synthetic"


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
        extra = getattr(case, "extra", None)
        extra = extra if isinstance(extra, dict) else {}
        reasoning_hops = extra.get("reasoning_hops")
        if isinstance(reasoning_hops, list):
            hops = [str(x) for x in reasoning_hops if str(x or "").strip()]
            if hops:
                items[-1]["reasoning_hops"] = hops[:20]
        evidence_chain = extra.get("evidence_chain")
        if isinstance(evidence_chain, list):
            chain = [x for x in evidence_chain if isinstance(x, dict)]
            if chain:
                items[-1]["evidence_chain"] = chain[:20]
        portable_extra = _portable_extra(extra)
        if portable_extra:
            items[-1]["extra"] = portable_extra

    # Stable ordering is useful for diffs/reviews.
    items.sort(key=lambda it: it.get("question") or "")

    return {
        "schema": REGRESSION_CASE_BUNDLE_SCHEMA_V1,
        "dataset_id": str(ds_id),
        "items": items,
    }


def plan_case_import(
    *,
    dataset_id: UUID,
    existing_questions: set[str],
    items: Sequence[Any],
    overwrite: bool = False,
    max_items: int = 500,
) -> dict[str, Any]:
    """
    Plan case upserts using (dataset_id + question.strip()) as a stable key.

    Returns counts plus `create_items`/`update_items` for the API layer.
    """
    _ = UUID(str(dataset_id))  # ensure UUID-compatible input
    cap = max(1, min(2000, int(max_items or 0))) if max_items else 500

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    create_items: list[dict[str, Any]] = []
    update_items: list[dict[str, Any]] = []
    skipped_existing_questions: list[str] = []

    seen: set[str] = set()

    for idx, raw in enumerate(list(items or [])[:cap]):
        payload = _coerce_bundle_item(raw)
        question = str(payload.get("question") or "").strip()
        if not question:
            skipped += 1
            errors.append({"index": idx, "error": "question is required"})
            continue

        if question in seen:
            skipped += 1
            errors.append({"index": idx, "question": question, "error": "duplicate question in import batch"})
            continue
        seen.add(question)

        payload["question"] = question

        if _is_review_only_local_sample_item(payload):
            skipped += 1
            errors.append(
                {
                    "index": idx,
                    "question": question,
                    "error": (
                        "review_only local sample Golden items cannot be imported; generate dataset "
                        "goldens from indexed chunks"
                    ),
                }
            )
            continue

        if question in existing_questions:
            if overwrite:
                updated += 1
                update_items.append(payload)
            else:
                skipped += 1
                skipped_existing_questions.append(question)
            continue

        created += 1
        create_items.append(payload)

    # If input is larger than cap, treat remaining items as skipped.
    if items and len(items) > cap:
        skipped += len(items) - cap
        errors.append({"error": "max_items exceeded", "max_items": cap, "ignored": len(items) - cap})

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "create_items": create_items,
        "update_items": update_items,
        "skipped_existing_questions": skipped_existing_questions,
    }

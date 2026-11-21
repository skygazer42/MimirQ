"""Import regression cases and normalize their reasoning metadata."""

from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

import app.services.datasets.management as dataset_service
from app.api.schemas.evaluation import RagasRegressionCaseImportRequest, StoredReferenceSource
from app.models.evaluation.results import RagasRegressionCase
from app.services.evaluation.case_bundle import plan_case_import
from app.services.evaluation.reference_sources import finalize_reference_sources


def normalize_reasoning_hops(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue
        out.append(text[:300])
        if len(out) >= 20:
            break
    return out


def normalize_evidence_chain(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="evidence_chain must be a list")
    return [_normalize_evidence_item(item) for item in raw[:20]]


def _normalize_evidence_item(item: Any) -> dict[str, Any]:
    try:
        source = StoredReferenceSource.model_validate(item)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid evidence_chain reference") from exc
    return source.model_dump(mode="json", exclude_unset=True)


def merge_regression_case_extra(
    *,
    base_extra: Any,
    reasoning_hops: Any,
    evidence_chain: Any,
) -> dict[str, Any]:
    extra = dict(base_extra) if isinstance(base_extra, dict) else {}
    hops = normalize_reasoning_hops(reasoning_hops)
    chain = normalize_evidence_chain(evidence_chain)
    if hops:
        extra["reasoning_hops"] = hops
    else:
        extra.pop("reasoning_hops", None)
    if chain:
        extra["evidence_chain"] = chain
    else:
        extra.pop("evidence_chain", None)
    return extra


def import_regression_cases(
    payload: RagasRegressionCaseImportRequest,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> dict[str, Any]:
    """Import (upsert) regression cases by (dataset_id + question.strip())."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, payload.dataset_id)
    dataset_service.assert_dataset_writable(db, ds, account_id)

    existing = (
        db.query(RagasRegressionCase)
        .filter(
            RagasRegressionCase.tenant_id == tenant_id,
            RagasRegressionCase.dataset_id == payload.dataset_id,
        )
        .all()
    )
    by_question = {row.question.strip(): row for row in existing if row.question}

    plan = plan_case_import(
        existing_questions=set(by_question.keys()),
        items=payload.items,
        overwrite=bool(payload.overwrite),
        max_items=payload.max_items,
    )

    skipped = plan["skipped"]
    errors: list[dict[str, Any]] = list(plan["errors"])
    skipped_case_ids = [by_question[question].id for question in plan["skipped_existing_questions"]]

    created_case_ids, create_skipped, create_errors = _import_new_regression_cases(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        items=plan["create_items"],
    )
    updated_case_ids, update_skipped, update_errors = _import_existing_regression_cases(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=payload.dataset_id,
        by_question=by_question,
        items=plan["update_items"],
    )
    skipped += create_skipped + update_skipped
    errors.extend(create_errors)
    errors.extend(update_errors)

    db.flush()
    db.commit()

    return {
        "created": len(created_case_ids),
        "updated": len(updated_case_ids),
        "skipped": skipped,
        "errors": errors,
        "created_case_ids": created_case_ids,
        "updated_case_ids": updated_case_ids,
        "skipped_case_ids": skipped_case_ids,
        "case_ids": [*created_case_ids, *updated_case_ids, *skipped_case_ids],
    }


def _import_new_regression_cases(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    items: list[dict[str, Any]],
) -> tuple[list[UUID], int, list[dict[str, Any]]]:
    created_case_ids: list[UUID] = []
    skipped = 0
    errors: list[dict[str, Any]] = []
    for item in items:
        try:
            reference_sources = finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                reference_sources=item["reference_sources"],
            )
            case_id = uuid4()
            row = RagasRegressionCase(
                id=case_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                question=item["question"],
                expected_answer=item["expected_answer"],
                reference_sources=reference_sources,
                tags=item["tags"],
                extra=merge_regression_case_extra(
                    base_extra=item["extra"],
                    reasoning_hops=item["reasoning_hops"],
                    evidence_chain=item["evidence_chain"],
                ),
                created_by=account_id,
            )
            db.add(row)
            created_case_ids.append(case_id)
        except HTTPException as exc:
            skipped += 1
            errors.append({"question": item["question"], "error": exc.detail})
    return created_case_ids, skipped, errors


def _import_existing_regression_cases(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    by_question: dict[str, RagasRegressionCase],
    items: list[dict[str, Any]],
) -> tuple[list[UUID], int, list[dict[str, Any]]]:
    updated_case_ids: list[UUID] = []
    skipped = 0
    errors: list[dict[str, Any]] = []
    for item in items:
        question = item["question"]
        row = by_question[question]
        try:
            _update_imported_regression_case(
                db=db,
                row=row,
                item=item,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
            )
            updated_case_ids.append(row.id)
        except HTTPException as exc:
            skipped += 1
            errors.append({"question": question, "error": exc.detail})
    return updated_case_ids, skipped, errors


def _update_imported_regression_case(
    *,
    db: Session,
    row: RagasRegressionCase,
    item: dict[str, Any],
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
) -> None:
    reference_sources = finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        reference_sources=item["reference_sources"],
    )
    merged_base_extra = dict(row.extra) if isinstance(row.extra, dict) else {}
    merged_base_extra.update(item["extra"])
    merged_extra = merge_regression_case_extra(
        base_extra=merged_base_extra,
        reasoning_hops=item["reasoning_hops"],
        evidence_chain=item["evidence_chain"],
    )
    row.expected_answer = item["expected_answer"]
    row.tags = item["tags"]
    row.reference_sources = reference_sources
    row.extra = merged_extra
    db.add(row)

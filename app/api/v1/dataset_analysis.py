from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.datasets import (
    DatasetAnalysisDashboardQuery,
    DatasetAnalysisExamplesQuery,
    DatasetAnalysisQuery,
    DatasetAnalysisRulesQuery,
    DatasetAnalysisWritebackQuery,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import dataset_analysis_service as analysis_service
from app.services import dataset_service

if TYPE_CHECKING:
    from app.models.dataset import Dataset

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _require_dataset_readable(*, db: Session, tenant_id: UUID, dataset_id: UUID, account_id: str) -> "Dataset":
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)
    return dataset


def _require_dataset_writable(*, db: Session, tenant_id: UUID, dataset_id: UUID, account_id: str) -> "Dataset":
    dataset_service.ensure_member(db, tenant_id, account_id)
    dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_writable(db, dataset, account_id)
    return dataset


def _get_png_task_status(*, task_id: str, tenant_id: UUID, dataset_id: UUID, account_id: str) -> dict[str, Any]:
    try:
        return analysis_service.get_dataset_analysis_png_task_status(
            task_id=task_id, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="PNG export task not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="PNG export task state unavailable") from exc


@router.get("/analysis/dashboard")
def get_tenant_dataset_analysis_dashboard(
    query: Annotated[DatasetAnalysisDashboardQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the tenant-level dataset analysis dashboard."""
    dataset_service.ensure_member(db, tenant_id, account_id)
    return analysis_service.build_tenant_dataset_analysis_dashboard(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        limit=query.limit,
    )


@router.get("/{dataset_id}/analysis/summary")
def get_dataset_analysis_summary(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return an analysis summary for one dataset."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    return analysis_service.build_dataset_analysis_summary(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        category=query.category,
    )


@router.get("/{dataset_id}/analysis/examples")
def get_dataset_analysis_examples(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisExamplesQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return representative analysis examples for one dataset."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    return analysis_service.build_dataset_analysis_examples(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        category=query.category,
        limit=query.limit,
    )


@router.get("/{dataset_id}/analysis/rule-suggestions")
def get_dataset_analysis_rule_suggestions(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisRulesQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return glossary and rule suggestions for dataset analysis."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    return analysis_service.build_dataset_analysis_rule_suggestions(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        ruleset_name=query.ruleset,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        limit=query.limit,
    )


@router.get("/{dataset_id}/analysis/export.json")
def export_dataset_analysis_json_endpoint(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export dataset analysis as JSON."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    return analysis_service.export_dataset_analysis_json(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        category=query.category,
    )


@router.get("/{dataset_id}/analysis/export.jsonl")
def export_dataset_analysis_jsonl_endpoint(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export dataset analysis as newline-delimited JSON."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    payload = analysis_service.export_dataset_analysis_jsonl(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        category=query.category,
    )
    return Response(content=payload, media_type="application/x-ndjson")


@router.get("/{dataset_id}/analysis/report.html")
def export_dataset_analysis_html_endpoint(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export dataset analysis as an HTML report."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    payload = analysis_service.export_dataset_analysis_html(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        category=query.category,
    )
    return Response(content=payload, media_type="text/html")


@router.post("/{dataset_id}/analysis/glossary-writeback")
def writeback_dataset_analysis_glossary_endpoint(
    dataset_id: UUID,
    query: Annotated[DatasetAnalysisWritebackQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Write suggested glossary entries back to a ruleset."""
    dataset = _require_dataset_writable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    return analysis_service.writeback_dataset_analysis_glossary_candidates(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=dataset.name,
        ruleset_name=query.ruleset,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        feedback_polarity=query.feedback_polarity,
        category=query.category,
        limit=query.limit,
    )


@router.post("/{dataset_id}/analysis/export.png", status_code=202)
def create_dataset_analysis_png_task_endpoint(
    dataset_id: UUID,
    background_tasks: BackgroundTasks,
    query: Annotated[DatasetAnalysisQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create an asynchronous PNG export task for dataset analysis."""
    dataset = _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    try:
        return analysis_service.create_dataset_analysis_png_task(
            db=db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            dataset_name=dataset.name,
            account_id=account_id,
            background_tasks=background_tasks,
            from_ts=query.from_ts,
            to_ts=query.to_ts,
            feedback_polarity=query.feedback_polarity,
            category=query.category,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="PNG export task state unavailable") from exc


@router.get("/{dataset_id}/analysis/export-tasks/{task_id}")
def get_dataset_analysis_png_task_endpoint(
    dataset_id: UUID,
    task_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the status of a dataset analysis PNG export task."""
    _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    return _get_png_task_status(task_id=task_id, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)


@router.get("/{dataset_id}/analysis/export-tasks/{task_id}/result.png")
def get_dataset_analysis_png_task_result_endpoint(
    dataset_id: UUID,
    task_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the PNG result for a completed dataset analysis export task."""
    _require_dataset_readable(db=db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    status = _get_png_task_status(task_id=task_id, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id)
    if status["status"] != "done":
        raise HTTPException(status_code=409, detail="PNG export task is not finished")
    try:
        payload = analysis_service.get_dataset_analysis_png_result(
            task_id=task_id, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="PNG export task result not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="PNG export task state unavailable") from exc
    return Response(content=payload, media_type="image/png")

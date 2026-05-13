from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.dataset_analysis_service import (
    build_dataset_analysis_examples,
    build_dataset_analysis_rule_suggestions,
    build_dataset_analysis_summary,
    build_tenant_dataset_analysis_dashboard,
    create_dataset_analysis_png_task,
    export_dataset_analysis_html,
    export_dataset_analysis_json,
    export_dataset_analysis_jsonl,
    get_dataset_analysis_png_result,
    get_dataset_analysis_png_task_status,
    writeback_dataset_analysis_glossary_candidates,
)
from app.services.dataset_service import DatasetService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/analysis/dashboard", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_tenant_dataset_analysis_dashboard(
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the tenant-level dataset analysis dashboard."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    return build_tenant_dataset_analysis_dashboard(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        limit=limit,
    )


@router.get("/{dataset_id}/analysis/summary", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_analysis_summary(
    dataset_id: UUID,
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return an analysis summary for one dataset."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    return build_dataset_analysis_summary(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
    )


@router.get("/{dataset_id}/analysis/examples", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_analysis_examples(
    dataset_id: UUID,
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return representative analysis examples for one dataset."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    return build_dataset_analysis_examples(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=limit,
    )


@router.get("/{dataset_id}/analysis/rule-suggestions", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_analysis_rule_suggestions(
    dataset_id: UUID,
    ruleset: Annotated[str, Query(min_length=1)],
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return glossary and rule suggestions for dataset analysis."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    return build_dataset_analysis_rule_suggestions(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        ruleset_name=ruleset,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        limit=limit,
    )


@router.get("/{dataset_id}/analysis/export.json", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_analysis_json_endpoint(
    dataset_id: UUID,
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export dataset analysis as JSON."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    return export_dataset_analysis_json(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
    )


@router.get("/{dataset_id}/analysis/export.jsonl", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_analysis_jsonl_endpoint(
    dataset_id: UUID,
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export dataset analysis as newline-delimited JSON."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    payload = export_dataset_analysis_jsonl(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
    )
    return Response(content=payload, media_type="application/x-ndjson")


@router.get("/{dataset_id}/analysis/report.html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_analysis_html_endpoint(
    dataset_id: UUID,
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Export dataset analysis as an HTML report."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    payload = export_dataset_analysis_html(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
    )
    return Response(content=payload, media_type="text/html")


@router.post("/{dataset_id}/analysis/glossary-writeback", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def writeback_dataset_analysis_glossary_endpoint(
    dataset_id: UUID,
    ruleset: Annotated[str, Query(min_length=1)],
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Write suggested glossary entries back to a ruleset."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    return writeback_dataset_analysis_glossary_candidates(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        ruleset_name=ruleset,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
        limit=limit,
    )


@router.post("/{dataset_id}/analysis/export.png", status_code=202, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def create_dataset_analysis_png_task_endpoint(
    dataset_id: UUID,
    background_tasks: BackgroundTasks,
    from_ts: Annotated[str | None, Query()] = None,
    to_ts: Annotated[str | None, Query()] = None,
    feedback_polarity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create an asynchronous PNG export task for dataset analysis."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
    return create_dataset_analysis_png_task(
        db=db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        dataset_name=str(getattr(dataset, "name", "") or ""),
        background_tasks=background_tasks,
        from_ts=from_ts,
        to_ts=to_ts,
        feedback_polarity=feedback_polarity,
        category=category,
    )


@router.get("/{dataset_id}/analysis/export-tasks/{task_id}", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_analysis_png_task_endpoint(
    dataset_id: UUID,
    task_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the status of a dataset analysis PNG export task."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    DatasetService.get_dataset(db, tenant_id, dataset_id)
    return get_dataset_analysis_png_task_status(task_id=task_id)


@router.get("/{dataset_id}/analysis/export-tasks/{task_id}/result.png", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_analysis_png_task_result_endpoint(
    dataset_id: UUID,
    task_id: str,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Return the PNG result for a completed dataset analysis export task."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    DatasetService.get_dataset(db, tenant_id, dataset_id)
    status = get_dataset_analysis_png_task_status(task_id=task_id)
    if str(status.get("status") or "") != "done":
        raise HTTPException(status_code=409, detail="PNG export task is not finished")
    payload = get_dataset_analysis_png_result(task_id=task_id)
    return Response(content=payload, media_type="image/png")

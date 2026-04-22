from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.dataset_analysis_service import (
    build_dataset_analysis_examples,
    build_dataset_analysis_summary,
    export_dataset_analysis_json,
    export_dataset_analysis_jsonl,
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

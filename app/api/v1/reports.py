"""Reports API.

Provides exportable, shareable dataset-level bundles (quality + compliance).
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.report import DatasetReportOut
from app.core.database import get_db
from app.services.report_html import render_dataset_report_html
from app.services.report_service import ReportService

router = APIRouter()


@router.get("/datasets/{dataset_id}", response_model=DatasetReportOut)
def get_dataset_report(
    dataset_id: UUID,
    pipeline_hash: str | None = Query(default=None, max_length=64, description="Optional: filter by pipeline_hash (active)"),
    connector_runs_limit: int = Query(default=20, ge=0, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    return ReportService.build_dataset_report(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        connector_runs_limit=int(connector_runs_limit or 0),
    )


@router.get("/datasets/{dataset_id}/export")
def export_dataset_report_json(
    dataset_id: UUID,
    pipeline_hash: str | None = Query(default=None, max_length=64),
    connector_runs_limit: int = Query(default=20, ge=0, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    report = ReportService.build_dataset_report(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        connector_runs_limit=int(connector_runs_limit or 0),
    )
    content = json.dumps(report.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.report{suffix}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/datasets/{dataset_id}/export-html")
def export_dataset_report_html(
    dataset_id: UUID,
    pipeline_hash: str | None = Query(default=None, max_length=64),
    connector_runs_limit: int = Query(default=20, ge=0, le=100),
    redact: bool = Query(default=True, description="Whether to redact dataset name/id for sharing"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    report = ReportService.build_dataset_report(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        connector_runs_limit=int(connector_runs_limit or 0),
    )

    html = render_dataset_report_html(
        title="MimirQ · 数据集报告中心（质量 + 合规）",
        dataset_name=str(report.dataset_name or ""),
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=bool(redact),
    )

    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.report{suffix}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

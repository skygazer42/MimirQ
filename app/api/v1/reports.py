"""Reports API.

Provides exportable, shareable dataset-level bundles (quality + compliance).
"""

import io
import json
import re
import zipfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.evaluation import (
    DatasetReportExportQuery,
    DatasetReportOut,
    DatasetReportQuery,
    DatasetReportSharedExportQuery,
)
from app.api.utils import (
    DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
from app.api.utils import file_response_headers
from app.core.database import get_db
from app.rag.core.logging import get_logger
from app.services import report_service
from app.services.report_html import _scrub_report_for_redaction, render_dataset_report_html, render_rag_audit_html
from app.services.report_service import DatasetReportRequest

if TYPE_CHECKING:
    from app.models.evaluation import RagasRegressionRun

logger = get_logger(__name__)

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SAFE_DATASET_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _build_report(
    db: Session,
    dataset_id: UUID,
    *,
    tenant_id: UUID,
    account_id: str,
    query: DatasetReportQuery | DatasetReportExportQuery,
) -> DatasetReportOut:
    return report_service.build_dataset_report(
        db,
        request=DatasetReportRequest(
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            pipeline_hash=query.pipeline_hash,
            connector_runs_limit=query.connector_runs_limit,
        ),
    )


def _json_compact(payload: object, *, default: Callable[[object], object] | None = None) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=default)


def _report_filename(
    *,
    dataset_name: str | None,
    pipeline_hash: str | None,
    stem: str,
    suffix: str,
    redact: bool = False,
) -> str:
    if redact:
        return f"dataset.{stem}.{suffix}"
    prefix = _SAFE_DATASET_NAME_RE.sub("_", dataset_name or "dataset")[:64]
    pipeline_suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    return f"{prefix}.{stem}{pipeline_suffix}.{suffix}"


def _report_bundle_manifest(
    *,
    report: DatasetReportOut,
    dataset_id: UUID,
    pipeline_hash: str | None,
    files: list[str],
    redact: bool,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema": "mimirq.report_bundle.v2",
        "generated_at": report.generated_at.isoformat(),
        "redact": redact,
        "files": files,
    }
    if redact:
        manifest["dataset"] = {"redacted": True}
    else:
        manifest["dataset_id"] = str(dataset_id)
        manifest["dataset_name"] = report.dataset_name
        manifest["pipeline_hash"] = pipeline_hash
    return manifest


def _regression_run_payload(row: "RagasRegressionRun") -> dict[str, object]:
    return {
        "run_id": str(row.id),
        "status": row.status,
        "params": row.params or {},
        "summary": row.summary or {},
        "created_at": row.created_at,
        "finished_at": row.finished_at,
    }


def _regression_diff_artifacts(base: "RagasRegressionRun", target: "RagasRegressionRun") -> dict[str, str]:
    from app.services.regression_run_diff import diff_regression_run_summaries
    from app.services.regression_run_diff_html import render_regression_run_diff_html

    base_summary = base.summary
    target_summary = target.summary
    if not isinstance(base_summary, dict) or not isinstance(target_summary, dict):
        return {}
    if not base_summary or not target_summary:
        return {}

    diff_payload = diff_regression_run_summaries(
        base_run_id=base.id,
        target_run_id=target.id,
        base_summary=base_summary,
        target_summary=target_summary,
        max_slice_buckets=40,
    )
    diff_payload["base_params"] = base.params or {}
    diff_payload["target_params"] = target.params or {}

    return {
        "regression_diff.json": _json_compact(diff_payload, default=str),
        "regression_diff.html": render_regression_run_diff_html(
            title="MimirQ · Regression Run Diff（Baseline vs Latest）",
            base_run_id=str(base.id),
            target_run_id=str(target.id),
            generated_at=diff_payload["generated_at"],
            diff=diff_payload,
        ),
    }


def _regression_bundle_artifacts(db: Session, dataset_id: UUID, *, tenant_id: UUID, redact: bool) -> dict[str, str]:
    if redact:
        return {}
    try:
        from app.models.evaluation import RagasRegressionRun

        rows = (
            db.query(RagasRegressionRun)
            .filter(
                RagasRegressionRun.tenant_id == tenant_id,
                RagasRegressionRun.dataset_id == dataset_id,
                RagasRegressionRun.status == "completed",
            )
            .order_by(RagasRegressionRun.created_at.desc())
            .limit(2)
            .all()
        )
    except Exception as exc:
        logger.debug("Failed to add regression diff files to report bundle: %s", exc, exc_info=True)
        return {}

    if not rows:
        return {}

    target = rows[0]
    artifacts = {"regression_latest.json": _json_compact(_regression_run_payload(target), default=str)}
    if len(rows) > 1:
        base = rows[1]
        artifacts["regression_baseline.json"] = _json_compact(_regression_run_payload(base), default=str)
        artifacts.update(_regression_diff_artifacts(base, target))
    return artifacts


@router.get("/datasets/{dataset_id}", response_model=DatasetReportOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_report(
    dataset_id: UUID,
    query: Annotated[DatasetReportQuery, Query()],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DatasetReportOut:
    return _build_report(db, dataset_id, tenant_id=tenant_id, account_id=account_id, query=query)


@router.get("/datasets/{dataset_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_json(
    dataset_id: UUID,
    query: Annotated[DatasetReportExportQuery, Query()],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    report = _build_report(db, dataset_id, tenant_id=tenant_id, account_id=account_id, query=query)
    content = _json_compact(report.model_dump(mode="json"))
    filename = _report_filename(
        dataset_name=report.dataset_name, pipeline_hash=query.pipeline_hash, stem="report", suffix="json"
    )
    return Response(
        content=content,
        media_type="application/json",
        headers=file_response_headers(filename),
    )


@router.get("/datasets/{dataset_id}/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_html(
    dataset_id: UUID,
    query: Annotated[DatasetReportSharedExportQuery, Query()],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    report = _build_report(db, dataset_id, tenant_id=tenant_id, account_id=account_id, query=query)

    html = render_dataset_report_html(
        title="MimirQ · 数据集报告中心（质量 + 合规）",
        dataset_name=report.dataset_name,
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=query.redact,
    )

    filename = _report_filename(
        dataset_name=report.dataset_name,
        pipeline_hash=query.pipeline_hash,
        stem="report",
        suffix="html",
        redact=query.redact,
    )
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=file_response_headers(filename),
    )


@router.get("/datasets/{dataset_id}/rag-audit/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_rag_audit_html(
    dataset_id: UUID,
    query: Annotated[DatasetReportSharedExportQuery, Query()],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    report = _build_report(db, dataset_id, tenant_id=tenant_id, account_id=account_id, query=query)

    html = render_rag_audit_html(
        title="MimirQ · RAG Audit（Profile + Governance + Chunk + KG + Eval）",
        dataset_name=report.dataset_name,
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=query.redact,
    )

    filename = _report_filename(
        dataset_name=report.dataset_name,
        pipeline_hash=query.pipeline_hash,
        stem="rag_audit",
        suffix="html",
        redact=query.redact,
    )
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=file_response_headers(filename),
    )


@router.get("/datasets/{dataset_id}/export-bundle", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_bundle_zip(
    dataset_id: UUID,
    query: Annotated[DatasetReportSharedExportQuery, Query()],
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """
    One-click export bundle (zip) containing:
    - report.json (redacted when redact=true)
    - report.html
    - rag_audit.html
    - manifest.json
    """
    report = _build_report(db, dataset_id, tenant_id=tenant_id, account_id=account_id, query=query)

    report_data = report.model_dump(mode="json")
    bundle_report_data = report_data
    if query.redact:
        bundle_report_data = _scrub_report_for_redaction(report_data)
        # Keep safe aggregate summaries that are useful for shareable audit bundles.
        for key in ("must_recall_summary", "hierarchy_recall_summary"):
            summary = report_data[key]
            if summary is not None:
                bundle_report_data[key] = summary

    report_json = _json_compact(bundle_report_data)

    report_html = render_dataset_report_html(
        title="MimirQ · 数据集报告中心（质量 + 合规）",
        dataset_name=report.dataset_name,
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report_data,
        redact=query.redact,
    )
    rag_audit_html = render_rag_audit_html(
        title="MimirQ · RAG Audit（Profile + Governance + Chunk + KG + Eval）",
        dataset_name=report.dataset_name,
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report_data,
        redact=query.redact,
    )

    artifacts = _regression_bundle_artifacts(db, dataset_id, tenant_id=tenant_id, redact=query.redact)
    files = ["manifest.json", "report.json", "report.html", "rag_audit.html", *artifacts]
    manifest = _report_bundle_manifest(
        report=report,
        dataset_id=dataset_id,
        pipeline_hash=query.pipeline_hash,
        files=files,
        redact=query.redact,
    )

    bundle_entries = [
        ("manifest.json", _json_compact(manifest)),
        ("report.json", report_json),
        ("report.html", report_html),
        ("rag_audit.html", rag_audit_html),
        *artifacts.items(),
    ]
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for artifact_name, artifact_content in bundle_entries:
                archive.writestr(artifact_name, artifact_content)
        content = buffer.getvalue()

    filename = _report_filename(
        dataset_name=report.dataset_name,
        pipeline_hash=query.pipeline_hash,
        stem="report_bundle",
        suffix="zip",
        redact=query.redact,
    )
    return Response(
        content=content,
        media_type="application/zip",
        headers=file_response_headers(filename),
    )

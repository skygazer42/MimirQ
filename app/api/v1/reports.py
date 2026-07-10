"""Reports API.

Provides exportable, shareable dataset-level bundles (quality + compliance).
"""


import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.report import DatasetReportOut
from app.api.utils.response_headers import download_response_headers
from app.core.database import get_db
from app.rag.core.logging import get_logger
from app.services.report_html import _scrub_report_for_redaction, render_dataset_report_html, render_rag_audit_html
from app.services.report_service import DatasetReportRequest, ReportService

logger = get_logger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SAFE_DATASET_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True)
class ReportContext:
    tenant_id: UUID
    account_id: str
    db: Session


def _get_report_context(
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ReportContext:
    return ReportContext(tenant_id=tenant_id, account_id=account_id, db=db)


ReportContextDep = Annotated[ReportContext, Depends(_get_report_context)]


def _build_report(
    context: ReportContext,
    *,
    dataset_id: UUID,
    pipeline_hash: str | None,
    connector_runs_limit: int,
) -> DatasetReportOut:
    return ReportService.build_dataset_report(
        context.db,
        request=DatasetReportRequest(
            tenant_id=context.tenant_id,
            account_id=context.account_id,
            dataset_id=dataset_id,
            pipeline_hash=pipeline_hash,
            connector_runs_limit=int(connector_runs_limit or 0),
        ),
    )


def _json_compact(payload: object, *, default: object | None = None) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=default)


def _regression_run_payload(row: object) -> dict:
    return {
        "run_id": str(getattr(row, "id", "")),
        "status": str(getattr(row, "status", "")),
        "params": dict(getattr(row, "params", None) or {}),
        "summary": dict(getattr(row, "summary", None) or {}),
        "created_at": getattr(row, "created_at", None),
        "finished_at": getattr(row, "finished_at", None),
    }


def _redact_regression_diff(diff_payload: dict) -> dict:
    redacted = dict(diff_payload)
    slice_diffs = redacted.get("slice_diffs")
    if isinstance(slice_diffs, dict) and "directory" in slice_diffs:
        slice_diffs = dict(slice_diffs)
        slice_diffs["directory"] = {"truncated_before": True, "truncated_after": True, "buckets": []}
        redacted["slice_diffs"] = slice_diffs
    redacted["base_run_id"] = "[REDACTED]"
    redacted["target_run_id"] = "[REDACTED]"
    return redacted


def _regression_diff_artifacts(base: object, target: object, *, redact: bool) -> dict[str, str]:
    from app.services.regression_run_diff import diff_regression_run_summaries
    from app.services.regression_run_diff_html import render_regression_run_diff_html

    base_summary = getattr(base, "summary", None)
    target_summary = getattr(target, "summary", None)
    base_summary = base_summary if isinstance(base_summary, dict) else {}
    target_summary = target_summary if isinstance(target_summary, dict) else {}
    if not base_summary or not target_summary:
        return {}

    diff_payload = diff_regression_run_summaries(
        base_run_id=base.id,
        target_run_id=target.id,
        base_summary=base_summary,
        target_summary=target_summary,
        max_slice_buckets=40,
    )
    diff_payload["base_params"] = dict(getattr(base, "params", None) or {})
    diff_payload["target_params"] = dict(getattr(target, "params", None) or {})
    if redact:
        diff_payload = _redact_regression_diff(diff_payload)

    return {
        "regression_diff.json": _json_compact(diff_payload, default=str),
        "regression_diff.html": render_regression_run_diff_html(
            title="MimirQ · Regression Run Diff（Baseline vs Latest）",
            base_run_id=str(getattr(base, "id", "")),
            target_run_id=str(getattr(target, "id", "")),
            generated_at=diff_payload.get("generated_at"),
            diff=diff_payload,
            redact=redact,
        ),
    }


def _regression_bundle_artifacts(context: ReportContext, dataset_id: UUID, *, redact: bool) -> dict[str, str]:
    try:
        from app.models.evaluation import RagasRegressionRun

        rows = (
            context.db.query(RagasRegressionRun)
            .filter(
                RagasRegressionRun.tenant_id == context.tenant_id,
                RagasRegressionRun.dataset_id == dataset_id,
                RagasRegressionRun.status == "completed",
            )
            .order_by(RagasRegressionRun.created_at.desc())
            .limit(2)
            .all()
        )
    except Exception as exc:
        logger.debug("Failed to add regression diff files to report bundle: %s", exc)
        return {}

    target = rows[0] if rows else None
    base = rows[1] if rows and len(rows) > 1 else None
    if target is None:
        return {}

    artifacts = {"regression_latest.json": _json_compact(_regression_run_payload(target), default=str)}
    if base is not None:
        artifacts["regression_baseline.json"] = _json_compact(_regression_run_payload(base), default=str)
        artifacts.update(_regression_diff_artifacts(base, target, redact=redact))
    return artifacts


@router.get("/datasets/{dataset_id}", response_model=DatasetReportOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_report(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64, description='Optional: filter by pipeline_hash (active)')] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    *,
    context: ReportContextDep,
):
    return _build_report(context, dataset_id=dataset_id, pipeline_hash=pipeline_hash, connector_runs_limit=connector_runs_limit)


@router.get("/datasets/{dataset_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_json(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64)] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    *,
    context: ReportContextDep,
):
    report = _build_report(context, dataset_id=dataset_id, pipeline_hash=pipeline_hash, connector_runs_limit=connector_runs_limit)
    content = _json_compact(report.model_dump(mode="json"))
    safe = _SAFE_DATASET_NAME_RE.sub("_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.report{suffix}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers=download_response_headers(filename),
    )


@router.get("/datasets/{dataset_id}/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_html(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64)] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    redact: Annotated[bool, Query(description='Whether to redact dataset name/id for sharing')] = True,
    *,
    context: ReportContextDep,
):
    report = _build_report(context, dataset_id=dataset_id, pipeline_hash=pipeline_hash, connector_runs_limit=connector_runs_limit)

    html = render_dataset_report_html(
        title="MimirQ · 数据集报告中心（质量 + 合规）",
        dataset_name=str(report.dataset_name or ""),
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=bool(redact),
    )

    safe = _SAFE_DATASET_NAME_RE.sub("_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.report{suffix}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=download_response_headers(filename),
    )


@router.get("/datasets/{dataset_id}/rag-audit/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_rag_audit_html(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64)] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    redact: Annotated[bool, Query(description='Whether to redact dataset name/id for sharing')] = True,
    *,
    context: ReportContextDep,
):
    report = _build_report(context, dataset_id=dataset_id, pipeline_hash=pipeline_hash, connector_runs_limit=connector_runs_limit)

    html = render_rag_audit_html(
        title="MimirQ · RAG Audit（Profile + Governance + Chunk + KG + Eval）",
        dataset_name=str(report.dataset_name or ""),
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=bool(redact),
    )

    safe = _SAFE_DATASET_NAME_RE.sub("_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.rag_audit{suffix}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=download_response_headers(filename),
    )


@router.get("/datasets/{dataset_id}/export-bundle", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_bundle_zip(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64)] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    redact: Annotated[bool, Query(description='Whether to redact dataset name/id for sharing')] = True,
    *,
    context: ReportContextDep,
):
    """
    One-click export bundle (zip) containing:
    - report.json (redacted when redact=true)
    - report.html
    - rag_audit.html
    - manifest.json
    """
    report = _build_report(context, dataset_id=dataset_id, pipeline_hash=pipeline_hash, connector_runs_limit=connector_runs_limit)

    report_obj_raw = report.model_dump(mode="json")
    report_obj = report_obj_raw
    if bool(redact):
        report_obj = _scrub_report_for_redaction(report_obj_raw)
        # Keep safe aggregate summaries that are useful for shareable audit bundles.
        for key in ("must_recall_summary", "hierarchy_recall_summary"):
            if report_obj_raw.get(key) is not None:
                report_obj[key] = report_obj_raw.get(key)

    report_json = _json_compact(report_obj)

    report_html = render_dataset_report_html(
        title="MimirQ · 数据集报告中心（质量 + 合规）",
        dataset_name=str(report.dataset_name or ""),
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=bool(redact),
    )
    rag_audit_html = render_rag_audit_html(
        title="MimirQ · RAG Audit（Profile + Governance + Chunk + KG + Eval）",
        dataset_name=str(report.dataset_name or ""),
        dataset_id=str(dataset_id),
        generated_at=report.generated_at,
        report=report.model_dump(mode="json"),
        redact=bool(redact),
    )

    artifacts = _regression_bundle_artifacts(context, dataset_id, redact=bool(redact))
    files = ["manifest.json", "report.json", "report.html", "rag_audit.html", *artifacts]
    manifest = {
        "schema": "mimirq.report_bundle.v2",
        "generated_at": report.generated_at.isoformat() if hasattr(report.generated_at, "isoformat") else str(report.generated_at or ""),
        "dataset_id": str(dataset_id),
        "pipeline_hash": pipeline_hash,
        "redact": bool(redact),
        "files": files,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", _json_compact(manifest))
        zf.writestr("report.json", report_json)
        zf.writestr("report.html", report_html)
        zf.writestr("rag_audit.html", rag_audit_html)
        for artifact_name, artifact_content in artifacts.items():
            zf.writestr(artifact_name, artifact_content)

    safe = _SAFE_DATASET_NAME_RE.sub("_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.report_bundle{suffix}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers=download_response_headers(filename),
    )

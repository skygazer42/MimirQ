"""Reports API.

Provides exportable, shareable dataset-level bundles (quality + compliance).
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.report import DatasetReportOut
from app.api.utils.response_headers import download_response_headers
from app.core.database import get_db
from app.services.report_html import _scrub_report_for_redaction, render_dataset_report_html, render_rag_audit_html
from app.services.report_service import ReportService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SAFE_DATASET_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


@router.get("/datasets/{dataset_id}", response_model=DatasetReportOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_report(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64, description='Optional: filter by pipeline_hash (active)')] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    return ReportService.build_dataset_report(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        connector_runs_limit=int(connector_runs_limit or 0),
    )


@router.get("/datasets/{dataset_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_report_json(
    dataset_id: UUID,
    pipeline_hash: Annotated[str | None, Query(max_length=64)] = None,
    connector_runs_limit: Annotated[int, Query(ge=0, le=100)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    report = ReportService.build_dataset_report(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        connector_runs_limit=int(connector_runs_limit or 0),
    )

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
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    One-click export bundle (zip) containing:
    - report.json (redacted when redact=true)
    - report.html
    - rag_audit.html
    - manifest.json
    """
    report = ReportService.build_dataset_report(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        pipeline_hash=pipeline_hash,
        connector_runs_limit=int(connector_runs_limit or 0),
    )

    report_obj_raw = report.model_dump(mode="json")
    report_obj = report_obj_raw
    if bool(redact):
        report_obj = _scrub_report_for_redaction(report_obj_raw)
        # Keep safe aggregate summaries that are useful for shareable audit bundles.
        for key in ("must_recall_summary", "hierarchy_recall_summary"):
            if report_obj_raw.get(key) is not None:
                report_obj[key] = report_obj_raw.get(key)

    report_json = json.dumps(report_obj, ensure_ascii=False, separators=(",", ":"))

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

    files = ["manifest.json", "report.json", "report.html", "rag_audit.html"]

    # Optional: include a baseline-vs-latest regression diff artifact (best-effort).
    regression_latest_json = ""
    regression_baseline_json = ""
    regression_diff_json = ""
    regression_diff_html = ""
    try:
        from app.models.evaluation import RagasRegressionRun
        from app.services.regression_run_diff import diff_regression_run_summaries
        from app.services.regression_run_diff_html import render_regression_run_diff_html

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
        target = rows[0] if rows else None
        base = rows[1] if rows and len(rows) > 1 else None

        if target is not None:
            regression_latest_json = json.dumps(
                {
                    "run_id": str(getattr(target, "id", "")),
                    "status": str(getattr(target, "status", "")),
                    "params": dict(getattr(target, "params", None) or {}),
                    "summary": dict(getattr(target, "summary", None) or {}),
                    "created_at": getattr(target, "created_at", None),
                    "finished_at": getattr(target, "finished_at", None),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            files.append("regression_latest.json")

        if target is not None and base is not None:
            regression_baseline_json = json.dumps(
                {
                    "run_id": str(getattr(base, "id", "")),
                    "status": str(getattr(base, "status", "")),
                    "params": dict(getattr(base, "params", None) or {}),
                    "summary": dict(getattr(base, "summary", None) or {}),
                    "created_at": getattr(base, "created_at", None),
                    "finished_at": getattr(base, "finished_at", None),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            files.append("regression_baseline.json")

            base_summary = getattr(base, "summary", None)
            base_summary = base_summary if isinstance(base_summary, dict) else {}
            target_summary = getattr(target, "summary", None)
            target_summary = target_summary if isinstance(target_summary, dict) else {}
            if base_summary and target_summary:
                diff_payload = diff_regression_run_summaries(
                    base_run_id=base.id,
                    target_run_id=target.id,
                    base_summary=base_summary,
                    target_summary=target_summary,
                    max_slice_buckets=40,
                )
                diff_payload["base_params"] = dict(getattr(base, "params", None) or {})
                diff_payload["target_params"] = dict(getattr(target, "params", None) or {})

                if bool(redact):
                    # Defense-in-depth: avoid leaking directory slice keys in diff payloads.
                    sd = diff_payload.get("slice_diffs")
                    if isinstance(sd, dict) and "directory" in sd:
                        sd = dict(sd)
                        sd["directory"] = {"truncated_before": True, "truncated_after": True, "buckets": []}
                        diff_payload["slice_diffs"] = sd
                    diff_payload["base_run_id"] = "[REDACTED]"
                    diff_payload["target_run_id"] = "[REDACTED]"

                regression_diff_json = json.dumps(diff_payload, ensure_ascii=False, separators=(",", ":"), default=str)
                regression_diff_html = render_regression_run_diff_html(
                    title="MimirQ · Regression Run Diff（Baseline vs Latest）",
                    base_run_id=str(getattr(base, "id", "")),
                    target_run_id=str(getattr(target, "id", "")),
                    generated_at=diff_payload.get("generated_at"),
                    diff=diff_payload,
                    redact=bool(redact),
                )
                files.append("regression_diff.json")
                files.append("regression_diff.html")
    except Exception:
        # Best-effort: do not fail report bundle exports due to missing DB/models in unit tests.
        pass
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
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        zf.writestr("report.json", report_json)
        zf.writestr("report.html", report_html)
        zf.writestr("rag_audit.html", rag_audit_html)
        if regression_latest_json:
            zf.writestr("regression_latest.json", regression_latest_json)
        if regression_baseline_json:
            zf.writestr("regression_baseline.json", regression_baseline_json)
        if regression_diff_json:
            zf.writestr("regression_diff.json", regression_diff_json)
        if regression_diff_html:
            zf.writestr("regression_diff.html", regression_diff_html)

    safe = _SAFE_DATASET_NAME_RE.sub("_", str(report.dataset_name or "dataset"))[:64]
    suffix = f".{pipeline_hash[:8]}" if pipeline_hash else ""
    filename = f"{safe}.report_bundle{suffix}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers=download_response_headers(filename),
    )

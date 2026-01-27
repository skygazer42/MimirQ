"""
Dataset precheck service.

Provides:
- Listing precheck scan runs
- Loading persisted summary snapshots
- Drill-down file lists by finding key (streamed from JSONL artifacts)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.dataset_precheck import DatasetPrecheckFindingListResponse, DatasetPrecheckFileOut, DatasetPrecheckSummary
from app.core.config import settings
from app.models.dataset import Dataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.services.dataset_service import DatasetService


FINDING_KEYS: set[str] = {
    "parse_failed",
    "pdf_scanned",
    "pdf_unknown",
    "pii",
    "secrets",
    "exact_dup",
    "near_dup",
    "large_spreadsheet",
}


def _assert_artifact_path_under_tenant(*, tenant_id: UUID, path: Path) -> None:
    upload_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads").resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    try:
        path.resolve(strict=False).relative_to(tenant_root)
    except Exception:
        raise HTTPException(status_code=403, detail="Artifact access denied")


def get_dataset_for_precheck(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    require_write: bool = False,
) -> Dataset:
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    if require_write:
        DatasetService.assert_dataset_writable(db, ds, account_id)
    else:
        DatasetService.assert_dataset_readable(db, ds, account_id)
    return ds


def _scan_run_out_from_row(row: DBDatasetPrecheckScanRun) -> dict[str, Any]:
    cfg = getattr(row, "config", None)
    if not isinstance(cfg, dict):
        cfg = {}
    # Redact root_path in API responses when requested.
    if bool(cfg.get("redact_paths", False)) and "root_path" in cfg:
        cfg = dict(cfg)
        cfg["root_path"] = "[REDACTED]"

    summary = getattr(row, "summary", None)
    if not isinstance(summary, dict):
        summary = {}
    artifacts = getattr(row, "artifacts", None)
    if not isinstance(artifacts, dict):
        artifacts = {}
    if bool(cfg.get("redact_paths", False)) and "root_path" in artifacts:
        artifacts = dict(artifacts)
        artifacts["root_path"] = "[REDACTED]"

    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "dataset_id": row.dataset_id,
        "requested_by": getattr(row, "requested_by", None),
        "kind": str(getattr(row, "kind", "") or "path"),
        "status": str(getattr(row, "status", "") or "pending"),
        "progress": int(getattr(row, "progress", 0) or 0),
        "config": cfg,
        "summary": summary,
        "artifacts": artifacts,
        "error_message": getattr(row, "error_message", None),
        "started_at": getattr(row, "started_at", None),
        "finished_at": getattr(row, "finished_at", None),
        "created_at": getattr(row, "created_at", None),
        "updated_at": getattr(row, "updated_at", None),
    }


def load_precheck_summary_from_row(row: DBDatasetPrecheckScanRun) -> DatasetPrecheckSummary:
    raw = getattr(row, "summary", None)
    if not isinstance(raw, dict) or not raw:
        raise HTTPException(status_code=404, detail="Summary not available")
    try:
        return DatasetPrecheckSummary(**raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid summary payload: {str(exc)[:200]}") from exc


def _iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def _list_finding_from_jsonl(
    *,
    jsonl_path: Path,
    finding_key: str,
    skip: int,
    limit: int,
) -> DatasetPrecheckFindingListResponse:
    key = str(finding_key or "").strip().lower()
    if key not in FINDING_KEYS:
        raise HTTPException(status_code=400, detail="Unknown finding_key")

    skip_n = max(0, int(skip or 0))
    limit_n = max(1, min(int(limit or 50), 200))

    # Special-case: exact duplicates require a 2-pass scan to find sha256 groups with cnt>1.
    dup_shas: set[str] | None = None
    if key == "exact_dup":
        dup_shas = set()
        counts: dict[str, int] = {}
        for obj in _iter_jsonl(jsonl_path):
            sha = str(obj.get("file_sha256") or "").strip().lower()
            if not sha:
                continue
            counts[sha] = counts.get(sha, 0) + 1
        for sha, cnt in counts.items():
            if int(cnt) > 1:
                dup_shas.add(sha)

    total = 0
    items: list[DatasetPrecheckFileOut] = []
    for obj in _iter_jsonl(jsonl_path):
        findings = obj.get("findings")
        if not isinstance(findings, list):
            findings = []
        if key == "exact_dup":
            sha = str(obj.get("file_sha256") or "").strip().lower()
            match = bool(dup_shas and sha and sha in dup_shas)
        else:
            match = key in {str(x or "").strip().lower() for x in findings}
        if not match:
            continue
        total += 1
        if total <= skip_n:
            continue
        if len(items) >= limit_n:
            continue

        try:
            items.append(DatasetPrecheckFileOut(**obj))
        except Exception:
            # Best-effort: ignore invalid lines.
            continue

    return DatasetPrecheckFindingListResponse(total=int(total), items=items)


def list_precheck_finding_files(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    scan_run_id: UUID,
    finding_key: str,
    skip: int = 0,
    limit: int = 50,
) -> DatasetPrecheckFindingListResponse:
    key = str(finding_key or "").strip().lower()
    if key not in FINDING_KEYS:
        raise HTTPException(status_code=400, detail="Unknown finding_key")

    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)

    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Scan run not found")

    artifacts = getattr(row, "artifacts", None)
    if not isinstance(artifacts, dict):
        artifacts = {}
    jsonl_raw = str(artifacts.get("files_jsonl") or "").strip()
    if not jsonl_raw:
        raise HTTPException(status_code=404, detail="Artifacts not available")

    jsonl_path = Path(jsonl_raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=jsonl_path)
    if not jsonl_path.exists() or not jsonl_path.is_file():
        raise HTTPException(status_code=404, detail="Artifacts not found")

    return _list_finding_from_jsonl(jsonl_path=jsonl_path, finding_key=key, skip=int(skip or 0), limit=int(limit or 50))


__all__ = [
    "_scan_run_out_from_row",
    "_list_finding_from_jsonl",
    "get_dataset_for_precheck",
    "list_precheck_finding_files",
    "load_precheck_summary_from_row",
]

"""
Dataset precheck service.

Provides:
- Listing precheck scan runs
- Loading persisted summary snapshots
- Drill-down file lists by finding key (streamed from JSONL artifacts)
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.dataset_precheck import (
    DatasetPrecheckFileOut,
    DatasetPrecheckFindingListResponse,
    DatasetPrecheckSummary,
)
from app.core.config import settings
from app.models.dataset import Dataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.services.dataset_precheck_scan_runner import _build_samples_payload
from app.services.dataset_service import DatasetService

FINDING_KEYS: set[str] = {
    "parse_failed",
    "legacy_format",
    "password_protected",
    "corrupted_or_unreadable",
    "other_parse_failure",
    "empty_text",
    "short_text",
    "low_density_text",
    "gibberish_text",
    "pdf_scanned",
    "pdf_mixed",
    "pdf_low_density",
    "pdf_encrypted",
    "pdf_unknown",
    "pii",
    "secrets",
    "exact_dup",
    "near_dup",
    "large_spreadsheet",
    "wide_spreadsheet",
    "many_sheets_spreadsheet",
    "merged_heavy_spreadsheet",
}

ARTIFACTS_NOT_AVAILABLE_DETAIL = "Artifacts not available"
ARTIFACTS_NOT_FOUND_DETAIL = "Artifacts not found"
_DEFAULT_UPLOAD_DIR = "./uploads"


def _assert_artifact_path_under_tenant(*, tenant_id: UUID, path: Path) -> None:
    upload_root = Path(getattr(settings, "UPLOAD_DIR", _DEFAULT_UPLOAD_DIR) or _DEFAULT_UPLOAD_DIR).resolve(strict=False)
    tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
    try:
        path.resolve(strict=False).relative_to(tenant_root)
    except Exception:
        raise HTTPException(status_code=403, detail="Artifact access denied") from None


def _precheck_sample_reviews_path_for_row(
    row: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
) -> Path:
    artifacts = getattr(row, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}

    raw = str(artifacts.get("sample_reviews_json") or "").strip()
    if raw:
        path = Path(raw)
        _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=path)
        return path

    jsonl_raw = str(artifacts.get("files_jsonl") or "").strip()
    if jsonl_raw:
        jsonl_path = Path(jsonl_raw)
        _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=jsonl_path)
        return jsonl_path.resolve(strict=False).parent / "sample_reviews.json"

    upload_root = Path(getattr(settings, "UPLOAD_DIR", _DEFAULT_UPLOAD_DIR) or _DEFAULT_UPLOAD_DIR).resolve(strict=False)
    path = upload_root / str(tenant_id) / "precheck" / str(row.id) / "sample_reviews.json"
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=path)
    return path


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


def _list_files_from_jsonl(
    *,
    jsonl_path: Path,
    dir_prefix: str | None,
    skip: int,
    limit: int,
) -> DatasetPrecheckFindingListResponse:
    """
    List file records under a directory prefix (best-effort).

    `dir_prefix` is a relative path under scan root (uses "/" separators).
    """
    raw = str(dir_prefix or "").replace("\\", "/").strip()
    if raw in {"", ".", "/"}:
        prefix = ""
    else:
        raw = raw.lstrip("/")
        raw = raw.strip("/")
        prefix = f"{raw}/" if raw else ""

    skip_n = max(0, int(skip or 0))
    limit_n = max(1, min(int(limit or 50), 200))

    total = 0
    items: list[DatasetPrecheckFileOut] = []
    for obj in _iter_jsonl(jsonl_path):
        nm = str(obj.get("name") or "").replace("\\", "/").strip()
        if prefix and not nm.startswith(prefix):
            continue
        total += 1
        if total <= skip_n:
            continue
        if len(items) >= limit_n:
            continue
        try:
            items.append(DatasetPrecheckFileOut(**obj))
        except Exception:
            continue

    return DatasetPrecheckFindingListResponse(total=int(total), items=items)


def load_precheck_samples_from_row(
    row: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
    size: int = 60,
    prefer_artifact: bool = True,
) -> dict[str, Any]:
    """
    Load representative samples payload for a scan run.

    - Prefer persisted artifacts (samples_json) when available.
    - Fallback to on-demand build from files_jsonl.
    """
    size_n = max(0, min(int(size or 0), 2000))

    artifacts = getattr(row, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}

    if prefer_artifact:
        raw = str(artifacts.get("samples_json") or "").strip()
        if raw:
            p = Path(raw)
            _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=p)
            if p.exists() and p.is_file():
                try:
                    obj = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass

    # Build on demand from JSONL.
    jsonl_raw = str(artifacts.get("files_jsonl") or "").strip()
    if not jsonl_raw:
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_AVAILABLE_DETAIL)
    jsonl_path = Path(jsonl_raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=jsonl_path)
    if not jsonl_path.exists() or not jsonl_path.is_file():
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_FOUND_DETAIL)

    return _build_samples_payload(jsonl_path=jsonl_path, target_size=size_n)


def load_precheck_sample_reviews_from_row(
    row: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
) -> dict[str, dict[str, Any]]:
    path = _precheck_sample_reviews_path_for_row(row, tenant_id=tenant_id)
    if not path.exists() or not path.is_file():
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        out[key] = dict(value)
    return out


def apply_precheck_sample_reviews(
    payload: dict[str, Any],
    reviews_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not reviews_by_name:
        return payload

    merged = json.loads(json.dumps(payload, ensure_ascii=False))

    def _apply(items: list[Any]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            review = reviews_by_name.get(str(item.get("name") or ""))
            if not isinstance(review, dict):
                continue
            item["review_disposition"] = review.get("review_disposition")
            item["reviewed_at"] = review.get("reviewed_at")
            item["reviewed_by"] = review.get("reviewed_by")

    _apply(merged.get("representative") if isinstance(merged.get("representative"), list) else [])
    _apply(merged.get("top_large_files") if isinstance(merged.get("top_large_files"), list) else [])
    _apply(merged.get("top_long_text") if isinstance(merged.get("top_long_text"), list) else [])

    needs_review = merged.get("needs_review")
    if isinstance(needs_review, dict):
        for files in needs_review.values():
            if isinstance(files, list):
                _apply(files)

    return merged


def upsert_precheck_sample_review_for_row(
    row: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
    account_id: str,
    file_name: str,
    disposition: str,
) -> dict[str, Any]:
    path = _precheck_sample_reviews_path_for_row(row, tenant_id=tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    reviews = load_precheck_sample_reviews_from_row(row, tenant_id=tenant_id)
    review = {
        "review_disposition": str(disposition),
        "reviewed_at": datetime.now(UTC).isoformat(),
        "reviewed_by": str(account_id or "").strip() or None,
    }
    reviews[str(file_name)] = review
    path.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")

    artifacts = dict(getattr(row, "artifacts", None) or {})
    artifacts["sample_reviews_json"] = str(path)
    row.artifacts = artifacts
    return review


def load_precheck_near_dups_from_row(
    row: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
) -> dict[str, Any]:
    artifacts = getattr(row, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    raw = str(artifacts.get("near_dups_json") or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Near-dup artifact not available")
    p = Path(raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=p)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Near-dup artifact not found")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid near-dup artifact: {str(exc)[:200]}") from exc
    if not isinstance(obj, dict):
        raise HTTPException(status_code=500, detail="Invalid near-dup artifact")
    return obj


def list_near_dup_files_from_row(
    row: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
    skip: int,
    limit: int,
) -> DatasetPrecheckFindingListResponse:
    """
    Resolve near-duplicate affected files (from near_dups_json) into per-file records.

    This keeps JSONL immutable (streaming write) and avoids a rewrite pass.
    """
    artifacts = getattr(row, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    jsonl_raw = str(artifacts.get("files_jsonl") or "").strip()
    if not jsonl_raw:
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_AVAILABLE_DETAIL)
    jsonl_path = Path(jsonl_raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=jsonl_path)
    if not jsonl_path.exists() or not jsonl_path.is_file():
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_FOUND_DETAIL)

    near = load_precheck_near_dups_from_row(row, tenant_id=tenant_id)
    clusters = near.get("clusters") if isinstance(near.get("clusters"), list) else []
    affected: set[str] = set()
    for c in clusters:
        if not isinstance(c, dict):
            continue
        members = c.get("members")
        if isinstance(members, list):
            for m in members:
                name = str(m or "").strip()
                if name:
                    affected.add(name)

    if not affected:
        return DatasetPrecheckFindingListResponse(total=0, items=[])

    skip_n = max(0, int(skip or 0))
    limit_n = max(1, min(int(limit or 50), 200))

    total = 0
    items: list[DatasetPrecheckFileOut] = []
    for obj in _iter_jsonl(jsonl_path):
        nm = str(obj.get("name") or "").strip()
        if not nm or nm not in affected:
            continue
        total += 1
        if total <= skip_n:
            continue
        if len(items) >= limit_n:
            continue
        try:
            items.append(DatasetPrecheckFileOut(**obj))
        except Exception:
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
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_AVAILABLE_DETAIL)

    jsonl_path = Path(jsonl_raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=jsonl_path)
    if not jsonl_path.exists() or not jsonl_path.is_file():
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_FOUND_DETAIL)

    # near_dup is cluster-based and resolved via near_dups_json (not per-record findings).
    if key == "near_dup":
        return list_near_dup_files_from_row(row, tenant_id=tenant_id, skip=int(skip or 0), limit=int(limit or 50))

    return _list_finding_from_jsonl(jsonl_path=jsonl_path, finding_key=key, skip=int(skip or 0), limit=int(limit or 50))


def list_precheck_files_by_dir_prefix(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    scan_run_id: UUID,
    dir_prefix: str | None,
    skip: int = 0,
    limit: int = 50,
) -> DatasetPrecheckFindingListResponse:
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
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_AVAILABLE_DETAIL)

    jsonl_path = Path(jsonl_raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=jsonl_path)
    if not jsonl_path.exists() or not jsonl_path.is_file():
        raise HTTPException(status_code=404, detail=ARTIFACTS_NOT_FOUND_DETAIL)

    return _list_files_from_jsonl(
        jsonl_path=jsonl_path,
        dir_prefix=dir_prefix,
        skip=int(skip or 0),
        limit=int(limit or 50),
    )


__all__ = [
    "_scan_run_out_from_row",
    "_list_finding_from_jsonl",
    "apply_precheck_sample_reviews",
    "get_dataset_for_precheck",
    "list_precheck_finding_files",
    "list_precheck_files_by_dir_prefix",
    "load_precheck_sample_reviews_from_row",
    "load_precheck_samples_from_row",
    "load_precheck_summary_from_row",
    "upsert_precheck_sample_review_for_row",
]

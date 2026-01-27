"""
Precheck -> ingestion policy suggestion (\"report\" -> \"action\" bridge).

This module converts objective precheck outputs into an importable IngestionPolicy and
a bounded manual-review manifest (parse_failed/pdf_unknown/large_spreadsheet/dups...).

Design principles:
- Prefer conservative, explainable rules.
- Never attempt to auto-delete or make irreversible decisions.
- Keep payload sizes bounded for API safety.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule
from app.core.config import settings
from app.models.dataset import Dataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.services.dataset_precheck_service import _assert_artifact_path_under_tenant, _list_finding_from_jsonl
from app.services.ingestion_policy import validate_and_normalize_ingestion_policy


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _load_jsonl_path(scan_run: DBDatasetPrecheckScanRun, *, tenant_id: UUID) -> Path:
    artifacts = getattr(scan_run, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    raw = str(artifacts.get("files_jsonl") or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Artifacts not available")
    p = Path(raw)
    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=p)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="Artifacts not found")
    return p


def _iter_jsonl(path: Path):  # noqa: ANN202
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


def _rule(
    *,
    rid: str,
    name: str,
    extensions: list[str],
    filename_regex: str | None = None,
    preprocess_steps: list[str] | None = None,
    parser_backend: str | None = None,
    governance_profile_ref: str | None = None,
    pipeline_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    steps = [{"id": sid, "params": {}} for sid in (preprocess_steps or [])]
    return {
        "id": rid,
        "name": name,
        "enabled": True,
        "match": {"extensions": extensions, "filename_regex": filename_regex},
        "preprocess": {"enabled": bool(steps), "steps": steps},
        "parser_backend": parser_backend,
        "chunk_strategy": None,
        "governance_profile_ref": governance_profile_ref,
        "pipeline_patch": dict(pipeline_patch or {}),
    }


def _pii_secrets_patch(*, enable_pii: bool, enable_secrets: bool) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if enable_pii:
        patch.update(
            {
                "governance_pii_anonymize": True,
                "governance_pii_mode": "mask",
                "governance_pii_mask": "[REDACTED]",
            }
        )
    if enable_secrets:
        patch.update(
            {
                "governance_secrets_redact": True,
                "governance_secrets_mode": "mask",
                "governance_secrets_mask": "[SECRET]",
            }
        )
    return patch


def build_ingestion_policy_suggestion(
    scan_run: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
    max_names_per_bucket: int = 50,
) -> dict[str, Any]:
    """
    Build a suggested ingestion policy from a precheck run.
    """
    max_names = max(0, min(int(max_names_per_bucket or 0), 2000))

    summary = getattr(scan_run, "summary", None)
    summary = summary if isinstance(summary, dict) else {}
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not available")

    pdf_scan = summary.get("pdf_scan") if isinstance(summary.get("pdf_scan"), dict) else {}
    scanned_pdfs = _safe_int(pdf_scan.get("scanned"))
    unknown_pdfs = _safe_int(pdf_scan.get("unknown"))
    finding_list = summary.get("findings") if isinstance(summary.get("findings"), list) else []
    finding_by_key = {
        str(item.get("key") or "").strip().lower(): item
        for item in (finding_list or [])
        if isinstance(item, dict)
    }
    large_spreadsheets = _safe_int((finding_by_key.get("large_spreadsheet") or {}).get("count"))

    # Identify which file types actually hit PII/secrets, so we only patch relevant rules.
    jsonl_path = _load_jsonl_path(scan_run, tenant_id=tenant_id)
    pii_types: set[str] = set()
    secrets_types: set[str] = set()
    for obj in _iter_jsonl(jsonl_path):
        ftype = str(obj.get("file_type") or "").strip().lower()
        findings = obj.get("findings") if isinstance(obj.get("findings"), list) else []
        fset = {str(x or "").strip().lower() for x in findings}
        if ftype and "pii" in fset:
            pii_types.add(ftype)
        if ftype and "secrets" in fset:
            secrets_types.add(ftype)

    # Heuristic: longform docs benefit from wiki profile (P90).
    p90 = 0
    lp = summary.get("length_percentiles") if isinstance(summary.get("length_percentiles"), dict) else {}
    p90 = _safe_int(lp.get("p90"))
    use_longform = p90 >= 20_000

    notes: list[str] = []
    if scanned_pdfs > 0:
        notes.append(f"检测到疑似扫描 PDF：{scanned_pdfs}（建议启用 OCR 相关解析链路，并复核 pdf_unknown/低密度页面）")
    if unknown_pdfs > 0:
        notes.append(f"PDF 类型未知：{unknown_pdfs}（可能为加密/权限/依赖缺失；建议加入人工复核队列）")
    if use_longform:
        notes.append(f"P90 文本长度较长（{p90} chars）：Markdown/长文建议使用 longform 治理预设（去重+裁剪 References）")
    if large_spreadsheets > 0:
        notes.append(f"检测到大表/复杂表格：{large_spreadsheets}（建议优先走 TAG/SQL 方案，而不是硬上纯 RAG）")

    # Build rules (conservative defaults).
    rules: list[dict[str, Any]] = []

    # HTML (web scrape).
    html_patch = _pii_secrets_patch(enable_pii=("html" in pii_types), enable_secrets=("html" in secrets_types))
    rules.append(
        _rule(
            rid="html-web",
            name="网页 HTML（去样板/去导航）",
            extensions=[".html", ".htm"],
            preprocess_steps=[
                "html.strip_scripts_styles",
                "html.strip_comments",
                "text.normalize_newlines",
                "text.trim_trailing_whitespace",
                "text.remove_zero_width",
                "text.remove_control_chars",
            ],
            parser_backend="auto",
            governance_profile_ref="builtin:html_web",
            pipeline_patch=html_patch,
        )
    )

    # PDF routing: add an OCR-first rule when scanned PDFs exist (best-effort filename hint).
    pdf_patch = _pii_secrets_patch(enable_pii=("pdf" in pii_types), enable_secrets=("pdf" in secrets_types))
    if scanned_pdfs > 0 or unknown_pdfs > 0:
        rules.append(
            _rule(
                rid="pdf-ocr-first",
                name="PDF 扫描/OCR（优先：文件名命中 scan/ocr/扫描）",
                extensions=[".pdf"],
                filename_regex=r"(?i)(scan|ocr|扫描|影印|图片|照片)",
                preprocess_steps=None,
                parser_backend="auto",
                governance_profile_ref="builtin:pdf_scanned_ocr",
                pipeline_patch=pdf_patch,
            )
        )
    rules.append(
        _rule(
            rid="pdf-default",
            name="PDF 文本版（默认）",
            extensions=[".pdf"],
            preprocess_steps=None,
            parser_backend="auto",
            governance_profile_ref="builtin:pdf_text",
            pipeline_patch=pdf_patch,
        )
    )

    # Table-like files: prefer TAG for large/complex tables, but keep small tables in RAG.
    # We do this via table_store_auto_route (implemented in the ingestion processor).
    table_has_pii = bool({"csv", "xls", "xlsx"} & pii_types)
    table_patch: dict[str, Any] = {
        "table_store_enabled": True,
        "table_store_auto_route": True,
        "table_store_auto_row_threshold": int(getattr(settings, "TABLE_STORE_AUTO_ROW_THRESHOLD", 5000) or 5000),
        "table_store_auto_col_threshold": int(getattr(settings, "TABLE_STORE_AUTO_COL_THRESHOLD", 80) or 80),
        "table_store_auto_sheet_threshold": int(getattr(settings, "TABLE_STORE_AUTO_SHEET_THRESHOLD", 5) or 5),
        "table_store_auto_file_bytes_threshold": int(getattr(settings, "TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD", 5_000_000) or 5_000_000),
    }
    if table_has_pii:
        # Conservative default: do not persist raw sample rows when precheck suggests PII exists.
        table_patch["table_store_sample_rows"] = 0
    # CSV is text; apply safe text preprocess before import.
    rules.append(
        _rule(
            rid="tables-csv-tag",
            name="表格（CSV）：TAG 自动分流（大表→SQL，小表→RAG）",
            extensions=[".csv"],
            preprocess_steps=[
                "text.reencode_utf8",
                "text.strip_bom",
                "text.normalize_newlines",
            ],
            parser_backend="auto",
            governance_profile_ref="builtin:structured_data",
            pipeline_patch=table_patch,
        )
    )
    # Excel is binary; do NOT apply text preprocess steps.
    rules.append(
        _rule(
            rid="tables-excel-tag",
            name="表格（XLS/XLSX）：TAG 自动分流（大表→SQL，小表→RAG）",
            extensions=[".xls", ".xlsx"],
            preprocess_steps=None,
            parser_backend="auto",
            governance_profile_ref="builtin:structured_data",
            pipeline_patch=table_patch,
        )
    )

    # Office.
    office_patch = _pii_secrets_patch(
        enable_pii=bool({"docx", "pptx"} & pii_types),
        enable_secrets=bool({"docx", "pptx"} & secrets_types),
    )
    rules.append(
        _rule(
            rid="office-default",
            name="Office（DOCX/PPTX）",
            extensions=[".docx", ".pptx"],
            preprocess_steps=None,
            parser_backend="markitdown",
            governance_profile_ref="builtin:kb_default",
            pipeline_patch=office_patch,
        )
    )

    # Structured data (csv/json/log).
    structured_patch = _pii_secrets_patch(
        enable_pii=bool({"json", "jsonl", "ndjson", "log", "txt"} & pii_types),
        enable_secrets=bool({"json", "jsonl", "ndjson", "log", "txt"} & secrets_types),
    )
    rules.append(
        _rule(
            rid="structured-data",
            name="结构化数据（JSON/日志型）",
            extensions=[".json", ".jsonl", ".ndjson", ".log"],
            preprocess_steps=[
                "text.reencode_utf8",
                "text.strip_bom",
                "text.normalize_newlines",
            ],
            parser_backend="auto",
            governance_profile_ref="builtin:structured_data",
            pipeline_patch=structured_patch,
        )
    )

    # Markdown/text.
    md_profile = "builtin:wiki_longform" if use_longform else "builtin:kb_default"
    md_patch = _pii_secrets_patch(enable_pii=bool({"md", "txt"} & pii_types), enable_secrets=bool({"md", "txt"} & secrets_types))
    rules.append(
        _rule(
            rid="markdown-text",
            name="Markdown / 纯文本（保守清洗）",
            extensions=[".md", ".txt"],
            preprocess_steps=[
                "text.reencode_utf8",
                "text.strip_bom",
                "text.normalize_newlines",
                "text.trim_trailing_whitespace",
                "text.remove_zero_width",
                "text.remove_control_chars",
            ],
            parser_backend="auto",
            governance_profile_ref=md_profile,
            pipeline_patch=md_patch,
        )
    )

    # Normalize via the shared validator (also enforces regex safety/allowlists).
    model = IngestionPolicy(version="1", rules=[IngestionRule(**r) for r in rules])
    normalized = validate_and_normalize_ingestion_policy(model)

    # Manual-review buckets (bounded name lists).
    buckets = []
    for key in ["parse_failed", "pdf_unknown", "large_spreadsheet", "exact_dup", "near_dup"]:
        try:
            if key == "near_dup":
                # near_dups.json is optional; keep this best-effort.
                artifacts = getattr(scan_run, "artifacts", None)
                artifacts = artifacts if isinstance(artifacts, dict) else {}
                near_raw = str(artifacts.get("near_dups_json") or "").strip()
                names: list[str] = []
                total_affected = 0
                if near_raw:
                    p = Path(near_raw)
                    _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=p)
                    if p.exists() and p.is_file():
                        obj = json.loads(p.read_text(encoding="utf-8"))
                        clusters = obj.get("clusters") if isinstance(obj, dict) and isinstance(obj.get("clusters"), list) else []
                        affected: list[str] = []
                        for c in clusters:
                            if not isinstance(c, dict):
                                continue
                            members = c.get("members")
                            if isinstance(members, list):
                                for m in members:
                                    s = str(m or "").strip()
                                    if s:
                                        affected.append(s)
                        total_affected = len(set(affected))
                        names = sorted(set(affected))[:max_names]
                buckets.append({"key": key, "total": int(total_affected), "sample_names": names})
                continue

            res = _list_finding_from_jsonl(jsonl_path=jsonl_path, finding_key=key, skip=0, limit=max_names or 1)
            buckets.append({"key": key, "total": int(res.total), "sample_names": [x.name for x in (res.items or [])]})
        except Exception:
            buckets.append({"key": key, "total": 0, "sample_names": []})

    return {
        "generated_at": _now_utc().isoformat(),
        "policy": normalized.model_dump(),
        "notes": notes,
        "manual_review": buckets,
    }


def apply_ingestion_policy_suggestion(
    db: Session,
    *,
    dataset: Dataset,
    scan_run: DBDatasetPrecheckScanRun,
    tenant_id: UUID,
    replace: bool,
) -> dict[str, Any]:
    """
    Apply a suggested ingestion policy to a dataset (server-side convenience wrapper).
    """
    meta = dict(getattr(dataset, "dataset_metadata", None) or {})
    if not bool(replace) and "ingestion_policy" in meta:
        raise HTTPException(status_code=409, detail="ingestion_policy already exists; set replace=true to overwrite")

    suggestion = build_ingestion_policy_suggestion(scan_run, tenant_id=tenant_id, max_names_per_bucket=0)
    try:
        policy = IngestionPolicy(**(suggestion.get("policy") or {}))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid suggested policy: {str(exc)[:200]}") from exc

    normalized = validate_and_normalize_ingestion_policy(policy)
    if normalized.rules:
        meta["ingestion_policy"] = normalized.model_dump()
    else:
        meta.pop("ingestion_policy", None)

    dataset.dataset_metadata = meta
    db.commit()
    db.refresh(dataset)
    return {"replaced": True, "rule_count": len(normalized.rules)}


__all__ = [
    "apply_ingestion_policy_suggestion",
    "build_ingestion_policy_suggestion",
]

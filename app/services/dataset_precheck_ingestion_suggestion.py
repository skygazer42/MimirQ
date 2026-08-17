"""
Precheck -> ingestion policy suggestion (\"report\" -> \"action\" bridge).

This module converts objective precheck outputs into an importable IngestionPolicy and
a bounded manual-review manifest (parse_failed/pdf_unknown/large_spreadsheet/dups...).

Design principles:
- Prefer conservative, explainable rules.
- Never attempt to auto-delete or make irreversible decisions.
- Keep payload sizes bounded for API safety.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionRule
from app.core.config import settings
from app.models.dataset import Dataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.rag.core.logging import get_logger
from app.services.dataset_precheck_service import _assert_artifact_path_under_tenant, _list_finding_from_jsonl
from app.services.ingestion_policy import validate_and_normalize_ingestion_policy
from app.services.ingestion_policy_diff import diff_ingestion_policies

STRUCTURED_DATA_PROFILE_REF = "builtin:structured_data"
STEP_NORMALIZE_NEWLINES = "text.normalize_newlines"
STEP_REENCODE_UTF8 = "text.reencode_utf8"
STEP_STRIP_BOM = "text.strip_bom"
_MANUAL_REVIEW_KEYS = [
    "parse_failed",
    "pdf_unknown",
    "large_spreadsheet",
    "wide_spreadsheet",
    "many_sheets_spreadsheet",
    "merged_heavy_spreadsheet",
    "exact_dup",
    "near_dup",
]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _safe_int(v: Any) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


@dataclass(frozen=True)
class _SuggestionSignals:
    scanned_pdfs: int
    unknown_pdfs: int
    large_spreadsheets: int
    wide_spreadsheets: int
    many_sheet_spreadsheets: int
    merged_heavy_spreadsheets: int
    p90: int
    token_p50: int
    token_p90: int
    use_longform: bool
    md_total: int
    txt_total: int


def _summary_or_404(scan_run: DBDatasetPrecheckScanRun) -> dict[str, Any]:
    summary = getattr(scan_run, "summary", None)
    summary = summary if isinstance(summary, dict) else {}
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not available")
    return summary


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
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if isinstance(obj, dict):
                yield obj


def _rule(
    *,
    rid: str,
    name: str,
    extensions: list[str],
    filename_regex: str | None = None,
    enabled: bool = True,
    preprocess_steps: list[str] | None = None,
    parser_backend: str | None = None,
    chunk_strategy: str | None = None,
    governance_profile_ref: str | None = None,
    pipeline_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    steps = [{"id": sid, "params": {}} for sid in (preprocess_steps or [])]
    return {
        "id": rid,
        "name": name,
        "enabled": bool(enabled),
        "match": {"extensions": extensions, "filename_regex": filename_regex},
        "preprocess": {"enabled": bool(steps), "steps": steps},
        "parser_backend": parser_backend,
        "chunk_strategy": chunk_strategy,
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


def _extract_suggestion_signals(summary: dict[str, Any]) -> _SuggestionSignals:
    pdf_scan = summary.get("pdf_scan") if isinstance(summary.get("pdf_scan"), dict) else {}
    finding_list = summary.get("findings") if isinstance(summary.get("findings"), list) else []
    finding_by_key = {
        str(item.get("key") or "").strip().lower(): item for item in finding_list if isinstance(item, dict)
    }
    length_percentiles = (
        summary.get("length_percentiles") if isinstance(summary.get("length_percentiles"), dict) else {}
    )
    token_percentiles = summary.get("token_percentiles") if isinstance(summary.get("token_percentiles"), dict) else {}
    by_file_type = summary.get("by_file_type") if isinstance(summary.get("by_file_type"), dict) else {}
    p90 = _safe_int(length_percentiles.get("p90"))

    return _SuggestionSignals(
        scanned_pdfs=_safe_int(pdf_scan.get("scanned")),
        unknown_pdfs=_safe_int(pdf_scan.get("unknown")),
        large_spreadsheets=_safe_int((finding_by_key.get("large_spreadsheet") or {}).get("count")),
        wide_spreadsheets=_safe_int((finding_by_key.get("wide_spreadsheet") or {}).get("count")),
        many_sheet_spreadsheets=_safe_int((finding_by_key.get("many_sheets_spreadsheet") or {}).get("count")),
        merged_heavy_spreadsheets=_safe_int((finding_by_key.get("merged_heavy_spreadsheet") or {}).get("count")),
        p90=p90,
        token_p50=_safe_int(token_percentiles.get("p50")),
        token_p90=_safe_int(token_percentiles.get("p90")),
        use_longform=p90 >= 20_000,
        md_total=_safe_int(by_file_type.get("md")),
        txt_total=_safe_int(by_file_type.get("txt")),
    )


def _collect_sensitive_file_types(jsonl_path: Path) -> tuple[set[str], set[str]]:
    pii_types: set[str] = set()
    secrets_types: set[str] = set()
    for obj in _iter_jsonl(jsonl_path):
        file_type = str(obj.get("file_type") or "").strip().lower()
        findings = obj.get("findings") if isinstance(obj.get("findings"), list) else []
        finding_set = {str(x or "").strip().lower() for x in findings}
        if file_type and "pii" in finding_set:
            pii_types.add(file_type)
        if file_type and "secrets" in finding_set:
            secrets_types.add(file_type)
    return pii_types, secrets_types


def _chunk_size_note(signals: _SuggestionSignals) -> str | None:
    if not bool(getattr(settings, "PRECHECK_SUGGEST_CHUNK_SIZE", True)):
        return None
    if signals.token_p90 <= 0:
        return None

    base_chunk_size = int(getattr(settings, "CHUNK_SIZE", 1000) or 1000)
    base_chunk_overlap = int(getattr(settings, "CHUNK_OVERLAP", 200) or 200)
    overlap_ratio = (base_chunk_overlap / base_chunk_size) if base_chunk_size > 0 else 0.2

    suggested_size = int(base_chunk_size)
    if signals.token_p90 >= 20_000:
        suggested_size = min(4000, int(round(base_chunk_size * 2.0)))
    elif signals.token_p90 >= 8_000:
        suggested_size = min(4000, int(round(base_chunk_size * 1.5)))
    elif signals.token_p90 <= 800:
        suggested_size = max(600, int(round(base_chunk_size * 0.8)))

    suggested_overlap = int(round(suggested_size * float(overlap_ratio)))
    suggested_overlap = max(0, min(1000, suggested_overlap))
    if suggested_overlap >= suggested_size:
        suggested_overlap = max(0, suggested_size - 1)

    return (
        "Token 分布（best-effort）："
        f"P50~{signals.token_p50}、P90~{signals.token_p90} tokens。"
        f"可尝试 chunk_size={suggested_size} chars、chunk_overlap={suggested_overlap}"
        "（建议先在 chunk-preview 验证分布）"
    )


def _build_suggestion_notes(signals: _SuggestionSignals) -> list[str]:
    notes: list[str] = []
    if signals.scanned_pdfs > 0:
        notes.append(
            f"检测到疑似扫描 PDF：{signals.scanned_pdfs}（建议启用 OCR 相关解析链路，并复核 pdf_unknown/低密度页面）"
        )
    if signals.unknown_pdfs > 0:
        notes.append(f"PDF 类型未知：{signals.unknown_pdfs}（可能为加密/权限/依赖缺失；建议加入人工复核队列）")
    if signals.use_longform:
        notes.append(
            f"P90 文本长度较长（{signals.p90} chars）：Markdown/长文建议使用 longform 治理预设（去重+裁剪 References）"
        )

    chunk_note = _chunk_size_note(signals)
    if chunk_note:
        notes.append(chunk_note)
    if signals.large_spreadsheets > 0:
        notes.append(f"检测到大表/复杂表格：{signals.large_spreadsheets}（建议优先走 TAG/SQL 方案，而不是硬上纯 RAG）")
    if signals.wide_spreadsheets > 0:
        notes.append(
            f"检测到宽表（列数较多）：{signals.wide_spreadsheets}（建议 TAG/结构化清洗；避免纯 RAG 切块导致噪声）"
        )
    if signals.many_sheet_spreadsheets > 0:
        notes.append(
            f"检测到多 Sheet 表格：{signals.many_sheet_spreadsheets}（建议拆分或结构化处理；避免一次性全量入库）"
        )
    if signals.merged_heavy_spreadsheets > 0:
        notes.append(
            f"检测到合并单元格占比较高的表格：{signals.merged_heavy_spreadsheets}（建议表格专用转换/人工复核）"
        )
    if (signals.md_total > 0 or signals.txt_total > 0) and signals.use_longform:
        notes.append(
            "可选：若你计划开启 hierarchy recall overlay（例如 profile=hierarchy_recall20_expand，或显式设置 "
            "hierarchy_parent_depth/hierarchy_sibling_window），可在 ingestion_policy 中启用 "
            "`markdown_hierarchy` / `text_hierarchy` 切块策略，以生成段落->句子两层结构，提升 parent/sibling "
            "上下文扩展与 tree-dedup 的效果。"
        )
    return notes


def _table_pipeline_patch(*, pii_types: set[str]) -> dict[str, Any]:
    table_patch: dict[str, Any] = {
        "table_store_enabled": True,
        "table_store_auto_route": True,
        "table_store_auto_row_threshold": int(getattr(settings, "TABLE_STORE_AUTO_ROW_THRESHOLD", 5000) or 5000),
        "table_store_auto_col_threshold": int(getattr(settings, "TABLE_STORE_AUTO_COL_THRESHOLD", 80) or 80),
        "table_store_auto_sheet_threshold": int(getattr(settings, "TABLE_STORE_AUTO_SHEET_THRESHOLD", 5) or 5),
        "table_store_auto_file_bytes_threshold": int(
            getattr(settings, "TABLE_STORE_AUTO_FILE_BYTES_THRESHOLD", 5_000_000) or 5_000_000
        ),
    }
    if bool({"csv", "xls", "xlsx"} & pii_types):
        table_patch["table_store_sample_rows"] = 0
    return table_patch


def _common_text_preprocess_steps() -> list[str]:
    return [
        STEP_REENCODE_UTF8,
        STEP_STRIP_BOM,
        STEP_NORMALIZE_NEWLINES,
        "text.trim_trailing_whitespace",
        "text.remove_zero_width",
        "text.remove_control_chars",
    ]


def _build_ingestion_rules(
    *,
    signals: _SuggestionSignals,
    pii_types: set[str],
    secrets_types: set[str],
) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    html_patch = _pii_secrets_patch(enable_pii=("html" in pii_types), enable_secrets=("html" in secrets_types))
    rules.append(
        _rule(
            rid="html-web",
            name="网页 HTML（去样板/去导航）",
            extensions=[".html", ".htm"],
            preprocess_steps=[
                "html.strip_scripts_styles",
                "html.strip_comments",
                STEP_NORMALIZE_NEWLINES,
                "text.trim_trailing_whitespace",
                "text.remove_zero_width",
                "text.remove_control_chars",
            ],
            parser_backend="auto",
            governance_profile_ref="builtin:html_web",
            pipeline_patch=html_patch,
        )
    )

    pdf_patch = _pii_secrets_patch(enable_pii=("pdf" in pii_types), enable_secrets=("pdf" in secrets_types))
    if signals.scanned_pdfs > 0 or signals.unknown_pdfs > 0:
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

    table_patch = _table_pipeline_patch(pii_types=pii_types)
    rules.append(
        _rule(
            rid="tables-csv-tag",
            name="表格（CSV）：TAG 自动分流（大表→SQL，小表→RAG）",
            extensions=[".csv"],
            preprocess_steps=[
                STEP_REENCODE_UTF8,
                STEP_STRIP_BOM,
                STEP_NORMALIZE_NEWLINES,
            ],
            parser_backend="auto",
            governance_profile_ref=STRUCTURED_DATA_PROFILE_REF,
            pipeline_patch=table_patch,
        )
    )
    rules.append(
        _rule(
            rid="tables-excel-tag",
            name="表格（XLS/XLSX）：TAG 自动分流（大表→SQL，小表→RAG）",
            extensions=[".xls", ".xlsx"],
            preprocess_steps=None,
            parser_backend="auto",
            governance_profile_ref=STRUCTURED_DATA_PROFILE_REF,
            pipeline_patch=table_patch,
        )
    )

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
                STEP_REENCODE_UTF8,
                STEP_STRIP_BOM,
                STEP_NORMALIZE_NEWLINES,
            ],
            parser_backend="auto",
            governance_profile_ref=STRUCTURED_DATA_PROFILE_REF,
            pipeline_patch=structured_patch,
        )
    )

    md_profile = "builtin:wiki_longform" if signals.use_longform else "builtin:kb_default"
    md_patch = _pii_secrets_patch(
        enable_pii=bool({"md", "txt"} & pii_types),
        enable_secrets=bool({"md", "txt"} & secrets_types),
    )
    common_text_preprocess = _common_text_preprocess_steps()
    rules.append(
        _rule(
            rid="chat-exports-txt",
            name="聊天导出（Slack/Teams）：TXT（文件名命中）",
            extensions=[".txt"],
            filename_regex=r"(?i)(slack|teams|chat|conversation|messages?|export|\u804a\u5929|\u4f1a\u8bdd|\u5bf9\u8bdd)",
            preprocess_steps=list(common_text_preprocess),
            parser_backend="auto",
            chunk_strategy="semantic_sentence",
            governance_profile_ref="builtin:chat_exports",
            pipeline_patch=_pii_secrets_patch(
                enable_pii=("txt" in pii_types),
                enable_secrets=("txt" in secrets_types),
            ),
        )
    )
    rules.append(
        _rule(
            rid="markdown-hierarchy-md",
            name="Markdown（层级：段落->句子，可用于层级召回）",
            enabled=False,
            extensions=[".md"],
            preprocess_steps=list(common_text_preprocess),
            parser_backend="auto",
            chunk_strategy="markdown_hierarchy",
            governance_profile_ref=md_profile,
            pipeline_patch=md_patch,
        )
    )
    rules.append(
        _rule(
            rid="markdown-md",
            name="Markdown（按标题分块）",
            extensions=[".md"],
            preprocess_steps=list(common_text_preprocess),
            parser_backend="auto",
            chunk_strategy="markdown_header",
            governance_profile_ref=md_profile,
            pipeline_patch=md_patch,
        )
    )
    rules.append(
        _rule(
            rid="text-hierarchy-txt",
            name="纯文本（层级：段落->句子，可用于层级召回）",
            enabled=False,
            extensions=[".txt"],
            preprocess_steps=list(common_text_preprocess),
            parser_backend="auto",
            chunk_strategy="text_hierarchy",
            governance_profile_ref=md_profile,
            pipeline_patch=md_patch,
        )
    )
    rules.append(
        _rule(
            rid="text-txt",
            name="纯文本（按句子分块）",
            extensions=[".txt"],
            preprocess_steps=list(common_text_preprocess),
            parser_backend="auto",
            chunk_strategy="semantic_sentence",
            governance_profile_ref=md_profile,
            pipeline_patch=md_patch,
        )
    )
    return rules


def _near_dup_manual_review_bucket(
    *,
    scan_run: DBDatasetPrecheckScanRun,
    tenant_id: UUID,
    max_names: int,
) -> dict[str, Any]:
    artifacts = getattr(scan_run, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    near_raw = str(artifacts.get("near_dups_json") or "").strip()
    names: list[str] = []
    total_affected = 0
    if near_raw:
        path = Path(near_raw)
        _assert_artifact_path_under_tenant(tenant_id=tenant_id, path=path)
        if path.exists() and path.is_file():
            obj = json.loads(path.read_text(encoding="utf-8"))
            clusters = obj.get("clusters") if isinstance(obj, dict) and isinstance(obj.get("clusters"), list) else []
            affected: list[str] = []
            for cluster in clusters:
                if not isinstance(cluster, dict):
                    continue
                members = cluster.get("members")
                if isinstance(members, list):
                    for member in members:
                        name = str(member or "").strip()
                        if name:
                            affected.append(name)
            total_affected = len(set(affected))
            names = sorted(set(affected))[:max_names]
    return {"key": "near_dup", "total": int(total_affected), "sample_names": names}


def _manual_review_bucket(
    *,
    key: str,
    jsonl_path: Path,
    max_names: int,
) -> dict[str, Any]:
    res = _list_finding_from_jsonl(jsonl_path=jsonl_path, finding_key=key, skip=0, limit=max_names or 1)
    return {
        "key": key,
        "total": int(res.total),
        "sample_names": [x.name for x in (res.items or [])],
    }


def _build_manual_review_buckets(
    *,
    scan_run: DBDatasetPrecheckScanRun,
    jsonl_path: Path,
    tenant_id: UUID,
    max_names: int,
) -> list[dict[str, Any]]:
    buckets: list[dict[str, Any]] = []
    for key in _MANUAL_REVIEW_KEYS:
        try:
            if key == "near_dup":
                buckets.append(
                    _near_dup_manual_review_bucket(
                        scan_run=scan_run,
                        tenant_id=tenant_id,
                        max_names=max_names,
                    )
                )
                continue
            buckets.append(_manual_review_bucket(key=key, jsonl_path=jsonl_path, max_names=max_names))
        except Exception:
            buckets.append({"key": key, "total": 0, "sample_names": []})
    return buckets


def build_ingestion_policy_suggestion(
    scan_run: DBDatasetPrecheckScanRun,
    *,
    tenant_id: UUID,
    before_policy: IngestionPolicy | None = None,
    max_names_per_bucket: int = 50,
) -> dict[str, Any]:
    """
    Build a suggested ingestion policy from a precheck run.
    """
    max_names = max(0, min(int(max_names_per_bucket or 0), 2000))
    summary = _summary_or_404(scan_run)
    jsonl_path = _load_jsonl_path(scan_run, tenant_id=tenant_id)
    signals = _extract_suggestion_signals(summary)
    pii_types, secrets_types = _collect_sensitive_file_types(jsonl_path)
    notes = _build_suggestion_notes(signals)
    rules = _build_ingestion_rules(
        signals=signals,
        pii_types=pii_types,
        secrets_types=secrets_types,
    )
    model = IngestionPolicy(version="1", rules=[IngestionRule(**r) for r in rules])
    normalized = validate_and_normalize_ingestion_policy(model)
    policy_diff = diff_ingestion_policies(before_policy, normalized)
    buckets = _build_manual_review_buckets(
        scan_run=scan_run,
        jsonl_path=jsonl_path,
        tenant_id=tenant_id,
        max_names=max_names,
    )

    return {
        "generated_at": _now_utc().isoformat(),
        "before_policy": before_policy.model_dump() if before_policy is not None else None,
        "policy": normalized.model_dump(),
        "policy_diff": policy_diff,
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

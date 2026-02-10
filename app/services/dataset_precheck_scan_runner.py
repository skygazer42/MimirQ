"""
Dataset precheck scan runner.

This scans a local folder (before ingestion) and produces:
- per-file records (JSONL on disk) for drill-down
- an aggregated summary snapshot (stored in DB)

Security:
- local scan must be explicitly enabled (LOCAL_SCAN_ENABLED)
- scan root must be under UPLOAD_DIR or one of LOCAL_SCAN_ROOTS
- symlinks are not followed (by design)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.token_utils import estimate_tokens
from app.core.optional_deps import optional_import
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.rag.core.logging import get_logger
from app.rag.preprocessing.pii_anonymizer import anonymize_pii, find_pii_matches
from app.rag.preprocessing.secrets import find_secret_matches, redact_secrets
from app.services.dataset_profile_utils import (
    FILE_SIZE_BINS,
    TEXT_LENGTH_BINS,
    histogram,
    percentile_from_sorted,
    safe_int,
)

logger = get_logger("services.dataset_precheck_scan")


FINDING_KEY_REASONS: dict[str, dict[str, Any]] = {
    "parse_failed": {
        "label": "解析/读取失败",
        "severity": "error",
        "description": "文件无法读取或解析（权限/损坏/依赖缺失）。",
    },
    "pdf_scanned": {
        "label": "疑似扫描 PDF",
        "severity": "warning",
        "description": "可能需要 OCR/更强 PDF 解析链路。",
    },
    "pdf_unknown": {
        "label": "PDF 类型未知",
        "severity": "info",
        "description": "无法获取 PDF 指标（解析失败/加密/权限）。",
    },
    "pii": {
        "label": "PII 命中",
        "severity": "warning",
        "description": "命中手机号/邮箱/身份证等（抽样文本）。建议复核脱敏策略。",
    },
    "secrets": {
        "label": "密钥/Token 命中",
        "severity": "warning",
        "description": "命中疑似密钥/Token（抽样文本）。建议脱敏或隔离。",
    },
    "exact_dup": {
        "label": "完全重复候选",
        "severity": "info",
        "description": "基于 file_sha256 的完全重复候选（需开启 compute_file_hash）。",
    },
    "near_dup": {
        "label": "近重复候选（版本冲突）",
        "severity": "info",
        "description": "基于文本样本的 SimHash 近重复候选（需开启 enable_near_dup；需要人工复核）。",
    },
    "large_spreadsheet": {
        "label": "大型表格（建议结构化方案）",
        "severity": "info",
        "description": "行数过多的表格更适合 Text-to-SQL/结构化索引，而非纯向量检索。",
    },
    "wide_spreadsheet": {
        "label": "宽表（列数过多）",
        "severity": "info",
        "description": "列数过多的表格通常不适合纯 RAG；建议走 TAG/SQL 或先做结构化清洗。",
    },
    "many_sheets_spreadsheet": {
        "label": "多 Sheet 表格",
        "severity": "info",
        "description": "Sheet 数过多可能意味着多维报表/账表；建议拆分或优先走结构化方案。",
    },
    "merged_heavy_spreadsheet": {
        "label": "合并单元格较多（结构复杂）",
        "severity": "info",
        "description": "合并单元格占比过高往往会增加解析/入库难度，建议专项处理（表格专用转换）。",
    },
}


TEXTLIKE_EXTS = {
    ".txt",
    ".md",
    ".rst",
    ".adoc",
    ".asciidoc",
    ".tex",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    ".sql",
    ".log",
    ".patch",
    ".diff",
    ".csv",
    ".json",
    ".jsonl",
    ".ndjson",
    ".xml",
    ".rss",
    ".atom",
    ".graphql",
    ".gql",
    ".proto",
    ".tf",
    ".hcl",
    ".html",
    ".htm",
}


def _hash64(text: str) -> int:
    # Stable 64-bit hash for SimHash features (blake2b is fast and deterministic).
    h = hashlib.blake2b((text or "").encode("utf-8", errors="ignore"), digest_size=8).digest()
    return int.from_bytes(h, byteorder="big", signed=False)


def _simhash64(text: str, *, max_tokens: int = 2000) -> int:
    """
    Compute a simple 64-bit SimHash for near-duplicate detection (best-effort).

    We intentionally keep this dependency-free and conservative:
    - tokenize by simple regex (latin alnum + CJK)
    - cap token count to avoid large CPU spikes during scans
    """
    s = (text or "").strip()
    if not s:
        return 0

    tokens = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", s.lower())
    if not tokens:
        return 0
    if len(tokens) > max_tokens:
        tokens = tokens[:max_tokens]

    counts = Counter(tokens)
    # 64-dim signed accumulator.
    v = [0] * 64
    for tok, w in counts.items():
        hv = _hash64(tok)
        weight = int(w)
        for i in range(64):
            if (hv >> i) & 1:
                v[i] += weight
            else:
                v[i] -= weight

    out = 0
    for i, val in enumerate(v):
        if val > 0:
            out |= 1 << i
    return int(out)


def _hamming_distance64(a: int, b: int) -> int:
    return int((int(a) ^ int(b)).bit_count())


def _bucket_file_size_label(size: int) -> str:
    v = int(size or 0)
    for spec in FILE_SIZE_BINS:
        try:
            if spec.contains(v):
                return str(spec.label)
        except Exception:
            continue
    return "unknown"


def _build_samples_payload(*, jsonl_path: Path, target_size: int) -> dict[str, Any]:
    """
    Build representative + problem-focused samples from a precheck JSONL artifact.

    Output is designed for pricing/POC alignment (shareable when redact_paths=true).
    """
    target_size = max(0, min(int(target_size or 0), 2000))
    if target_size <= 0:
        return {"requested": 0, "representative": [], "needs_review": {}, "top_large_files": [], "top_long_text": []}

    # Base strata: (file_type, size_bin, pdf_state).
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    findings_buckets: dict[str, list[dict[str, Any]]] = {}
    largest: list[dict[str, Any]] = []
    longest: list[dict[str, Any]] = []

    def _push_top(arr: list[dict[str, Any]], item: dict[str, Any], *, key: str, top_k: int = 20) -> None:
        arr.append(item)
        arr.sort(key=lambda x: int(x.get(key) or 0), reverse=True)
        if len(arr) > top_k:
            del arr[top_k:]

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            file_type = str(obj.get("file_type") or "unknown")
            file_size = int(obj.get("file_size") or 0)
            pdf_scanned = obj.get("pdf_scanned")
            pdf_state = "na"
            if file_type.lower() == "pdf":
                if pdf_scanned is True:
                    pdf_state = "scan"
                elif pdf_scanned is False:
                    pdf_state = "text"
                else:
                    pdf_state = "unknown"

            size_bin = _bucket_file_size_label(file_size)
            key = (file_type.lower(), size_bin, pdf_state)
            groups.setdefault(key, []).append(obj)

            findings = obj.get("findings")
            if isinstance(findings, list):
                for fk in findings:
                    fkey = str(fk or "").strip().lower()
                    if not fkey:
                        continue
                    findings_buckets.setdefault(fkey, []).append(obj)

            _push_top(largest, obj, key="file_size", top_k=20)
            _push_top(longest, obj, key="text_characters", top_k=20)

    # Representative picks: choose one file per stratum.
    rep: list[dict[str, Any]] = []
    ordered_groups = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if len(ordered_groups) <= target_size:
        chosen = ordered_groups
    else:
        half = max(1, target_size // 2)
        chosen = ordered_groups[:half] + ordered_groups[-(target_size - half) :]

    picked_names: set[str] = set()
    for _k, items in chosen:
        items_sorted = sorted(items, key=lambda o: str(o.get("name") or ""))
        if not items_sorted:
            continue
        item = items_sorted[0]
        nm = str(item.get("name") or "")
        if nm and nm not in picked_names:
            picked_names.add(nm)
            rep.append(item)
        if len(rep) >= target_size:
            break

    # Problem-focused samples: per finding bucket (cap per finding).
    needs_review: dict[str, list[dict[str, Any]]] = {}
    for fk, items in findings_buckets.items():
        if fk not in {
            "parse_failed",
            "pdf_scanned",
            "pdf_unknown",
            "pii",
            "secrets",
            "large_spreadsheet",
            "wide_spreadsheet",
            "many_sheets_spreadsheet",
            "merged_heavy_spreadsheet",
            "near_dup",
            "exact_dup",
        }:
            continue
        items_sorted = sorted(items, key=lambda o: int(o.get("file_size") or 0), reverse=True)
        needs_review[fk] = items_sorted[: min(10, max(1, target_size // 6))]

    return {
        "requested": int(target_size),
        "representative": rep,
        "needs_review": needs_review,
        "top_large_files": largest,
        "top_long_text": longest,
        "strata_count": int(len(groups)),
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_csv(raw: str) -> list[str]:
    parts = [p.strip() for p in str(raw or "").split(",")]
    return [p for p in parts if p]


def _assert_local_scan_enabled() -> None:
    if not bool(getattr(settings, "LOCAL_SCAN_ENABLED", False)):
        raise ValueError("local_scan_disabled")


def _assert_scan_root_allowed(root: Path) -> None:
    """
    Ensure root is within UPLOAD_DIR or one of LOCAL_SCAN_ROOTS.

    This is a safety guard against arbitrary file reads in shared deployments.
    """
    upload_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads").resolve(strict=False)
    allowed: list[Path] = [upload_root]
    for p in _parse_csv(str(getattr(settings, "LOCAL_SCAN_ROOTS", "") or "")):
        try:
            allowed.append(Path(p).expanduser().resolve(strict=False))
        except Exception:
            continue

    resolved = root.expanduser().resolve(strict=False)
    for base in allowed:
        try:
            resolved.relative_to(base)
            return
        except Exception:
            continue
    raise ValueError("scan_root_denied")


def _safe_hash_file(path: Path, *, algo: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _read_text_sample(path: Path, *, max_bytes: int) -> tuple[str, bool]:
    """
    Best-effort read a text sample from a file.

    Returns (text, estimated), where estimated means sample-only (file too large).
    """
    size = path.stat().st_size
    max_bytes = max(1_000, int(max_bytes or 0))
    read_bytes = min(size, max_bytes)
    with path.open("rb") as f:
        buf = f.read(read_bytes)
    # Best-effort decode: utf-8 with replacement. We only need rough metrics/hits.
    text = buf.decode("utf-8", errors="ignore")
    return text, bool(size > read_bytes)


@lru_cache(maxsize=1)
def _get_pdfplumber():  # noqa: ANN201
    return optional_import("pdfplumber", feature="precheck_pdf_text_sample")


@lru_cache(maxsize=1)
def _get_openpyxl():  # noqa: ANN201
    return optional_import("openpyxl", feature="precheck_xlsx_stats")


def _pdf_text_sample(
    path: Path, *, sample_pages: int, max_chars: int = 200_000
) -> tuple[str, bool, int, list[int | None], str | None]:
    """
    Extract a best-effort text sample from first N pages of a PDF.

    Returns (text, estimated, page_count, per_page_chars) where per_page_chars is
    a list aligned with sampled pages (None means extraction failed for that page).
    """
    pdfplumber = _get_pdfplumber()
    if pdfplumber is None:
        return "", True, 0, [], "dependency_missing:pdfplumber (pip install pdfplumber)"

    try:
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)
            n = max(1, min(int(sample_pages or 1), page_count))
            chunks: list[str] = []
            per_page_chars: list[int | None] = []
            total = 0
            for p in pdf.pages[:n]:
                try:
                    t = p.extract_text() or ""
                except Exception:
                    t = ""
                    per_page_chars.append(None)
                    continue
                per_page_chars.append(len(t))
                if not t:
                    continue
                if total + len(t) > max_chars:
                    t = t[: max(0, max_chars - total)]
                chunks.append(t)
                total += len(t)
                if total >= max_chars:
                    break
        text = "\n".join(chunks)
        estimated = bool(page_count > n)
        return text, estimated, int(page_count), per_page_chars, None
    except Exception as exc:  # noqa: BLE001
        return "", True, 0, [], f"parse_failed:{type(exc).__name__}"


def _build_pdf_page_breakdown(
    *,
    page_count: int,
    per_page_chars: list[int | None],
    scan_max_chars: int,
    text_min_chars: int,
) -> dict[str, Any]:
    scanned_pages = 0
    text_pages = 0
    low_density_pages = 0
    unknown_pages = 0

    sampled_pages = int(len(per_page_chars or []))
    for ch in per_page_chars or []:
        if ch is None:
            unknown_pages += 1
            continue
        chars = int(ch or 0)
        if chars <= int(scan_max_chars):
            scanned_pages += 1
        elif chars >= int(text_min_chars):
            text_pages += 1
        else:
            low_density_pages += 1

    denom = max(1, sampled_pages - unknown_pages)
    scan_ratio = float(scanned_pages) / float(denom)
    low_density_ratio = float(low_density_pages) / float(denom)

    return {
        "page_count": int(page_count or 0),
        "sampled_pages": int(sampled_pages),
        "scanned_pages": int(scanned_pages),
        "text_pages": int(text_pages),
        "low_density_pages": int(low_density_pages),
        "unknown_pages": int(unknown_pages),
        "scan_ratio": round(scan_ratio, 4),
        "low_density_ratio": round(low_density_ratio, 4),
    }


def _sanitize_display_name(rel_path: str) -> str:
    # Keep it stable and safe for HTML/JSON; do not allow control chars.
    s = str(rel_path or "").replace("\\", "/").strip()
    s = re.sub(r"[\x00-\x1f\x7f]+", "", s)
    return s[:1024] if len(s) > 1024 else s


def _xlsx_spreadsheet_stats(path: Path, *, max_sheets: int = 3) -> tuple[dict[str, Any] | None, str | None]:
    """
    Best-effort spreadsheet stats for .xlsx (read-only).

    Note: This is intentionally lightweight and may be approximate for files with
    complex formatting. It should never raise.
    """
    openpyxl = _get_openpyxl()
    if openpyxl is None:
        return None, "dependency_missing:openpyxl (pip install openpyxl)"

    wb = None
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        sheetnames = list(getattr(wb, "sheetnames", None) or [])
        sheet_count = int(len(sheetnames))
        max_rows = 0
        max_cols = 0
        merged_area = 0

        for idx, name in enumerate(sheetnames[: max(1, int(max_sheets or 1))]):
            ws = wb[name]
            r = int(getattr(ws, "max_row", 0) or 0)
            c = int(getattr(ws, "max_column", 0) or 0)
            max_rows = max(max_rows, r)
            max_cols = max(max_cols, c)

            # Only compute merged cells on the first sheet (cheap signal).
            if idx == 0:
                merged_cells = getattr(ws, "merged_cells", None)
                ranges = list(getattr(merged_cells, "ranges", None) or [])
                # Cap range count to avoid pathological files.
                for rng in ranges[:5000]:
                    try:
                        merged_area += int(rng.size)  # type: ignore[attr-defined]
                    except Exception:
                        try:
                            merged_area += int((rng.max_row - rng.min_row + 1) * (rng.max_col - rng.min_col + 1))  # type: ignore[attr-defined]
                        except Exception:
                            continue

        total_area = max(1, int(max_rows) * int(max_cols))
        merged_ratio = float(merged_area) / float(total_area)
        if merged_ratio < 0.0:
            merged_ratio = 0.0
        if merged_ratio > 1.0:
            merged_ratio = 1.0

        return {
            "row_count": int(max_rows),
            "col_count": int(max_cols),
            "sheet_count": int(sheet_count),
            "merged_cell_ratio": round(float(merged_ratio), 6),
            "estimated_rows": False,
            "estimated_cols": False,
        }, None
    except Exception as exc:  # noqa: BLE001
        return None, f"parse_failed:{type(exc).__name__}"
    finally:
        try:
            if wb is not None:
                wb.close()
        except Exception:
            pass


def _mask_pii_value(kind: str, raw: str) -> str:
    k = (kind or "").strip().lower()
    s = (raw or "").strip()
    if not s:
        return "[REDACTED]"
    if k == "email":
        if "@" not in s:
            return "[REDACTED]"
        local, domain = s.split("@", 1)
        head = (local[:1] + "***") if local else "***"
        return f"{head}@{domain}"
    if k == "ip":
        parts = s.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3] + ["***"])
        return "[REDACTED]"
    if k in {"phone"}:
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) >= 7:
            return f"{digits[:3]}****{digits[-2:]}"
        return "[REDACTED]"
    if k == "credit_card":
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) >= 8:
            return f"{digits[:4]}****{digits[-4:]}"
        return "[REDACTED]"
    if k == "cn_id":
        if len(s) >= 10:
            return f"{s[:6]}********{s[-2:]}"
        return "[REDACTED]"
    if k == "ssn":
        return "***-**-****"
    return "[REDACTED]"


def _mask_secret_value(kind: str, raw: str) -> str:
    k = (kind or "").strip().lower()
    s = (raw or "").strip()
    if not s:
        return "[SECRET]"
    if k == "openai_key":
        return "sk-***"
    if k == "github_token":
        if s.startswith("ghp_"):
            return "ghp_***"
        if s.startswith("github_pat_"):
            return "github_pat_***"
        return "[SECRET]"
    if k == "aws_access_key":
        return (s[:4] + "***") if len(s) >= 4 else "[SECRET]"
    if k == "slack_token":
        # xox[baprs]-...
        prefix = s.split("-", 1)[0]
        return f"{prefix}-***" if prefix else "[SECRET]"
    if k == "bearer_token":
        return "Bearer ***"
    if k == "private_key":
        return "-----BEGIN PRIVATE KEY----- ... -----END PRIVATE KEY-----"
    return "[SECRET]"


@dataclass
class _FileRecord:
    name: str
    file_type: str
    file_size: int
    file_mtime: int = 0
    text_characters: int = 0
    text_tokens_est: int = 0
    estimated_text: bool = False
    pdf_scanned: Optional[bool] = None
    pdf_pages: Optional[dict[str, Any]] = None
    spreadsheet: Optional[dict[str, Any]] = None
    text_simhash64: Optional[str] = None
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    pii_samples: list[dict[str, Any]] = field(default_factory=list)
    secrets_samples: list[dict[str, Any]] = field(default_factory=list)
    file_sha256: Optional[str] = None
    findings: list[str] = field(default_factory=list)
    error_message: Optional[str] = None


def _iter_files(root: Path, *, max_files: int) -> Iterable[Path]:
    # Use os.walk to avoid following symlinks by default.
    root_resolved = root.resolve(strict=False)
    count = 0
    for dirpath, dirnames, filenames in os.walk(str(root), topdown=True, followlinks=False):
        # Skip hidden dirs by default (can be added later via config).
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            path = Path(dirpath) / fn
            # Defense-in-depth: do not follow symlinks (files or dirs). `os.walk(... followlinks=False)`
            # only prevents descending into symlink *directories*; symlink files still appear in filenames.
            try:
                if path.is_symlink():
                    continue
            except Exception:
                continue
            # Ensure the resolved path stays within the scan root to prevent symlink escape.
            try:
                path.resolve(strict=False).relative_to(root_resolved)
            except Exception:
                continue

            if not path.is_file():
                continue
            yield path
            count += 1
            if count >= max_files:
                return


def run_dataset_precheck_scan(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> dict[str, Any]:
    """
    Execute a dataset precheck scan run.

    Returns a small stats dict for logs/worker result.
    """
    run = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if run is None:
        raise ValueError("scan_run_not_found")

    # Mark running.
    run.status = "running"
    run.progress = 0
    run.started_at = _now_utc()
    run.error_message = None
    db.commit()

    cfg = dict(getattr(run, "config", None) or {})
    root_path = str(cfg.get("root_path") or "").strip()
    if not root_path:
        raise ValueError("root_path_required")

    _assert_local_scan_enabled()
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError("root_path_not_found")
    _assert_scan_root_allowed(root)

    max_files_cap = safe_int(getattr(settings, "PRECHECK_SCAN_MAX_FILES", 20_000), default=20_000)
    requested_max_files = cfg.get("max_files")
    max_files_req = safe_int(requested_max_files, default=0)
    max_files = max_files_cap if max_files_req <= 0 else min(max_files_cap, max_files_req)

    max_total_bytes = safe_int(getattr(settings, "PRECHECK_SCAN_MAX_TOTAL_BYTES", 0), default=0)
    text_max_bytes = safe_int(
        cfg.get("text_extract_max_bytes") or getattr(settings, "PRECHECK_TEXT_EXTRACT_MAX_BYTES", 2_000_000),
        default=2_000_000,
    )
    pdf_sample_pages = safe_int(
        cfg.get("pdf_sample_pages") or getattr(settings, "PRECHECK_PDF_SAMPLE_PAGES", 3),
        default=3,
    )

    enable_pdf_quality = bool(cfg.get("enable_pdf_quality", True))
    enable_text_extract = bool(cfg.get("enable_text_extract", True))
    enable_pii = bool(cfg.get("enable_pii", False))
    enable_secrets = bool(cfg.get("enable_secrets", False))
    compute_file_hash = bool(cfg.get("compute_file_hash", False))
    redact_paths = bool(cfg.get("redact_paths", False))

    enable_pii_samples = bool(cfg.get("enable_pii_samples", False))
    pii_context_chars = safe_int(cfg.get("pii_context_chars") or 50, default=50)
    pii_context_chars = max(0, min(pii_context_chars, 500))
    pii_max_samples_per_file = safe_int(cfg.get("pii_max_samples_per_file") or 5, default=5)
    pii_max_samples_per_file = max(0, min(pii_max_samples_per_file, 50))

    enable_secrets_samples = bool(cfg.get("enable_secrets_samples", False))
    secrets_context_chars = safe_int(cfg.get("secrets_context_chars") or 50, default=50)
    secrets_context_chars = max(0, min(secrets_context_chars, 500))
    secrets_max_samples_per_file = safe_int(cfg.get("secrets_max_samples_per_file") or 5, default=5)
    secrets_max_samples_per_file = max(0, min(secrets_max_samples_per_file, 50))

    enable_near_dup = bool(cfg.get("enable_near_dup", False))
    near_dup_hamming_threshold = safe_int(cfg.get("near_dup_hamming_threshold") or 5, default=5)
    near_dup_hamming_threshold = max(0, min(near_dup_hamming_threshold, 32))
    near_dup_max_pairs = safe_int(cfg.get("near_dup_max_pairs") or 5000, default=5000)
    near_dup_max_pairs = max(0, min(near_dup_max_pairs, 200_000))

    enable_sampling = bool(cfg.get("enable_sampling", True))
    sample_size = safe_int(cfg.get("sample_size") or 60, default=60)
    sample_size = max(0, min(sample_size, 2000))

    # Optional: reuse unchanged file records from a previous scan run (incremental scans).
    reuse_unchanged_files = bool(cfg.get("reuse_unchanged_files", False))
    reuse_from_scan_run_id: UUID | None = None
    raw_reuse_id = cfg.get("reuse_from_scan_run_id")
    if raw_reuse_id:
        try:
            reuse_from_scan_run_id = UUID(str(raw_reuse_id))
        except Exception:
            reuse_from_scan_run_id = None

    # Shareable mode should not include per-match contexts (even if toggled on).
    if redact_paths:
        enable_pii_samples = False
        enable_secrets_samples = False

    pdf_scan_max_chars = safe_int(
        cfg.get("pdf_min_text_chars_per_page") or getattr(settings, "PRECHECK_PDF_MIN_TEXT_CHARS_PER_PAGE", 50),
        default=50,
    )
    pdf_text_min_chars = safe_int(
        cfg.get("pdf_text_chars_per_page") or getattr(settings, "PRECHECK_PDF_TEXT_CHARS_PER_PAGE", 200),
        default=200,
    )
    pdf_scan_ratio_threshold = float(
        cfg.get("pdf_scan_ratio_threshold")
        if cfg.get("pdf_scan_ratio_threshold") is not None
        else float(getattr(settings, "PRECHECK_PDF_SCAN_RATIO_THRESHOLD", 0.7) or 0.7)
    )
    spreadsheet_large_row_threshold = safe_int(
        getattr(settings, "PRECHECK_SPREADSHEET_LARGE_ROW_THRESHOLD", 5000),
        default=5000,
    )
    spreadsheet_wide_col_threshold = safe_int(
        getattr(settings, "PRECHECK_SPREADSHEET_WIDE_COL_THRESHOLD", 80),
        default=80,
    )
    spreadsheet_sheet_threshold = safe_int(
        getattr(settings, "PRECHECK_SPREADSHEET_SHEET_THRESHOLD", 5),
        default=5,
    )
    spreadsheet_merged_ratio_threshold = float(getattr(settings, "PRECHECK_SPREADSHEET_MERGED_RATIO_THRESHOLD", 0.15) or 0.15)
    if spreadsheet_merged_ratio_threshold < 0.0:
        spreadsheet_merged_ratio_threshold = 0.0
    if spreadsheet_merged_ratio_threshold > 1.0:
        spreadsheet_merged_ratio_threshold = 1.0

    # Prepare artifact dir and JSONL writer.
    artifact_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads") / str(tenant_id) / "precheck" / str(run.id)
    artifact_root.mkdir(parents=True, exist_ok=True)
    jsonl_path = (artifact_root / "files.jsonl").resolve(strict=False)
    samples_path = (artifact_root / "samples.json").resolve(strict=False)

    # Enumerate file candidates first to compute total for progress (bounded by max_files).
    allowed_exts = set(getattr(settings, "allowed_extensions_list", []) or [])
    candidates: list[Path] = []
    total_bytes_seen = 0
    for p in _iter_files(root, max_files=max_files):
        ext = p.suffix.lower()
        if ext not in allowed_exts:
            continue
        try:
            size = int(p.stat().st_size)
        except Exception:
            size = 0
        if max_total_bytes > 0 and (total_bytes_seen + size) > max_total_bytes:
            break
        candidates.append(p)
        total_bytes_seen += size

    total = len(candidates)
    if total == 0:
        run.status = "completed"
        run.progress = 100
        run.finished_at = _now_utc()
        run.summary = {
            "dataset_id": str(dataset_id),
            "scan_run_id": str(run.id),
            "generated_at": run.finished_at.isoformat(),
            "total_files": 0,
            "total_size_bytes": 0,
            "by_file_type": {},
            "file_size_histogram": [],
            "length_percentiles": {"p25": 0, "p50": 0, "p75": 0, "p90": 0, "p99": 0},
            "length_histogram": [],
            "pdf_scan": {"scanned": 0, "not_scanned": 0, "unknown": 0},
            "pdf_detection": {
                "sample_pages": int(pdf_sample_pages),
                "scan_max_chars_per_page": int(pdf_scan_max_chars),
                "text_min_chars_per_page": int(pdf_text_min_chars),
                "scan_ratio_threshold": float(pdf_scan_ratio_threshold),
            },
            "pii_hits_total": {},
            "secrets_hits_total": {},
            "findings": [
                {"key": k, "label": v.get("label", k), "severity": v.get("severity", "info"), "count": 0, "description": v.get("description")}
                for k, v in FINDING_KEY_REASONS.items()
            ],
        }
        run.artifacts = {"files_jsonl": str(jsonl_path), "root_path": "[REDACTED]" if redact_paths else str(root)}
        db.commit()
        return {"ok": True, "files": 0}

    last_progress_write = time.monotonic()
    cancelled = False

    def flush_progress(processed: int, *, force: bool = False) -> None:
        nonlocal last_progress_write
        nonlocal cancelled
        now = time.monotonic()
        if not force and (now - last_progress_write) < 0.5:
            return
        last_progress_write = now
        pct = int((processed / max(1, total)) * 100)
        run.progress = max(0, min(100, pct))
        db.commit()
        # Allow cooperative cancellation from another session (API).
        try:
            db.refresh(run)
            if str(getattr(run, "status", "") or "").lower() == "cancelled":
                cancelled = True
        except Exception:
            # Best-effort: ignore refresh failures.
            pass

    # Aggregation accumulators.
    by_type: dict[str, int] = {}
    file_sizes: list[int] = []
    text_lengths: list[int] = []
    pii_totals: dict[str, int] = {}
    secrets_totals: dict[str, int] = {}
    pdf_scanned = 0
    pdf_not_scanned = 0
    pdf_unknown = 0
    finding_counts: dict[str, int] = {k: 0 for k in FINDING_KEY_REASONS.keys()}

    # For exact-dup finding: sha256 -> count.
    sha_counts: dict[str, int] = {}

    # For near-dup finding: (display_name, simhash64) pairs.
    simhash_entries: list[tuple[str, int]] = []

    errors = 0
    reused_files = 0

    # Optional: load a previous JSONL snapshot for incremental reuse.
    prev_records: dict[str, dict[str, Any]] = {}
    if reuse_unchanged_files and not redact_paths:
        # Pick the previous run (explicit id, else latest completed run for this dataset).
        prev_run: DBDatasetPrecheckScanRun | None = None
        if reuse_from_scan_run_id is not None:
            prev_run = (
                db.query(DBDatasetPrecheckScanRun)
                .filter(
                    DBDatasetPrecheckScanRun.id == reuse_from_scan_run_id,
                    DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                    DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                )
                .first()
            )
        else:
            prev_run = (
                db.query(DBDatasetPrecheckScanRun)
                .filter(
                    DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                    DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                    DBDatasetPrecheckScanRun.status == "completed",
                )
                .order_by(DBDatasetPrecheckScanRun.created_at.desc())
                .first()
            )

        def _cfg_subset(d: dict[str, Any], keys: set[str]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k in keys:
                if k in d:
                    out[k] = d.get(k)
            return out

        if prev_run is not None:
            prev_cfg = dict(getattr(prev_run, "config", None) or {})
            prev_root = str(prev_cfg.get("root_path") or "").strip()
            if prev_root and prev_root == root_path and bool(prev_cfg.get("redact_paths", False)) is False:
                # Only reuse when the feature-affecting config matches (avoid confusing deltas).
                cfg_keys = {
                    "enable_pdf_quality",
                    "enable_text_extract",
                    "enable_pii",
                    "enable_secrets",
                    "compute_file_hash",
                    "pdf_sample_pages",
                    "text_extract_max_bytes",
                    "pdf_min_text_chars_per_page",
                    "pdf_text_chars_per_page",
                    "pdf_scan_ratio_threshold",
                    "enable_pii_samples",
                    "pii_context_chars",
                    "pii_max_samples_per_file",
                    "enable_secrets_samples",
                    "secrets_context_chars",
                    "secrets_max_samples_per_file",
                    "enable_near_dup",
                    "near_dup_hamming_threshold",
                    "near_dup_max_pairs",
                }
                if _cfg_subset(cfg, cfg_keys) == _cfg_subset(prev_cfg, cfg_keys):
                    prev_artifacts = getattr(prev_run, "artifacts", None)
                    prev_artifacts = prev_artifacts if isinstance(prev_artifacts, dict) else {}
                    prev_jsonl_raw = str(prev_artifacts.get("files_jsonl") or "").strip()
                    prev_jsonl = Path(prev_jsonl_raw) if prev_jsonl_raw else None
                    if prev_jsonl and prev_jsonl.exists() and prev_jsonl.is_file():
                        # Defense-in-depth: only reuse artifacts under the same tenant root.
                        try:
                            upload_root = Path(getattr(settings, "UPLOAD_DIR", "./uploads") or "./uploads").resolve(strict=False)
                            tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
                            prev_jsonl.resolve(strict=False).relative_to(tenant_root)
                        except Exception:
                            prev_jsonl = None
                    if prev_jsonl and prev_jsonl.exists() and prev_jsonl.is_file():
                        try:
                            with prev_jsonl.open("r", encoding="utf-8") as f:
                                for line in f:
                                    s = (line or "").strip()
                                    if not s:
                                        continue
                                    try:
                                        obj = json.loads(s)
                                    except Exception:
                                        continue
                                    if not isinstance(obj, dict):
                                        continue
                                    name = str(obj.get("name") or "").strip()
                                    if not name:
                                        continue
                                    prev_records[name] = obj
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Failed to load previous precheck JSONL (reuse disabled): %s", str(exc)[:200])
                else:
                    logger.info("Skip reuse_unchanged_files due to config mismatch (scan_run_id=%s)", str(getattr(prev_run, "id", "")))
            else:
                logger.info("Skip reuse_unchanged_files due to root_path mismatch or redacted prev run")
    elif reuse_unchanged_files and redact_paths:
        logger.info("Skip reuse_unchanged_files in redact_paths mode")

    # Stream JSONL writes to avoid holding all file records in memory.
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for idx, path in enumerate(candidates, start=1):
            if cancelled:
                break
            rel = ""
            try:
                rel = str(path.relative_to(root)).replace("\\", "/")
            except Exception:
                rel = path.name

            ext = path.suffix.lower()
            file_type = ext.lstrip(".") if ext.startswith(".") else (path.suffix or "").lower().lstrip(".") or "unknown"
            try:
                st = path.stat()
                size = int(st.st_size)
                mtime = int(st.st_mtime)
            except Exception:
                size = 0
                mtime = 0

            rec = _FileRecord(
                name=_sanitize_display_name(rel) if not redact_paths else f"FILE_{idx:06d}{ext}",
                file_type=file_type or "unknown",
                file_size=int(size),
                file_mtime=int(mtime),
            )

            try:
                # Incremental reuse: keep unchanged file records without re-reading content.
                if prev_records and not redact_paths:
                    prev = prev_records.get(rec.name)
                    if isinstance(prev, dict):
                        try:
                            prev_size = int(prev.get("file_size") or 0)
                            prev_mtime = int(prev.get("file_mtime") or 0)
                        except Exception:
                            prev_size = -1
                            prev_mtime = -1
                        prev_findings = prev.get("findings") if isinstance(prev.get("findings"), list) else []
                        has_parse_failed = "parse_failed" in {str(x or "").strip().lower() for x in prev_findings}
                        if not has_parse_failed and prev_size == rec.file_size and prev_mtime == rec.file_mtime:
                            # We intentionally skip reuse of parse_failed files so a new environment
                            # (deps/permissions) can re-evaluate them.
                            reused_files += 1
                            # Preserve stable name (relative path) and current fs stats.
                            prev = dict(prev)
                            prev["name"] = rec.name
                            prev["file_size"] = rec.file_size
                            prev["file_mtime"] = rec.file_mtime

                            # Aggregation (best-effort) from previous record.
                            by_type[str(prev.get("file_type") or rec.file_type or "unknown")] = by_type.get(
                                str(prev.get("file_type") or rec.file_type or "unknown"),
                                0,
                            ) + 1
                            file_sizes.append(int(prev.get("file_size") or 0))
                            tl = int(prev.get("text_characters") or 0)
                            if tl > 0:
                                text_lengths.append(tl)
                            # PDF scan counts.
                            pdf_sc = prev.get("pdf_scanned")
                            if pdf_sc is True:
                                pdf_scanned += 1
                            elif pdf_sc is False:
                                pdf_not_scanned += 1
                            elif str(prev.get("file_type") or "").strip().lower() == "pdf":
                                pdf_unknown += 1

                            # Findings counts.
                            if isinstance(prev_findings, list):
                                for fk in prev_findings:
                                    k = str(fk or "").strip().lower()
                                    if k in finding_counts:
                                        finding_counts[k] += 1

                            # Totals for pii/secrets.
                            pii_hits = prev.get("pii_hits") if isinstance(prev.get("pii_hits"), dict) else {}
                            for k, v in pii_hits.items():
                                try:
                                    pii_totals[str(k)] = pii_totals.get(str(k), 0) + int(v or 0)
                                except Exception:
                                    continue
                            secrets_hits = prev.get("secrets_hits") if isinstance(prev.get("secrets_hits"), dict) else {}
                            for k, v in secrets_hits.items():
                                try:
                                    secrets_totals[str(k)] = secrets_totals.get(str(k), 0) + int(v or 0)
                                except Exception:
                                    continue

                            # Near-dup entries and exact-dup entries.
                            if enable_near_dup:
                                sim_hex = str(prev.get("text_simhash64") or "").strip().lower()
                                if sim_hex:
                                    try:
                                        simhash_entries.append((rec.name, int(sim_hex, 16)))
                                    except Exception:
                                        pass
                            if compute_file_hash:
                                sha = str(prev.get("file_sha256") or "").strip().lower()
                                if sha:
                                    sha_counts[sha] = sha_counts.get(sha, 0) + 1

                            jf.write(json.dumps(prev, ensure_ascii=False, separators=(",", ":")))
                            jf.write("\n")
                            flush_progress(idx)
                            continue

                # Text metrics (best-effort).
                sample_text = ""
                estimated_text = False
                if enable_text_extract:
                    if ext in TEXTLIKE_EXTS:
                        sample_text, estimated_text = _read_text_sample(path, max_bytes=text_max_bytes)
                        # Estimate text length using bytes ratio (rough).
                        if sample_text:
                            sample_tokens = int(estimate_tokens(sample_text) or 0)
                            if estimated_text and size > 0:
                                ratio = size / max(1, min(size, text_max_bytes))
                                rec.text_characters = int(len(sample_text) * ratio)
                                rec.text_tokens_est = int(sample_tokens * ratio)
                                rec.estimated_text = True
                            else:
                                rec.text_characters = int(len(sample_text))
                                rec.text_tokens_est = int(sample_tokens)
                                rec.estimated_text = False
                    elif ext == ".pdf":
                        sample_text, estimated_text, page_count, per_page_chars, pdf_err = _pdf_text_sample(
                            path, sample_pages=pdf_sample_pages
                        )
                        if pdf_err:
                            rec.error_message = str(pdf_err)[:200]
                            if "parse_failed" not in rec.findings:
                                rec.findings.append("parse_failed")
                                finding_counts["parse_failed"] += 1
                                errors += 1
                        if sample_text:
                            sample_tokens = int(estimate_tokens(sample_text) or 0)
                            if estimated_text and page_count > 0:
                                # Scale by pages (rough).
                                ratio = page_count / max(1, min(page_count, pdf_sample_pages))
                                rec.text_characters = int(len(sample_text) * ratio)
                                rec.text_tokens_est = int(sample_tokens * ratio)
                                rec.estimated_text = True
                            else:
                                rec.text_characters = int(len(sample_text))
                                rec.text_tokens_est = int(sample_tokens)
                                rec.estimated_text = False
                        # Always attach PDF page breakdown when possible (even if text is empty).
                        if page_count > 0 and per_page_chars:
                            rec.pdf_pages = _build_pdf_page_breakdown(
                                page_count=int(page_count),
                                per_page_chars=per_page_chars,
                                scan_max_chars=int(pdf_scan_max_chars),
                                text_min_chars=int(pdf_text_min_chars),
                            )

                # Optional near-duplicate fingerprint (SimHash over extracted text sample).
                if enable_near_dup and sample_text:
                    try:
                        sim = _simhash64(sample_text)
                    except Exception:
                        sim = 0
                    if sim:
                        rec.text_simhash64 = f"{int(sim) & ((1<<64)-1):016x}"
                        simhash_entries.append((rec.name, int(sim)))

                # PDF scan detection (transparent heuristics on sampled pages).
                if enable_pdf_quality and ext == ".pdf":
                    if "parse_failed" in rec.findings:
                        # If we couldn't even sample pages/text, do not report misleading "pdf_unknown" heuristics.
                        rec.pdf_scanned = None
                    else:
                        breakdown = rec.pdf_pages if isinstance(rec.pdf_pages, dict) else None
                        scan_ratio = float(breakdown.get("scan_ratio") or 0.0) if breakdown else 0.0
                        page_count = int(breakdown.get("page_count") or 0) if breakdown else 0

                        if page_count <= 0:
                            rec.pdf_scanned = None
                            rec.findings.append("pdf_unknown")
                            finding_counts["pdf_unknown"] += 1
                            pdf_unknown += 1
                        else:
                            scanned = bool(scan_ratio >= float(pdf_scan_ratio_threshold))
                            rec.pdf_scanned = scanned
                            if scanned:
                                rec.findings.append("pdf_scanned")
                                finding_counts["pdf_scanned"] += 1
                                pdf_scanned += 1
                            else:
                                pdf_not_scanned += 1

                # Spreadsheet stats (best-effort): large tables are often better served by structured indexing / Text-to-SQL.
                if ext in {".csv", ".xlsx"}:
                    if ext == ".csv":
                        # Use the already-read text sample as a cheap proxy for row count.
                        if sample_text:
                            lines = int(sample_text.count("\n"))
                            if not sample_text.endswith("\n"):
                                lines += 1
                            row_count = max(0, lines)
                            estimated_rows = False
                            if estimated_text and size > 0:
                                ratio = size / max(1, min(size, text_max_bytes))
                                row_count = int(row_count * ratio)
                                estimated_rows = True
                            col_count = 0
                            try:
                                sniff_sample = sample_text[:8192]
                                dialect: csv.Dialect = csv.excel
                                try:
                                    dialect = csv.Sniffer().sniff(sniff_sample, delimiters=[",", "\t", ";", "|"])
                                except Exception:
                                    dialect = csv.excel
                                reader = csv.reader(io.StringIO(sample_text), dialect)
                                for row in reader:
                                    if row and any(str(c).strip() for c in row):
                                        col_count = int(len(row))
                                        break
                            except Exception:
                                col_count = 0
                            rec.spreadsheet = {
                                "row_count": int(row_count),
                                "col_count": int(col_count),
                                "sheet_count": 1,
                                "merged_cell_ratio": 0.0,
                                "estimated_rows": bool(estimated_rows),
                                "estimated_cols": False,
                            }
                    else:
                        stats, xlsx_err = _xlsx_spreadsheet_stats(path)
                        if isinstance(stats, dict) and stats:
                            rec.spreadsheet = stats
                        elif xlsx_err:
                            rec.error_message = str(xlsx_err)[:200]
                            if "parse_failed" not in rec.findings:
                                rec.findings.append("parse_failed")
                                finding_counts["parse_failed"] += 1
                                errors += 1

                    if isinstance(rec.spreadsheet, dict):
                        rows = int(rec.spreadsheet.get("row_count") or 0)
                        if spreadsheet_large_row_threshold > 0 and rows >= int(spreadsheet_large_row_threshold):
                            rec.findings.append("large_spreadsheet")
                            finding_counts["large_spreadsheet"] += 1
                        cols = int(rec.spreadsheet.get("col_count") or 0)
                        if spreadsheet_wide_col_threshold > 0 and cols >= int(spreadsheet_wide_col_threshold):
                            rec.findings.append("wide_spreadsheet")
                            finding_counts["wide_spreadsheet"] += 1
                        sheets = int(rec.spreadsheet.get("sheet_count") or 0)
                        if spreadsheet_sheet_threshold > 0 and sheets >= int(spreadsheet_sheet_threshold):
                            rec.findings.append("many_sheets_spreadsheet")
                            finding_counts["many_sheets_spreadsheet"] += 1
                        try:
                            merged_ratio = float(rec.spreadsheet.get("merged_cell_ratio") or 0.0)
                        except Exception:
                            merged_ratio = 0.0
                        if spreadsheet_merged_ratio_threshold > 0.0 and merged_ratio >= float(spreadsheet_merged_ratio_threshold):
                            rec.findings.append("merged_heavy_spreadsheet")
                            finding_counts["merged_heavy_spreadsheet"] += 1

                # Optional PII/secrets detection on sample text.
                if sample_text and enable_pii:
                    pii = anonymize_pii(sample_text, enabled=True, mode="mask")
                    if pii.hits:
                        rec.pii_hits = {str(k): int(v) for k, v in pii.hits.items() if int(v) > 0}
                        if rec.pii_hits:
                            rec.findings.append("pii")
                            finding_counts["pii"] += 1
                            for k, v in rec.pii_hits.items():
                                pii_totals[k] = pii_totals.get(k, 0) + int(v)

                    if enable_pii_samples and pii_max_samples_per_file > 0:
                        matches = find_pii_matches(sample_text, max_matches=pii_max_samples_per_file)
                        for m in matches:
                            start = int(getattr(m, "start", 0) or 0)
                            end = int(getattr(m, "end", 0) or 0)
                            if end <= start:
                                continue
                            ctx_start = max(0, start - int(pii_context_chars))
                            ctx_end = min(len(sample_text), end + int(pii_context_chars))
                            ctx = sample_text[ctx_start:ctx_end]
                            # Mask other occurrences within context for safer display.
                            ctx = anonymize_pii(ctx, enabled=True, mode="mask").text
                            ctx = redact_secrets(ctx, enabled=True, mode="mask").text
                            if len(ctx) > 2000:
                                ctx = ctx[:2000] + "..."
                            rec.pii_samples.append(
                                {
                                    "kind": str(getattr(m, "kind", "") or "pii"),
                                    "masked": _mask_pii_value(str(getattr(m, "kind", "") or ""), str(getattr(m, "text", "") or "")),
                                    "context": ctx,
                                    "start": start,
                                    "end": end,
                                }
                            )

                if sample_text and enable_secrets:
                    sec = redact_secrets(sample_text, enabled=True, mode="mask")
                    if sec.hits:
                        rec.secrets_hits = {str(k): int(v) for k, v in sec.hits.items() if int(v) > 0}
                        if rec.secrets_hits:
                            rec.findings.append("secrets")
                            finding_counts["secrets"] += 1
                            for k, v in rec.secrets_hits.items():
                                secrets_totals[k] = secrets_totals.get(k, 0) + int(v)

                    if enable_secrets_samples and secrets_max_samples_per_file > 0:
                        matches = find_secret_matches(sample_text, max_matches=secrets_max_samples_per_file)
                        for m in matches:
                            start = int(getattr(m, "start", 0) or 0)
                            end = int(getattr(m, "end", 0) or 0)
                            if end <= start:
                                continue
                            ctx_start = max(0, start - int(secrets_context_chars))
                            ctx_end = min(len(sample_text), end + int(secrets_context_chars))
                            ctx = sample_text[ctx_start:ctx_end]
                            # Mask PII/secrets in context for safer display.
                            ctx = anonymize_pii(ctx, enabled=True, mode="mask").text
                            ctx = redact_secrets(ctx, enabled=True, mode="mask").text
                            if len(ctx) > 2000:
                                ctx = ctx[:2000] + "..."
                            rec.secrets_samples.append(
                                {
                                    "kind": str(getattr(m, "kind", "") or "secret"),
                                    "masked": _mask_secret_value(str(getattr(m, "kind", "") or ""), str(getattr(m, "text", "") or "")),
                                    "context": ctx,
                                    "start": start,
                                    "end": end,
                                }
                            )

                # Optional file hash (expensive; for exact duplicates).
                if compute_file_hash:
                    sha = _safe_hash_file(path, algo="sha256")
                    rec.file_sha256 = sha
                    sha_counts[sha] = sha_counts.get(sha, 0) + 1

            except Exception as exc:  # noqa: BLE001
                errors += 1
                rec.error_message = str(exc)[:200]
                rec.findings.append("parse_failed")
                finding_counts["parse_failed"] += 1

            # Aggregation (best-effort).
            by_type[rec.file_type] = by_type.get(rec.file_type, 0) + 1
            file_sizes.append(int(rec.file_size or 0))
            if int(rec.text_characters or 0) > 0:
                text_lengths.append(int(rec.text_characters))

            # Write JSONL line.
            jf.write(json.dumps(asdict(rec), ensure_ascii=False, separators=(",", ":")))
            jf.write("\n")

            flush_progress(idx)

    if cancelled:
        # Best-effort: keep partial artifacts + summary.
        run.status = "cancelled"

    # Add exact-dup counts.
    if compute_file_hash and sha_counts:
        dup_total = 0
        for _sha, cnt in sha_counts.items():
            if int(cnt) > 1:
                dup_total += int(cnt)
        if dup_total > 0:
            finding_counts["exact_dup"] = int(dup_total)

    near_dup_path: Path | None = None
    if enable_near_dup and simhash_entries and near_dup_hamming_threshold > 0 and near_dup_max_pairs > 0:
        names = [n for n, _h in simhash_entries]
        hashes = [int(_h) for _n, _h in simhash_entries]
        n_total = len(hashes)

        # LSH banding to avoid O(N^2) comparisons (4x16-bit bands).
        buckets: dict[tuple[int, int], list[int]] = {}
        pairs: list[dict[str, Any]] = []
        parent = list(range(n_total))
        rank = [0] * n_total

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra = find(a)
            rb = find(b)
            if ra == rb:
                return
            if rank[ra] < rank[rb]:
                parent[ra] = rb
            elif rank[ra] > rank[rb]:
                parent[rb] = ra
            else:
                parent[rb] = ra
                rank[ra] += 1

        # Compare candidates as we insert each item.
        for i, h in enumerate(hashes):
            candidates: set[int] = set()
            for band in range(4):
                key = (band, int((h >> (band * 16)) & 0xFFFF))
                existing = buckets.get(key)
                if existing and len(existing) <= 2000:
                    candidates.update(existing)
                buckets.setdefault(key, []).append(i)

            for j in candidates:
                if j == i:
                    continue
                d = _hamming_distance64(h, hashes[j])
                if d <= int(near_dup_hamming_threshold):
                    pairs.append({"a": names[j], "b": names[i], "distance": int(d)})
                    union(i, j)
                    if len(pairs) >= int(near_dup_max_pairs):
                        break
            if len(pairs) >= int(near_dup_max_pairs):
                break

        # Build clusters from union-find (size>=2).
        groups: dict[int, list[int]] = {}
        for idx in range(n_total):
            r = find(idx)
            groups.setdefault(r, []).append(idx)

        clusters: list[dict[str, Any]] = []
        for root_id, members in groups.items():
            if len(members) < 2:
                continue
            clusters.append({"id": str(root_id), "members": [names[i] for i in sorted(members)]})

        clusters.sort(key=lambda c: (-len(c.get("members") or []), str(c.get("id") or "")))
        affected = {m for c in clusters for m in (c.get("members") or [])}
        if affected:
            finding_counts["near_dup"] = int(len(affected))

        near_dup_payload = {
            "threshold": int(near_dup_hamming_threshold),
            "max_pairs": int(near_dup_max_pairs),
            "pairs_returned": int(len(pairs)),
            "clusters_returned": int(len(clusters)),
            "clusters": clusters[:2000],
            "pairs": pairs[:5000],
        }
        near_dup_path = (artifact_root / "near_dups.json").resolve(strict=False)
        near_dup_path.write_text(json.dumps(near_dup_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Representative sampling artifact (shareable when redact_paths=true).
    samples_written = False
    if enable_sampling and sample_size > 0:
        try:
            payload = _build_samples_payload(jsonl_path=jsonl_path, target_size=sample_size)
            samples_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            samples_written = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to write samples.json: %s", str(exc)[:200])

    # Histograms + percentiles.
    file_sizes.sort()
    text_lengths.sort()
    percentiles = {
        "p25": percentile_from_sorted(text_lengths, 25),
        "p50": percentile_from_sorted(text_lengths, 50),
        "p75": percentile_from_sorted(text_lengths, 75),
        "p90": percentile_from_sorted(text_lengths, 90),
        "p99": percentile_from_sorted(text_lengths, 99),
    }

    summary = {
        "dataset_id": str(dataset_id),
        "scan_run_id": str(run.id),
        "generated_at": _now_utc().isoformat(),
        # Use processed count (supports cancelled runs with partial artifacts).
        "total_files": int(len(file_sizes)),
        "total_size_bytes": int(sum(file_sizes)),
        "reused_files": int(reused_files),
        "by_file_type": {k: int(v) for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))},
        "file_size_histogram": histogram(file_sizes, FILE_SIZE_BINS),
        "length_percentiles": percentiles,
        "length_histogram": histogram(text_lengths, TEXT_LENGTH_BINS),
        "pdf_scan": {"scanned": int(pdf_scanned), "not_scanned": int(pdf_not_scanned), "unknown": int(pdf_unknown)},
        "pdf_detection": {
            "sample_pages": int(pdf_sample_pages),
            "scan_max_chars_per_page": int(pdf_scan_max_chars),
            "text_min_chars_per_page": int(pdf_text_min_chars),
            "scan_ratio_threshold": float(pdf_scan_ratio_threshold),
        },
        "pii_hits_total": {k: int(v) for k, v in pii_totals.items()},
        "secrets_hits_total": {k: int(v) for k, v in secrets_totals.items()},
        "findings": [
            {
                "key": k,
                "label": v.get("label", k),
                "severity": v.get("severity", "info"),
                "count": int(finding_counts.get(k, 0) or 0),
                "description": v.get("description"),
            }
            for k, v in FINDING_KEY_REASONS.items()
        ],
    }

    if not cancelled:
        run.status = "completed"
        run.progress = 100
    run.finished_at = _now_utc()
    run.summary = summary
    run.artifacts = {
        "files_jsonl": str(jsonl_path),
        "root_path": "[REDACTED]" if redact_paths else str(root),
    }
    if near_dup_path is not None:
        run.artifacts["near_dups_json"] = str(near_dup_path)
    if samples_written:
        run.artifacts["samples_json"] = str(samples_path)
    db.commit()

    return {
        "ok": True,
        "files": int(total),
        "errors": int(errors),
        "reused": int(reused_files),
    }

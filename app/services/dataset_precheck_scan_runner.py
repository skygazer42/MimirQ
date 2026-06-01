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
import logging
import os
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.optional_deps import optional_import
from app.core.token_utils import estimate_tokens
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.rag.core.logging import get_logger
from app.rag.preprocessing.language import detect_language
from app.rag.preprocessing.pii_anonymizer import anonymize_pii, find_pii_matches
from app.rag.preprocessing.secrets import find_secret_matches, redact_secrets
from app.rag.tools.pre_poc_scanner.settings import resolve_pre_poc_scanner_thresholds
from app.services.dataset_precheck_classification import (
    classify_parse_failure_kind,
    infer_primary_tag,
    infer_processing_paths,
)
from app.services.dataset_precheck_near_dup_summary import summarize_near_dup_payload
from app.services.dataset_precheck_risk_buckets import risk_buckets_for_file
from app.services.dataset_profile_utils import (
    FILE_SIZE_BINS,
    TEXT_LENGTH_BINS,
    TEXT_TOKEN_BINS,
    histogram,
    percentile_from_sorted,
    safe_int,
)

logger = get_logger("services.dataset_precheck_scan")
_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE = "Ignoring non-critical precheck runner fallback failure: %s"

UPLOAD_DIR_FALLBACK = "./uploads"
REDACTED_MASK = "[REDACTED]"
SECRET_MASK = "[SECRET]"
PRECHECK_SAMPLE_RATIO_NUMERATOR = 3
PRECHECK_SAMPLE_RATIO_DENOMINATOR = 1000
PRECHECK_SAMPLE_MAX_SIZE = 2000


FINDING_KEY_REASONS: dict[str, dict[str, Any]] = {
    "parse_failed": {
        "label": "解析/读取失败",
        "severity": "error",
        "description": "文件无法读取或解析（权限/损坏/依赖缺失）。",
    },
    "legacy_format": {
        "label": "老格式/兼容格式解析失败",
        "severity": "warning",
        "description": "更像旧格式或兼容格式问题，建议尝试回退解析链路。",
    },
    "password_protected": {
        "label": "受保护/加密文件",
        "severity": "warning",
        "description": "文件可能受密码保护或访问受限，建议人工解锁后再处理。",
    },
    "corrupted_or_unreadable": {
        "label": "文件损坏或不可读",
        "severity": "error",
        "description": "文件本身可能损坏、压缩包异常或不可读，建议人工复核原件。",
    },
    "other_parse_failure": {
        "label": "其他解析失败",
        "severity": "warning",
        "description": "发生解析失败，但当前只能归为其他异常类型，建议复核与回退。",
    },
    "empty_text": {
        "label": "空文本/未提取到文本（抽样）",
        "severity": "warning",
        "description": "抽样未提取到有效文本（可能是二进制/编码异常/内容在文件后部/扫描件）。建议复核解析/OCR 路由。",
    },
    "short_text": {
        "label": "文本过短（抽样）",
        "severity": "info",
        "description": "文本长度过短可能导致检索信号不足（也可能是正常短文档）。建议结合业务判断。",
    },
    "low_density_text": {
        "label": "低密度/疑似乱码（抽样）",
        "severity": "warning",
        "description": "字符密度偏低（有效字符占比过低），可能是乱码/噪声/解析失败的弱信号。",
    },
    "gibberish_text": {
        "label": "疑似乱码（替换字符/密度极低）",
        "severity": "warning",
        "description": "替换字符比例高或密度极低，通常意味着解码/解析质量问题。建议检查编码/OCR/解析器后备策略。",
    },
    "pdf_scanned": {
        "label": "疑似扫描 PDF",
        "severity": "warning",
        "description": "可能需要 OCR/更强 PDF 解析链路。",
    },
    "pdf_mixed": {
        "label": "PDF 混合页（扫描+文本）",
        "severity": "info",
        "description": "同一 PDF 同时包含扫描页与文本页，路由策略可能需要更精细（按页类型处理）。",
    },
    "pdf_low_density": {
        "label": "PDF 低密度页较多",
        "severity": "warning",
        "description": "抽样页中低密度页占比较高，可能需要更强解析/OCR，或先做治理清洗。",
    },
    "pdf_encrypted": {
        "label": "PDF 可能加密/受限",
        "severity": "error",
        "description": "PDF 可能被加密/受限导致无法提取文本。建议提供解密版或调整解析权限。",
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
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    return "unknown"


def _stable_sample_key(item: dict[str, Any], *, salt: str) -> str:
    raw = "|".join(
        [
            str(salt or ""),
            str(item.get("name") or ""),
            str(item.get("file_type") or ""),
            str(item.get("file_size") or ""),
            str(item.get("file_mtime") or ""),
        ]
    )
    return hashlib.blake2b(raw.encode("utf-8", errors="ignore"), digest_size=8).hexdigest()


def _resolve_precheck_sample_target(
    *,
    total_files: int,
    file_type_counts: dict[str, int] | Counter[str],
    requested_size: int | None = None,
) -> int:
    """
    Resolve representative precheck sample size.

    Default policy is intentionally small for POC/pricing: 3/1000 files,
    with one sample for every file type that actually appears in the batch.
    """
    total_n = max(0, int(total_files or 0))
    if total_n <= 0:
        return 0

    present_type_count = len(
        [
            str(key or "").strip().lower()
            for key, count in dict(file_type_counts or {}).items()
            if str(key or "").strip() and int(count or 0) > 0
        ]
    )

    if requested_size is not None:
        base = max(0, min(int(requested_size or 0), PRECHECK_SAMPLE_MAX_SIZE))
        if base <= 0:
            return 0
    else:
        base = int(
            (total_n * PRECHECK_SAMPLE_RATIO_NUMERATOR + PRECHECK_SAMPLE_RATIO_DENOMINATOR - 1)
            // PRECHECK_SAMPLE_RATIO_DENOMINATOR
        )

    target = max(1, present_type_count, base)
    return min(total_n, min(PRECHECK_SAMPLE_MAX_SIZE, target))


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
    type_groups: dict[str, list[dict[str, Any]]] = {}
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
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
            type_groups.setdefault(file_type.lower(), []).append(obj)

            findings = obj.get("findings")
            if isinstance(findings, list):
                for fk in findings:
                    fkey = str(fk or "").strip().lower()
                    if not fkey:
                        continue
                    findings_buckets.setdefault(fkey, []).append(obj)

            _push_top(largest, obj, key="file_size", top_k=20)
            _push_top(longest, obj, key="text_characters", top_k=20)

    # Representative picks: random-like deterministic coverage by present file type first,
    # then fill the ratio target from the remaining pool. Deterministic ordering keeps
    # exports and tests reproducible while avoiding "first N files" bias.
    rep: list[dict[str, Any]] = []
    picked_names: set[str] = set()
    if len(type_groups) > target_size:
        target_size = min(PRECHECK_SAMPLE_MAX_SIZE, len(type_groups))
    type_minimum = min(
        int(len(type_groups)),
        int(max(0, min(target_size, PRECHECK_SAMPLE_MAX_SIZE))),
    )

    for file_type, items in sorted(type_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:type_minimum]:
        keyed_items = [
            (_stable_sample_key(item, salt=f"type:{file_type}"), str(item.get("name") or ""), item)
            for item in items
        ]
        items_sorted = [item for _, _, item in sorted(keyed_items, key=lambda entry: (entry[0], entry[1]))]
        if not items_sorted:
            continue
        item = items_sorted[0]
        nm = str(item.get("name") or "")
        if nm and nm not in picked_names:
            picked_names.add(nm)
            rep.append(item)
        if len(rep) >= target_size:
            break

    if len(rep) < target_size:
        remaining = [
            item
            for items in type_groups.values()
            for item in items
            if str(item.get("name") or "") not in picked_names
        ]
        remaining.sort(key=lambda o: (_stable_sample_key(o, salt="ratio-fill"), str(o.get("name") or "")))
        for item in remaining:
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
    return datetime.now(UTC)


def _parse_csv(raw: str) -> list[str]:
    parts = [p.strip() for p in str(raw or "").split(",")]
    return [p for p in parts if p]


def _is_local_scan_allowed_for_root(*, cfg: dict[str, Any], root: Path) -> bool:
    """
    Return True if local scanning is allowed for this run.

    Normal mode requires LOCAL_SCAN_ENABLED=true.

    Internal mode (used by "precheck-first ingest") can allow scans of server-managed staging
    folders under UPLOAD_DIR even when LOCAL_SCAN_ENABLED=false.
    """
    if bool(getattr(settings, "LOCAL_SCAN_ENABLED", False)):
        return True

    # Internal allowlist: must be explicitly set by server code (not exposed in API schema)
    # and must target a root under UPLOAD_DIR.
    if not bool(cfg.get("internal_allow_upload_scan", False)):
        return False

    upload_root = Path(getattr(settings, "UPLOAD_DIR", UPLOAD_DIR_FALLBACK) or UPLOAD_DIR_FALLBACK).resolve(strict=False)
    resolved = root.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(upload_root)
        return True
    except Exception:
        return False


def _assert_scan_root_allowed(root: Path) -> None:
    """
    Ensure root is within UPLOAD_DIR or one of LOCAL_SCAN_ROOTS.

    This is a safety guard against arbitrary file reads in shared deployments.
    """
    upload_root = Path(getattr(settings, "UPLOAD_DIR", UPLOAD_DIR_FALLBACK) or UPLOAD_DIR_FALLBACK).resolve(strict=False)
    allowed: list[Path] = [upload_root]
    for p in _parse_csv(str(getattr(settings, "LOCAL_SCAN_ROOTS", "") or "")):
        try:
            allowed.append(Path(p).expanduser().resolve(strict=False))
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue

    resolved = root.expanduser().resolve(strict=False)
    for base in allowed:
        try:
            resolved.relative_to(base)
            return
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
                            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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
        except Exception as exc:
            logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)


def _mask_pii_value(kind: str, raw: str) -> str:
    k = (kind or "").strip().lower()
    s = (raw or "").strip()
    if not s:
        return REDACTED_MASK
    if k == "email":
        if "@" not in s:
            return REDACTED_MASK
        local, domain = s.split("@", 1)
        head = (local[:1] + "***") if local else "***"
        return f"{head}@{domain}"
    if k == "ip":
        parts = s.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3] + ["***"])
        return REDACTED_MASK
    if k in {"phone"}:
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) >= 7:
            return f"{digits[:3]}****{digits[-2:]}"
        return REDACTED_MASK
    if k == "credit_card":
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) >= 8:
            return f"{digits[:4]}****{digits[-4:]}"
        return REDACTED_MASK
    if k == "cn_id":
        if len(s) >= 10:
            return f"{s[:6]}********{s[-2:]}"
        return REDACTED_MASK
    if k == "ssn":
        return "***-**-****"
    return REDACTED_MASK


def _mask_secret_value(kind: str, raw: str) -> str:
    k = (kind or "").strip().lower()
    s = (raw or "").strip()
    if not s:
        return SECRET_MASK
    if k == "openai_key":
        return "sk-***"
    if k == "github_token":
        if s.startswith("ghp_"):
            return "ghp_***"
        if s.startswith("github_pat_"):
            return "github_pat_***"
        return SECRET_MASK
    if k == "aws_access_key":
        return (s[:4] + "***") if len(s) >= 4 else SECRET_MASK
    if k == "slack_token":
        # xox[baprs]-...
        prefix = s.split("-", 1)[0]
        return f"{prefix}-***" if prefix else SECRET_MASK
    if k == "bearer_token":
        return "Bearer ***"
    if k == "private_key":
        return "[PRIVATE_KEY_REDACTED]"
    return SECRET_MASK


@dataclass
class _FileRecord:
    name: str
    file_type: str
    file_size: int
    file_mtime: int = 0
    text_characters: int = 0
    text_tokens_est: int = 0
    language: str | None = None
    language_confidence: float | None = None
    estimated_text: bool = False
    pdf_scanned: bool | None = None
    pdf_pages: dict[str, Any] | None = None
    spreadsheet: dict[str, Any] | None = None
    text_simhash64: str | None = None
    pii_hits: dict[str, int] = field(default_factory=dict)
    secrets_hits: dict[str, int] = field(default_factory=dict)
    pii_samples: list[dict[str, Any]] = field(default_factory=list)
    secrets_samples: list[dict[str, Any]] = field(default_factory=list)
    file_sha256: str | None = None
    parse_failure_kind: str | None = None
    primary_tag: str | None = None
    processing_paths: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    error_message: str | None = None


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
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            # Ensure the resolved path stays within the scan root to prevent symlink escape.
            try:
                path.resolve(strict=False).relative_to(root_resolved)
            except Exception:
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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

    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError("root_path_not_found")
    if not _is_local_scan_allowed_for_root(cfg=cfg, root=root):
        raise ValueError("local_scan_disabled")
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
    raw_sample_size = cfg.get("sample_size")

    threshold_overrides = cfg.get("threshold_overrides") if isinstance(cfg.get("threshold_overrides"), dict) else {}
    thresholds = resolve_pre_poc_scanner_thresholds(
        {
            **threshold_overrides,
            "pdf_scan_ratio_threshold": cfg.get("pdf_scan_ratio_threshold"),
            "near_dup_hamming_threshold": cfg.get("near_dup_hamming_threshold"),
            "near_dup_max_pairs": cfg.get("near_dup_max_pairs"),
            "sample_size": cfg.get("sample_size"),
        }
    )
    configured_default_sample_size = safe_int(getattr(settings, "PRECHECK_SAMPLE_SIZE", 0), default=0)
    sample_size_override = (
        int(thresholds["sample_size"])
        if raw_sample_size is not None or configured_default_sample_size > 0
        else None
    )

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
    pdf_scan_ratio_threshold = float(thresholds["pdf_scan_ratio_threshold"])
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

    # Best-effort text quality / language heuristics (for precheck only).
    language_min_chars = safe_int(getattr(settings, "PRECHECK_LANGUAGE_MIN_CHARS", 40), default=40)
    text_short_chars_threshold = int(thresholds["text_short_chars_threshold"])
    text_density_threshold = float(thresholds["text_density_threshold"])
    text_gibberish_density_threshold = float(thresholds["text_gibberish_density_threshold"])
    text_high_replacement_ratio_threshold = float(thresholds["text_high_replacement_ratio_threshold"])
    pdf_low_density_ratio_threshold = float(thresholds["pdf_low_density_ratio_threshold"])

    directory_stats_limit = safe_int(getattr(settings, "PRECHECK_DIRECTORY_STATS_LIMIT", 200), default=200)
    directory_stats_limit = max(0, min(int(directory_stats_limit or 0), 2000))

    # Prepare artifact dir and JSONL writer.
    artifact_root = Path(getattr(settings, "UPLOAD_DIR", UPLOAD_DIR_FALLBACK) or UPLOAD_DIR_FALLBACK) / str(tenant_id) / "precheck" / str(run.id)
    artifact_root.mkdir(parents=True, exist_ok=True)
    jsonl_path = (artifact_root / "files.jsonl").resolve(strict=False)
    samples_path = (artifact_root / "samples.json").resolve(strict=False)

    # Enumerate file candidates first to compute total for progress (bounded by max_files).
    allowed_exts = set(getattr(settings, "allowed_extensions_list", []) or [])
    candidates: list[Path] = []
    candidate_type_counts: Counter[str] = Counter()
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
        file_type = ext.lstrip(".") if ext.startswith(".") else (p.suffix or "").lower().lstrip(".") or "unknown"
        candidate_type_counts[str(file_type or "unknown").lower()] += 1
        total_bytes_seen += size

    total = len(candidates)
    sample_size = _resolve_precheck_sample_target(
        total_files=total,
        file_type_counts=candidate_type_counts,
        requested_size=sample_size_override,
    )
    if total == 0:
        run.status = "completed"
        run.progress = 100
        run.finished_at = _now_utc()
        run.summary = {
            "dataset_id": str(dataset_id),
            "scan_run_id": str(run.id),
            "generated_at": run.finished_at.isoformat(),
            "schema_id": "mimirq.dataset_precheck_summary.v3",
            "schema_version": 3,
            "total_files": 0,
            "total_size_bytes": 0,
            "reused_files": 0,
            "by_file_type": {},
            "by_file_type_bytes": {},
            "file_type_stats": [],
            "language_mix": {},
            "directory_stats": [],
            "file_size_histogram": [],
            "length_percentiles": {"p25": 0, "p50": 0, "p75": 0, "p90": 0, "p99": 0},
            "length_histogram": [],
            "token_percentiles": {"p25": 0, "p50": 0, "p75": 0, "p90": 0, "p99": 0},
            "token_histogram": [],
            "pdf_scan": {"scanned": 0, "not_scanned": 0, "unknown": 0},
            "pdf_detection": {
                "sample_pages": int(pdf_sample_pages),
                "scan_max_chars_per_page": int(pdf_scan_max_chars),
                "text_min_chars_per_page": int(pdf_text_min_chars),
                "scan_ratio_threshold": float(pdf_scan_ratio_threshold),
            },
            "risk_buckets": {},
            "near_dup_summary": summarize_near_dup_payload(None),
            "pii_hits_total": {},
            "secrets_hits_total": {},
            "findings": [
                {"key": k, "label": v.get("label", k), "severity": v.get("severity", "info"), "count": 0, "description": v.get("description")}
                for k, v in FINDING_KEY_REASONS.items()
            ],
        }
        run.artifacts = {"files_jsonl": str(jsonl_path), "root_path": REDACTED_MASK if redact_paths else str(root)}
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
        except Exception as exc:
            # Best-effort: ignore refresh failures.
            logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)

    # Aggregation accumulators.
    by_type: dict[str, int] = {}
    bytes_by_type: dict[str, int] = {}
    file_sizes: list[int] = []
    text_lengths: list[int] = []
    token_lengths: list[int] = []
    language_counts: Counter[str] = Counter()
    directory_stats: dict[str, dict[str, Any]] = {}
    pii_totals: dict[str, int] = {}
    secrets_totals: dict[str, int] = {}
    pdf_scanned = 0
    pdf_not_scanned = 0
    pdf_unknown = 0
    finding_counts: dict[str, int] = dict.fromkeys(FINDING_KEY_REASONS.keys(), 0)
    risk_bucket_counts: dict[str, int] = {}
    primary_tag_counts: Counter[str] = Counter()
    processing_path_counts: Counter[str] = Counter()

    # For exact-dup finding: sha256 -> count.
    sha_counts: dict[str, int] = {}

    # For near-dup finding: (name, simhash64, file_size, text_characters, file_mtime).
    simhash_entries: list[tuple[str, int, int, int, int]] = []

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
                            upload_root = Path(getattr(settings, "UPLOAD_DIR", UPLOAD_DIR_FALLBACK) or UPLOAD_DIR_FALLBACK).resolve(strict=False)
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
                                        logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
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

    risk_keys: set[str] = {
        str(k).strip().lower()
        for k, v in FINDING_KEY_REASONS.items()
        if str((v or {}).get("severity") or "").strip().lower() in {"warning", "error"}
    }

    def _normalize_language_bucket(value: object) -> str:
        s = str(value or "").strip().lower()
        if s in {"zh", "en", "mixed", "unknown"}:
            return s
        return "unknown"

    def _dir_key(name: str) -> str:
        s = str(name or "").replace("\\", "/").strip()
        d = os.path.dirname(s)
        return d if d else "."

    def _update_directory_stats(*, name: str, file_size: int, findings: list[str]) -> None:
        d = _dir_key(name)
        entry = directory_stats.get(d)
        if entry is None:
            entry = {"path": d, "total_files": 0, "total_size_bytes": 0, "risky_files": 0, "findings": {}}
            directory_stats[d] = entry
        entry["total_files"] = int(entry.get("total_files") or 0) + 1
        entry["total_size_bytes"] = int(entry.get("total_size_bytes") or 0) + int(file_size or 0)
        fset = {str(x or "").strip().lower() for x in (findings or []) if str(x or "").strip()}
        if fset and risk_keys and (fset & risk_keys):
            entry["risky_files"] = int(entry.get("risky_files") or 0) + 1
        counts = entry.get("findings")
        if not isinstance(counts, dict):
            counts = {}
            entry["findings"] = counts
        for fk in fset:
            counts[fk] = int(counts.get(fk, 0) or 0) + 1

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
                            ft = str(prev.get("file_type") or rec.file_type or "unknown").strip().lower() or "unknown"
                            by_type[ft] = by_type.get(ft, 0) + 1
                            bs = int(prev.get("file_size") or 0)
                            bytes_by_type[ft] = bytes_by_type.get(ft, 0) + int(bs)
                            file_sizes.append(int(bs))
                            tl = int(prev.get("text_characters") or 0)
                            if tl > 0:
                                text_lengths.append(tl)
                            tt = int(prev.get("text_tokens_est") or 0)
                            if tt > 0:
                                token_lengths.append(tt)

                            lang_bucket = _normalize_language_bucket(prev.get("language"))
                            language_counts[lang_bucket] += 1

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
                                prev_fset = {str(fk or "").strip().lower() for fk in prev_findings if str(fk or "").strip()}
                                for k in prev_fset:
                                    if k in finding_counts:
                                        finding_counts[k] += 1

                            # Risk buckets (v3).
                            try:
                                for b in risk_buckets_for_file(file_type=ft, findings=prev_findings):
                                    risk_bucket_counts[b] = int(risk_bucket_counts.get(b, 0) or 0) + 1
                            except Exception as exc:
                                logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)

                            _update_directory_stats(name=rec.name, file_size=int(bs), findings=list(prev_findings) if isinstance(prev_findings, list) else [])

                            # Totals for pii/secrets.
                            pii_hits = prev.get("pii_hits") if isinstance(prev.get("pii_hits"), dict) else {}
                            for k, v in pii_hits.items():
                                try:
                                    pii_totals[str(k)] = pii_totals.get(str(k), 0) + int(v or 0)
                                except Exception:
                                    logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                                    continue
                            secrets_hits = prev.get("secrets_hits") if isinstance(prev.get("secrets_hits"), dict) else {}
                            for k, v in secrets_hits.items():
                                try:
                                    secrets_totals[str(k)] = secrets_totals.get(str(k), 0) + int(v or 0)
                                except Exception:
                                    logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                                    continue

                            # Near-dup entries and exact-dup entries.
                            if enable_near_dup:
                                sim_hex = str(prev.get("text_simhash64") or "").strip().lower()
                                if sim_hex:
                                    try:
                                        simhash_entries.append((rec.name, int(sim_hex, 16), int(bs), int(tl), int(prev.get("file_mtime") or 0)))
                                    except Exception as exc:
                                        logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)
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
                            err_l = str(pdf_err or "").strip().lower()
                            if ("password" in err_l) or ("encrypt" in err_l) or ("encryption" in err_l):
                                if "pdf_encrypted" not in rec.findings:
                                    rec.findings.append("pdf_encrypted")
                                    finding_counts["pdf_encrypted"] += 1
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

                # Text quality / language heuristics (best-effort; based on sampled extracted text).
                if enable_text_extract:
                    if ext in TEXTLIKE_EXTS and not (sample_text or "").strip():
                        if "empty_text" not in rec.findings:
                            rec.findings.append("empty_text")
                            finding_counts["empty_text"] += 1

                    if int(rec.text_characters or 0) > 0 and int(text_short_chars_threshold or 0) > 0:
                        if int(rec.text_characters) < int(text_short_chars_threshold):
                            if "short_text" not in rec.findings:
                                rec.findings.append("short_text")
                                finding_counts["short_text"] += 1

                    if sample_text:
                        try:
                            lang = detect_language(sample_text, min_chars=int(language_min_chars or 0))
                            rec.language = _normalize_language_bucket(getattr(lang, "language", "unknown"))
                            rec.language_confidence = float(getattr(lang, "confidence", 0.0) or 0.0)
                        except Exception:
                            rec.language = "unknown"
                            rec.language_confidence = 0.0

                        try:
                            tq = score_parsed_text_quality(sample_text)
                        except Exception:
                            tq = None

                        if tq is not None:
                            if float(getattr(tq, "replacement_ratio", 0.0) or 0.0) >= float(text_high_replacement_ratio_threshold):
                                if "gibberish_text" not in rec.findings:
                                    rec.findings.append("gibberish_text")
                                    finding_counts["gibberish_text"] += 1
                            if (
                                int(getattr(tq, "chars_non_space", 0) or 0) >= 200
                                and float(getattr(tq, "density", 1.0) or 1.0) < float(text_density_threshold)
                                and "low_density_text" not in rec.findings
                            ):
                                rec.findings.append("low_density_text")
                                finding_counts["low_density_text"] += 1
                            if (
                                int(getattr(tq, "chars_non_space", 0) or 0) >= 1000
                                and float(getattr(tq, "density", 1.0) or 1.0) < float(text_gibberish_density_threshold)
                                and "gibberish_text" not in rec.findings
                            ):
                                rec.findings.append("gibberish_text")
                                finding_counts["gibberish_text"] += 1

                # Optional near-duplicate fingerprint (SimHash over extracted text sample).
                if enable_near_dup and sample_text:
                    try:
                        sim = _simhash64(sample_text)
                    except Exception:
                        sim = 0
                    if sim:
                        rec.text_simhash64 = f"{int(sim) & ((1<<64)-1):016x}"
                        simhash_entries.append((rec.name, int(sim), int(rec.file_size or 0), int(rec.text_characters or 0), int(rec.file_mtime or 0)))

                # PDF scan detection (transparent heuristics on sampled pages).
                if enable_pdf_quality and ext == ".pdf":
                    if "parse_failed" in rec.findings:
                        # If we couldn't even sample pages/text, do not report misleading "pdf_unknown" heuristics.
                        rec.pdf_scanned = None
                    else:
                        breakdown = rec.pdf_pages if isinstance(rec.pdf_pages, dict) else None
                        scan_ratio = float(breakdown.get("scan_ratio") or 0.0) if breakdown else 0.0
                        low_density_ratio = float(breakdown.get("low_density_ratio") or 0.0) if breakdown else 0.0
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

                            if breakdown:
                                scanned_pages = int(breakdown.get("scanned_pages") or 0)
                                text_pages = int(breakdown.get("text_pages") or 0)
                                if scanned_pages > 0 and text_pages > 0 and "pdf_mixed" not in rec.findings:
                                    rec.findings.append("pdf_mixed")
                                    finding_counts["pdf_mixed"] += 1
                                if float(low_density_ratio) >= float(pdf_low_density_ratio_threshold) and "pdf_low_density" not in rec.findings:
                                    rec.findings.append("pdf_low_density")
                                    finding_counts["pdf_low_density"] += 1

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
                                    dialect = csv.Sniffer().sniff(sniff_sample, delimiters=",\t;|")
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
                rec.parse_failure_kind = classify_parse_failure_kind(file_type=rec.file_type, error_message=rec.error_message)
                if rec.parse_failure_kind not in rec.findings:
                    rec.findings.append(rec.parse_failure_kind)
                    finding_counts[rec.parse_failure_kind] += 1

            # Aggregation (best-effort).
            ft = str(rec.file_type or "unknown").strip().lower() or "unknown"
            if rec.error_message and rec.parse_failure_kind is None and "parse_failed" in rec.findings:
                rec.parse_failure_kind = classify_parse_failure_kind(file_type=rec.file_type, error_message=rec.error_message)
                if rec.parse_failure_kind not in rec.findings:
                    rec.findings.append(rec.parse_failure_kind)
                    finding_counts[rec.parse_failure_kind] += 1

            rec.primary_tag = infer_primary_tag(file_type=ft, findings=rec.findings)
            rec.processing_paths = infer_processing_paths(primary_tag=rec.primary_tag, findings=rec.findings)
            primary_tag_counts[rec.primary_tag] += 1
            for path_key in rec.processing_paths:
                processing_path_counts[str(path_key or "")] += 1

            by_type[ft] = by_type.get(ft, 0) + 1
            bytes_by_type[ft] = bytes_by_type.get(ft, 0) + int(rec.file_size or 0)
            file_sizes.append(int(rec.file_size or 0))
            if int(rec.text_characters or 0) > 0:
                text_lengths.append(int(rec.text_characters))
            if int(rec.text_tokens_est or 0) > 0:
                token_lengths.append(int(rec.text_tokens_est))
            language_counts[_normalize_language_bucket(rec.language)] += 1
            _update_directory_stats(name=rec.name, file_size=int(rec.file_size or 0), findings=list(rec.findings or []))

            # Risk buckets (v3).
            try:
                for b in risk_buckets_for_file(file_type=ft, findings=rec.findings):
                    risk_bucket_counts[b] = int(risk_bucket_counts.get(b, 0) or 0) + 1
            except Exception as exc:
                logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)

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

    near_dup_payload: dict[str, Any] | None = None
    near_dup_path: Path | None = None
    if enable_near_dup and simhash_entries and near_dup_hamming_threshold > 0 and near_dup_max_pairs > 0:
        names = [n for n, _h, _sz, _tl, _mt in simhash_entries]
        hashes = [int(_h) for _n, _h, _sz, _tl, _mt in simhash_entries]
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

            # Conservative recommendation: pick a "keep" candidate (max text chars, then size, then mtime),
            # and ask humans to review the rest (no auto-drop).
            def _score(idx: int) -> tuple[int, int, int, str]:
                try:
                    _nm, _h, _sz, _tl, _mt = simhash_entries[idx]
                except Exception:
                    return (0, 0, 0, names[idx])
                return (int(_tl or 0), int(_sz or 0), int(_mt or 0), str(_nm or ""))

            ordered = sorted(members, key=_score, reverse=True)
            keep_idx = ordered[0]
            member_names = [names[i] for i in ordered]

            cluster: dict[str, Any] = {
                "id": str(root_id),
                "members": member_names,
                "keep_candidate": str(names[keep_idx]),
                "keep_strategy": "max_text_chars_then_size_then_mtime",
                "review_candidates": member_names[1: min(len(member_names), 21)],
            }
            # Keep artifacts reasonably small; include per-member stats when helpful.
            member_stats: list[dict[str, Any]] = []
            for i in ordered[: min(50, len(ordered))]:
                try:
                    nm, _h, sz, tl, mt = simhash_entries[i]
                    member_stats.append(
                        {
                            "name": str(nm),
                            "file_size": int(sz or 0),
                            "text_characters": int(tl or 0),
                            "file_mtime": int(mt or 0),
                        }
                    )
                except Exception:
                    logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                    continue
            if member_stats:
                cluster["member_stats"] = member_stats

            clusters.append(cluster)

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
    token_lengths.sort()
    percentiles = {
        "p25": percentile_from_sorted(text_lengths, 25),
        "p50": percentile_from_sorted(text_lengths, 50),
        "p75": percentile_from_sorted(text_lengths, 75),
        "p90": percentile_from_sorted(text_lengths, 90),
        "p99": percentile_from_sorted(text_lengths, 99),
    }
    token_percentiles = {
        "p25": percentile_from_sorted(token_lengths, 25),
        "p50": percentile_from_sorted(token_lengths, 50),
        "p75": percentile_from_sorted(token_lengths, 75),
        "p90": percentile_from_sorted(token_lengths, 90),
        "p99": percentile_from_sorted(token_lengths, 99),
    }

    file_type_stats: list[dict[str, Any]] = []
    for ft, cnt in by_type.items():
        file_type_stats.append(
            {
                "file_type": str(ft or "unknown"),
                "count": int(cnt or 0),
                "total_size_bytes": int(bytes_by_type.get(str(ft or "unknown"), 0) or 0),
            }
        )
    file_type_stats.sort(key=lambda o: (-int(o.get("count") or 0), -int(o.get("total_size_bytes") or 0), str(o.get("file_type") or "")))
    if len(file_type_stats) > 500:
        file_type_stats = file_type_stats[:500]

    lang_mix = {
        "zh": int(language_counts.get("zh", 0) or 0),
        "en": int(language_counts.get("en", 0) or 0),
        "mixed": int(language_counts.get("mixed", 0) or 0),
        "unknown": int(language_counts.get("unknown", 0) or 0),
    }

    dir_items: list[dict[str, Any]] = []
    for d, entry in directory_stats.items():
        if not isinstance(entry, dict):
            continue
        item = {
            "path": str(entry.get("path") or d or "."),
            "total_files": int(entry.get("total_files") or 0),
            "total_size_bytes": int(entry.get("total_size_bytes") or 0),
            "risky_files": int(entry.get("risky_files") or 0),
            "findings": entry.get("findings") if isinstance(entry.get("findings"), dict) else {},
        }
        # Keep report payload small and predictable.
        if len(item["path"]) > 512:
            item["path"] = item["path"][:512]
        dir_items.append(item)
    dir_items.sort(key=lambda o: (-int(o.get("risky_files") or 0), -int(o.get("total_files") or 0), str(o.get("path") or "")))
    if int(directory_stats_limit or 0) > 0:
        dir_items = dir_items[: int(directory_stats_limit)]
    else:
        dir_items = []

    near_dup_summary = summarize_near_dup_payload(near_dup_payload)

    summary = {
        "dataset_id": str(dataset_id),
        "scan_run_id": str(run.id),
        "generated_at": _now_utc().isoformat(),
        "schema_id": "mimirq.dataset_precheck_summary.v3",
        "schema_version": 3,
        # Use processed count (supports cancelled runs with partial artifacts).
        "total_files": int(len(file_sizes)),
        "total_size_bytes": int(sum(file_sizes)),
        "reused_files": int(reused_files),
        "by_file_type": {k: int(v) for k, v in sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))},
        "by_file_type_bytes": {
            k: int(v)
            for k, v in sorted(bytes_by_type.items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")))
            if int(v or 0) > 0
        },
        "file_type_stats": file_type_stats,
        "language_mix": lang_mix,
        "directory_stats": dir_items,
        "file_size_histogram": histogram(file_sizes, FILE_SIZE_BINS),
        "length_percentiles": percentiles,
        "length_histogram": histogram(text_lengths, TEXT_LENGTH_BINS),
        "token_percentiles": token_percentiles,
        "token_histogram": histogram(token_lengths, TEXT_TOKEN_BINS),
        "pdf_scan": {"scanned": int(pdf_scanned), "not_scanned": int(pdf_not_scanned), "unknown": int(pdf_unknown)},
        "pdf_detection": {
            "sample_pages": int(pdf_sample_pages),
            "scan_max_chars_per_page": int(pdf_scan_max_chars),
            "text_min_chars_per_page": int(pdf_text_min_chars),
            "scan_ratio_threshold": float(pdf_scan_ratio_threshold),
        },
        "risk_buckets": {
            k: int(v)
            for k, v in sorted(
                risk_bucket_counts.items(),
                key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")),
            )
            if int(v or 0) > 0
        },
        "primary_tag_counts": {
            k: int(v)
            for k, v in sorted(primary_tag_counts.items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")))
            if int(v or 0) > 0
        },
        "processing_path_counts": {
            k: int(v)
            for k, v in sorted(processing_path_counts.items(), key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")))
            if int(v or 0) > 0
        },
        "near_dup_summary": near_dup_summary,
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
        "root_path": REDACTED_MASK if redact_paths else str(root),
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

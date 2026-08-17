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

import csv
import hashlib
import io
import json
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
from app.core.constants import NON_CRITICAL_EXCEPTION_LOG_MESSAGE
from app.core.optional_deps import optional_import
from app.core.token_utils import estimate_tokens
from app.models.dataset import Dataset as DBDataset
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.parsing.quality.text_quality import score_parsed_text_quality
from app.rag.core.logging import get_logger
from app.rag.preprocessing.language import detect_language
from app.rag.preprocessing.pii_anonymizer import anonymize_pii, find_pii_matches
from app.rag.preprocessing.secrets import find_secret_matches, redact_secrets
from app.rag.tools.pre_poc_scanner.settings import resolve_pre_poc_scanner_thresholds
from app.services.dataset_embedding_advisory import build_embedding_language_advisories
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
# Redaction placeholder, not a credential.
SECRET_MASK = "[SECRET]"  # noqa: S105
PRECHECK_SAMPLE_RATIO_NUMERATOR = 3
PRECHECK_SAMPLE_RATIO_DENOMINATOR = 1000
PRECHECK_SAMPLE_MAX_SIZE = 2000

_SAMPLE_REVIEW_KEYS = {
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
}
_LANGUAGE_BUCKETS = {"zh", "en", "mixed", "unknown"}
_REUSE_CONFIG_KEYS = {
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
_RISKY_FINDING_KEYS = {
    str(key).strip().lower()
    for key, reason in FINDING_KEY_REASONS.items()
    if str((reason or {}).get("severity") or "").strip().lower() in {"warning", "error"}
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
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
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


def _iter_jsonl_objects(jsonl_path: Path) -> Iterable[dict[str, Any]]:
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue
            if isinstance(obj, dict):
                yield obj


def _sample_pdf_state(*, file_type: str, pdf_scanned: object) -> str:
    if file_type.lower() != "pdf":
        return "na"
    if pdf_scanned is True:
        return "scan"
    if pdf_scanned is False:
        return "text"
    return "unknown"


def _push_top_records(arr: list[dict[str, Any]], item: dict[str, Any], *, key: str, top_k: int = 20) -> None:
    arr.append(item)
    arr.sort(key=lambda x: int(x.get(key) or 0), reverse=True)
    if len(arr) > top_k:
        del arr[top_k:]


def _collect_sample_payload_buckets(
    *, jsonl_path: Path
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    type_groups: dict[str, list[dict[str, Any]]] = {}
    findings_buckets: dict[str, list[dict[str, Any]]] = {}
    largest: list[dict[str, Any]] = []
    longest: list[dict[str, Any]] = []

    for obj in _iter_jsonl_objects(jsonl_path):
        file_type = str(obj.get("file_type") or "unknown")
        file_size = int(obj.get("file_size") or 0)
        pdf_state = _sample_pdf_state(file_type=file_type, pdf_scanned=obj.get("pdf_scanned"))
        key = (file_type.lower(), _bucket_file_size_label(file_size), pdf_state)
        groups.setdefault(key, []).append(obj)
        type_groups.setdefault(file_type.lower(), []).append(obj)

        findings = obj.get("findings")
        if isinstance(findings, list):
            for fk in findings:
                fkey = str(fk or "").strip().lower()
                if fkey:
                    findings_buckets.setdefault(fkey, []).append(obj)

        _push_top_records(largest, obj, key="file_size", top_k=20)
        _push_top_records(longest, obj, key="text_characters", top_k=20)

    return groups, type_groups, findings_buckets, largest, longest


def _pick_representative_sample(items: list[dict[str, Any]], *, salt: str) -> dict[str, Any] | None:
    keyed_items = [(_stable_sample_key(item, salt=salt), str(item.get("name") or ""), item) for item in items]
    if not keyed_items:
        return None
    return min(keyed_items, key=lambda entry: (entry[0], entry[1]))[2]


def _build_representative_samples(
    *, type_groups: dict[str, list[dict[str, Any]]], target_size: int
) -> tuple[int, list[dict[str, Any]]]:
    rep: list[dict[str, Any]] = []
    picked_names: set[str] = set()
    target_size = max(0, min(int(target_size or 0), PRECHECK_SAMPLE_MAX_SIZE))
    if len(type_groups) > target_size:
        target_size = min(PRECHECK_SAMPLE_MAX_SIZE, len(type_groups))
    type_minimum = min(len(type_groups), target_size)

    for file_type, items in sorted(type_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:type_minimum]:
        item = _pick_representative_sample(items, salt=f"type:{file_type}")
        name = str((item or {}).get("name") or "")
        if item is not None and name and name not in picked_names:
            picked_names.add(name)
            rep.append(item)
        if len(rep) >= target_size:
            return target_size, rep

    remaining = [
        item for items in type_groups.values() for item in items if str(item.get("name") or "") not in picked_names
    ]
    remaining.sort(key=lambda o: (_stable_sample_key(o, salt="ratio-fill"), str(o.get("name") or "")))
    for item in remaining:
        name = str(item.get("name") or "")
        if name and name not in picked_names:
            picked_names.add(name)
            rep.append(item)
        if len(rep) >= target_size:
            break
    return target_size, rep


def _build_needs_review_samples(
    *, findings_buckets: dict[str, list[dict[str, Any]]], target_size: int
) -> dict[str, list[dict[str, Any]]]:
    needs_review: dict[str, list[dict[str, Any]]] = {}
    limit = min(10, max(1, int(target_size or 0) // 6))
    for fk, items in findings_buckets.items():
        if fk not in _SAMPLE_REVIEW_KEYS:
            continue
        needs_review[fk] = sorted(items, key=lambda o: int(o.get("file_size") or 0), reverse=True)[:limit]
    return needs_review


def _build_samples_payload(*, jsonl_path: Path, target_size: int) -> dict[str, Any]:
    """
    Build representative + problem-focused samples from a precheck JSONL artifact.

    Output is designed for pricing/POC alignment (shareable when redact_paths=true).
    """
    target_size = max(0, min(int(target_size or 0), 2000))
    if target_size <= 0:
        return {"requested": 0, "representative": [], "needs_review": {}, "top_large_files": [], "top_long_text": []}
    groups, type_groups, findings_buckets, largest, longest = _collect_sample_payload_buckets(jsonl_path=jsonl_path)
    target_size, representative = _build_representative_samples(type_groups=type_groups, target_size=target_size)

    return {
        "requested": int(target_size),
        "representative": representative,
        "needs_review": _build_needs_review_samples(findings_buckets=findings_buckets, target_size=target_size),
        "top_large_files": largest,
        "top_long_text": longest,
        "strata_count": int(len(groups)),
    }


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _upload_root_path() -> Path:
    upload_dir = getattr(settings, "UPLOAD_DIR", UPLOAD_DIR_FALLBACK) or UPLOAD_DIR_FALLBACK
    return Path(upload_dir).resolve(strict=False)


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

    upload_root = _upload_root_path()
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
    upload_root = _upload_root_path()
    allowed: list[Path] = [upload_root]
    for p in _parse_csv(str(getattr(settings, "LOCAL_SCAN_ROOTS", "") or "")):
        try:
            allowed.append(Path(p).expanduser().resolve(strict=False))
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
            continue

    resolved = root.expanduser().resolve(strict=False)
    for base in allowed:
        try:
            resolved.relative_to(base)
            return
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
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


def _merged_range_area(rng: Any) -> int:
    try:
        return int(rng.size)  # type: ignore[attr-defined]
    except Exception:
        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
    try:
        return int((rng.max_row - rng.min_row + 1) * (rng.max_col - rng.min_col + 1))  # type: ignore[attr-defined]
    except Exception:
        get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
        return 0


def _merged_area_for_sheet(ws: Any) -> int:
    merged_cells = getattr(ws, "merged_cells", None)
    ranges = list(getattr(merged_cells, "ranges", None) or [])
    return sum(_merged_range_area(rng) for rng in ranges[:5000])


def _clamp_unit_ratio(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


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

        for idx, name in enumerate(sheetnames[: max(1, int(max_sheets or 1))]):
            ws = wb[name]
            r = int(getattr(ws, "max_row", 0) or 0)
            c = int(getattr(ws, "max_column", 0) or 0)
            max_rows = max(max_rows, r)
            max_cols = max(max_cols, c)
            if idx == 0:
                merged_area = _merged_area_for_sheet(ws)

        total_area = max(1, int(max_rows) * int(max_cols))
        merged_ratio = _clamp_unit_ratio(float(merged_area) / float(total_area))

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


def _mask_email_value(raw: str) -> str:
    if "@" not in raw:
        return REDACTED_MASK
    local, domain = raw.split("@", 1)
    head = (local[:1] + "***") if local else "***"
    return f"{head}@{domain}"


def _mask_ip_value(raw: str) -> str:
    parts = raw.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3] + ["***"])
    return REDACTED_MASK


def _mask_phone_value(raw: str) -> str:
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) >= 7:
        return f"{digits[:3]}****{digits[-2:]}"
    return REDACTED_MASK


def _mask_credit_card_value(raw: str) -> str:
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) >= 8:
        return f"{digits[:4]}****{digits[-4:]}"
    return REDACTED_MASK


def _mask_cn_id_value(raw: str) -> str:
    if len(raw) >= 10:
        return f"{raw[:6]}********{raw[-2:]}"
    return REDACTED_MASK


def _mask_pii_value(kind: str, raw: str) -> str:
    k = (kind or "").strip().lower()
    s = (raw or "").strip()
    if not s:
        return REDACTED_MASK
    maskers = {
        "email": _mask_email_value,
        "ip": _mask_ip_value,
        "phone": _mask_phone_value,
        "credit_card": _mask_credit_card_value,
        "cn_id": _mask_cn_id_value,
        "ssn": lambda _value: "***-**-****",
    }
    masker = maskers.get(k)
    return masker(s) if masker is not None else REDACTED_MASK


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


@dataclass(frozen=True)
class _ScanOptions:
    cfg: dict[str, Any]
    root_path: str
    max_files: int
    max_total_bytes: int
    text_max_bytes: int
    pdf_sample_pages: int
    enable_pdf_quality: bool
    enable_text_extract: bool
    enable_pii: bool
    enable_secrets: bool
    compute_file_hash: bool
    redact_paths: bool
    enable_pii_samples: bool
    pii_context_chars: int
    pii_max_samples_per_file: int
    enable_secrets_samples: bool
    secrets_context_chars: int
    secrets_max_samples_per_file: int
    enable_near_dup: bool
    near_dup_hamming_threshold: int
    near_dup_max_pairs: int
    enable_sampling: bool
    sample_size_override: int | None
    pdf_scan_max_chars: int
    pdf_text_min_chars: int
    pdf_scan_ratio_threshold: float
    spreadsheet_large_row_threshold: int
    spreadsheet_wide_col_threshold: int
    spreadsheet_sheet_threshold: int
    spreadsheet_merged_ratio_threshold: float
    language_min_chars: int
    text_short_chars_threshold: int
    text_density_threshold: float
    text_gibberish_density_threshold: float
    text_high_replacement_ratio_threshold: float
    pdf_low_density_ratio_threshold: float
    directory_stats_limit: int
    allowed_exts: set[str]


@dataclass
class _ScanAccumulator:
    by_type: dict[str, int] = field(default_factory=dict)
    bytes_by_type: dict[str, int] = field(default_factory=dict)
    file_sizes: list[int] = field(default_factory=list)
    text_lengths: list[int] = field(default_factory=list)
    token_lengths: list[int] = field(default_factory=list)
    language_counts: Counter[str] = field(default_factory=Counter)
    directory_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    pii_totals: dict[str, int] = field(default_factory=dict)
    secrets_totals: dict[str, int] = field(default_factory=dict)
    pdf_scanned: int = 0
    pdf_not_scanned: int = 0
    pdf_unknown: int = 0
    finding_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FINDING_KEY_REASONS.keys(), 0))
    risk_bucket_counts: dict[str, int] = field(default_factory=dict)
    primary_tag_counts: Counter[str] = field(default_factory=Counter)
    processing_path_counts: Counter[str] = field(default_factory=Counter)
    sha_counts: dict[str, int] = field(default_factory=dict)
    simhash_entries: list[tuple[str, int, int, int, int]] = field(default_factory=list)
    errors: int = 0
    reused_files: int = 0
    cancelled: bool = False


def _normalize_language_bucket(value: object) -> str:
    s = str(value or "").strip().lower()
    return s if s in _LANGUAGE_BUCKETS else "unknown"


def _dir_key(name: str) -> str:
    s = str(name or "").replace("\\", "/").strip()
    d = os.path.dirname(s)
    return d if d else "."


def _mark_run_running(db: Session, run: DBDatasetPrecheckScanRun) -> None:
    run.status = "running"
    run.progress = 0
    run.started_at = _now_utc()
    run.updated_at = run.started_at
    run.error_message = None
    db.commit()


def _build_scan_options(*, cfg: dict[str, Any]) -> _ScanOptions:
    max_files_cap = safe_int(getattr(settings, "PRECHECK_SCAN_MAX_FILES", 20_000), default=20_000)
    requested_max_files = cfg.get("max_files")
    max_files_req = safe_int(requested_max_files, default=0)
    max_files = max_files_cap if max_files_req <= 0 else min(max_files_cap, max_files_req)

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
    raw_sample_size = cfg.get("sample_size")
    if raw_sample_size is not None or configured_default_sample_size > 0:
        sample_size_override = int(thresholds["sample_size"])
    else:
        sample_size_override = None

    pii_context_chars = max(0, min(safe_int(cfg.get("pii_context_chars") or 50, default=50), 500))
    pii_max_samples_per_file = max(0, min(safe_int(cfg.get("pii_max_samples_per_file") or 5, default=5), 50))
    secrets_context_chars = max(0, min(safe_int(cfg.get("secrets_context_chars") or 50, default=50), 500))
    secrets_max_samples_per_file = max(0, min(safe_int(cfg.get("secrets_max_samples_per_file") or 5, default=5), 50))
    near_dup_hamming_threshold = max(0, min(safe_int(cfg.get("near_dup_hamming_threshold") or 5, default=5), 32))
    near_dup_max_pairs = max(0, min(safe_int(cfg.get("near_dup_max_pairs") or 5000, default=5000), 200_000))
    spreadsheet_merged_ratio_threshold = _clamp_unit_ratio(
        float(getattr(settings, "PRECHECK_SPREADSHEET_MERGED_RATIO_THRESHOLD", 0.15) or 0.15)
    )
    directory_stats_limit = max(
        0,
        min(safe_int(getattr(settings, "PRECHECK_DIRECTORY_STATS_LIMIT", 200), default=200), 2000),
    )

    redact_paths = bool(cfg.get("redact_paths", False))
    return _ScanOptions(
        cfg=cfg,
        root_path=str(cfg.get("root_path") or "").strip(),
        max_files=max_files,
        max_total_bytes=safe_int(getattr(settings, "PRECHECK_SCAN_MAX_TOTAL_BYTES", 0), default=0),
        text_max_bytes=safe_int(
            cfg.get("text_extract_max_bytes") or getattr(settings, "PRECHECK_TEXT_EXTRACT_MAX_BYTES", 2_000_000),
            default=2_000_000,
        ),
        pdf_sample_pages=safe_int(
            cfg.get("pdf_sample_pages") or getattr(settings, "PRECHECK_PDF_SAMPLE_PAGES", 3),
            default=3,
        ),
        enable_pdf_quality=bool(cfg.get("enable_pdf_quality", True)),
        enable_text_extract=bool(cfg.get("enable_text_extract", True)),
        enable_pii=bool(cfg.get("enable_pii", False)),
        enable_secrets=bool(cfg.get("enable_secrets", False)),
        compute_file_hash=bool(cfg.get("compute_file_hash", False)),
        redact_paths=redact_paths,
        enable_pii_samples=False if redact_paths else bool(cfg.get("enable_pii_samples", False)),
        pii_context_chars=pii_context_chars,
        pii_max_samples_per_file=pii_max_samples_per_file,
        enable_secrets_samples=False if redact_paths else bool(cfg.get("enable_secrets_samples", False)),
        secrets_context_chars=secrets_context_chars,
        secrets_max_samples_per_file=secrets_max_samples_per_file,
        enable_near_dup=bool(cfg.get("enable_near_dup", False)),
        near_dup_hamming_threshold=near_dup_hamming_threshold,
        near_dup_max_pairs=near_dup_max_pairs,
        enable_sampling=bool(cfg.get("enable_sampling", True)),
        sample_size_override=sample_size_override,
        pdf_scan_max_chars=safe_int(
            cfg.get("pdf_min_text_chars_per_page") or getattr(settings, "PRECHECK_PDF_MIN_TEXT_CHARS_PER_PAGE", 50),
            default=50,
        ),
        pdf_text_min_chars=safe_int(
            cfg.get("pdf_text_chars_per_page") or getattr(settings, "PRECHECK_PDF_TEXT_CHARS_PER_PAGE", 200),
            default=200,
        ),
        pdf_scan_ratio_threshold=float(thresholds["pdf_scan_ratio_threshold"]),
        spreadsheet_large_row_threshold=safe_int(
            getattr(settings, "PRECHECK_SPREADSHEET_LARGE_ROW_THRESHOLD", 5000),
            default=5000,
        ),
        spreadsheet_wide_col_threshold=safe_int(
            getattr(settings, "PRECHECK_SPREADSHEET_WIDE_COL_THRESHOLD", 80),
            default=80,
        ),
        spreadsheet_sheet_threshold=safe_int(
            getattr(settings, "PRECHECK_SPREADSHEET_SHEET_THRESHOLD", 5),
            default=5,
        ),
        spreadsheet_merged_ratio_threshold=spreadsheet_merged_ratio_threshold,
        language_min_chars=safe_int(getattr(settings, "PRECHECK_LANGUAGE_MIN_CHARS", 40), default=40),
        text_short_chars_threshold=int(thresholds["text_short_chars_threshold"]),
        text_density_threshold=float(thresholds["text_density_threshold"]),
        text_gibberish_density_threshold=float(thresholds["text_gibberish_density_threshold"]),
        text_high_replacement_ratio_threshold=float(thresholds["text_high_replacement_ratio_threshold"]),
        pdf_low_density_ratio_threshold=float(thresholds["pdf_low_density_ratio_threshold"]),
        directory_stats_limit=directory_stats_limit,
        allowed_exts=set(getattr(settings, "allowed_extensions_list", []) or []),
    )


def _collect_scan_candidates(
    *, root: Path, allowed_exts: set[str], max_files: int, max_total_bytes: int
) -> tuple[list[Path], Counter[str]]:
    candidates: list[Path] = []
    candidate_type_counts: Counter[str] = Counter()
    total_bytes_seen = 0
    for path in _iter_files(root, max_files=max_files):
        ext = path.suffix.lower()
        if ext not in allowed_exts:
            continue
        try:
            size = int(path.stat().st_size)
        except Exception:
            size = 0
        if max_total_bytes > 0 and (total_bytes_seen + size) > max_total_bytes:
            break
        candidates.append(path)
        file_type = ext.lstrip(".") if ext.startswith(".") else (path.suffix or "").lower().lstrip(".") or "unknown"
        candidate_type_counts[str(file_type or "unknown").lower()] += 1
        total_bytes_seen += size
    return candidates, candidate_type_counts


def _empty_findings_summary() -> list[dict[str, Any]]:
    return [
        {
            "key": k,
            "label": v.get("label", k),
            "severity": v.get("severity", "info"),
            "count": 0,
            "description": v.get("description"),
        }
        for k, v in FINDING_KEY_REASONS.items()
    ]


def _build_empty_scan_summary(
    *,
    dataset_id: UUID,
    scan_run_id: UUID,
    generated_at: datetime,
    pdf_sample_pages: int,
    pdf_scan_max_chars: int,
    pdf_text_min_chars: int,
    pdf_scan_ratio_threshold: float,
) -> dict[str, Any]:
    return {
        "dataset_id": str(dataset_id),
        "scan_run_id": str(scan_run_id),
        "generated_at": generated_at.isoformat(),
        "schema_id": "mimirq.dataset_precheck_summary.v3",
        "schema_version": 3,
        "total_files": 0,
        "total_size_bytes": 0,
        "reused_files": 0,
        "by_file_type": {},
        "by_file_type_bytes": {},
        "file_type_stats": [],
        "language_mix": {},
        "embedding_advisories": [],
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
        "findings": _empty_findings_summary(),
    }


def _prepare_artifact_paths(*, tenant_id: UUID, scan_run_id: UUID) -> tuple[Path, Path, Path, Path]:
    artifact_root = (
        Path(getattr(settings, "UPLOAD_DIR", UPLOAD_DIR_FALLBACK) or UPLOAD_DIR_FALLBACK)
        / str(tenant_id)
        / "precheck"
        / str(scan_run_id)
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    jsonl_path = (artifact_root / "files.jsonl").resolve(strict=False)
    samples_path = (artifact_root / "samples.json").resolve(strict=False)
    return artifact_root, jsonl_path, samples_path, artifact_root / "near_dups.json"


def _reuse_cfg_subset(cfg: dict[str, Any]) -> dict[str, Any]:
    return {k: cfg.get(k) for k in _REUSE_CONFIG_KEYS if k in cfg}


def _query_previous_scan_run(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    reuse_from_scan_run_id: UUID | None,
) -> DBDatasetPrecheckScanRun | None:
    if reuse_from_scan_run_id is not None:
        return (
            db.query(DBDatasetPrecheckScanRun)
            .filter(
                DBDatasetPrecheckScanRun.id == reuse_from_scan_run_id,
                DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                DBDatasetPrecheckScanRun.dataset_id == dataset_id,
            )
            .first()
        )
    return (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
            DBDatasetPrecheckScanRun.status == "completed",
        )
        .order_by(DBDatasetPrecheckScanRun.created_at.desc())
        .first()
    )


def _resolve_reusable_jsonl_path(*, tenant_id: UUID, prev_run: DBDatasetPrecheckScanRun) -> Path | None:
    prev_artifacts = getattr(prev_run, "artifacts", None)
    prev_artifacts = prev_artifacts if isinstance(prev_artifacts, dict) else {}
    prev_jsonl_raw = str(prev_artifacts.get("files_jsonl") or "").strip()
    prev_jsonl = Path(prev_jsonl_raw) if prev_jsonl_raw else None
    if prev_jsonl is None or not prev_jsonl.exists() or not prev_jsonl.is_file():
        return None
    try:
        upload_root = _upload_root_path()
        tenant_root = (upload_root / str(tenant_id)).resolve(strict=False)
        prev_jsonl.resolve(strict=False).relative_to(tenant_root)
    except Exception:
        return None
    return prev_jsonl


def _load_jsonl_records_by_name(jsonl_path: Path) -> dict[str, dict[str, Any]]:
    prev_records: dict[str, dict[str, Any]] = {}
    for obj in _iter_jsonl_objects(jsonl_path):
        name = str(obj.get("name") or "").strip()
        if name:
            prev_records[name] = obj
    return prev_records


def _load_previous_records(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    options: _ScanOptions,
    reuse_from_scan_run_id: UUID | None,
) -> dict[str, dict[str, Any]]:
    if not bool(options.cfg.get("reuse_unchanged_files", False)):
        return {}
    if options.redact_paths:
        logger.info("Skip reuse_unchanged_files in redact_paths mode")
        return {}

    prev_run = _query_previous_scan_run(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        reuse_from_scan_run_id=reuse_from_scan_run_id,
    )
    if prev_run is None:
        return {}

    prev_cfg = dict(getattr(prev_run, "config", None) or {})
    prev_root = str(prev_cfg.get("root_path") or "").strip()
    if not prev_root or prev_root != options.root_path or bool(prev_cfg.get("redact_paths", False)):
        logger.info("Skip reuse_unchanged_files due to root_path mismatch or redacted prev run")
        return {}
    if _reuse_cfg_subset(options.cfg) != _reuse_cfg_subset(prev_cfg):
        logger.info(
            "Skip reuse_unchanged_files due to config mismatch (scan_run_id=%s)",
            str(getattr(prev_run, "id", "")),
        )
        return {}

    prev_jsonl = _resolve_reusable_jsonl_path(tenant_id=tenant_id, prev_run=prev_run)
    if prev_jsonl is None:
        return {}
    try:
        return _load_jsonl_records_by_name(prev_jsonl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load previous precheck JSONL (reuse disabled): %s", str(exc)[:200])
        return {}


def _append_finding(rec: _FileRecord, state: _ScanAccumulator, key: str) -> None:
    if key not in rec.findings:
        rec.findings.append(key)
        if key in state.finding_counts:
            state.finding_counts[key] += 1


def _record_parse_failure(
    rec: _FileRecord,
    state: _ScanAccumulator,
    *,
    file_type: str,
    error_message: str,
) -> None:
    state.errors += 1
    rec.error_message = str(error_message)[:200]
    _append_finding(rec, state, "parse_failed")
    parse_failure_kind = classify_parse_failure_kind(file_type=file_type, error_message=rec.error_message)
    rec.parse_failure_kind = parse_failure_kind
    if parse_failure_kind:
        _append_finding(rec, state, parse_failure_kind)


def _build_file_record(*, path: Path, root: Path, idx: int, redact_paths: bool) -> tuple[_FileRecord, str, int]:
    ext = path.suffix.lower()
    try:
        rel = str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        rel = path.name
    try:
        st = path.stat()
        size = int(st.st_size)
        mtime = int(st.st_mtime)
    except Exception:
        size = 0
        mtime = 0
    rec = _FileRecord(
        name=_sanitize_display_name(rel) if not redact_paths else f"FILE_{idx:06d}{ext}",
        file_type=ext.lstrip(".") if ext.startswith(".") else (path.suffix or "").lower().lstrip(".") or "unknown",
        file_size=size,
        file_mtime=mtime,
    )
    return rec, ext, size


def _apply_record_text_estimate(
    rec: _FileRecord,
    *,
    sample_text: str,
    sample_tokens: int,
    estimated_text: bool,
    ratio: float,
) -> None:
    if estimated_text:
        rec.text_characters = int(len(sample_text) * ratio)
        rec.text_tokens_est = int(sample_tokens * ratio)
        rec.estimated_text = True
        return
    rec.text_characters = int(len(sample_text))
    rec.text_tokens_est = int(sample_tokens)
    rec.estimated_text = False


def _extract_textlike_sample(path: Path, *, size: int, rec: _FileRecord, options: _ScanOptions) -> tuple[str, bool]:
    sample_text, estimated_text = _read_text_sample(path, max_bytes=options.text_max_bytes)
    if sample_text:
        sample_tokens = int(estimate_tokens(sample_text) or 0)
        ratio = size / max(1, min(size, options.text_max_bytes)) if estimated_text and size > 0 else 1.0
        _apply_record_text_estimate(
            rec,
            sample_text=sample_text,
            sample_tokens=sample_tokens,
            estimated_text=estimated_text,
            ratio=ratio,
        )
    return sample_text, estimated_text


def _extract_pdf_sample(
    path: Path,
    *,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> tuple[str, bool]:
    sample_text, estimated_text, page_count, per_page_chars, pdf_err = _pdf_text_sample(
        path, sample_pages=options.pdf_sample_pages
    )
    if pdf_err:
        rec.error_message = str(pdf_err)[:200]
        err_l = str(pdf_err or "").strip().lower()
        if any(token in err_l for token in {"password", "encrypt", "encryption"}):
            _append_finding(rec, state, "pdf_encrypted")
        _append_finding(rec, state, "parse_failed")
        state.errors += 1
    if sample_text:
        sample_tokens = int(estimate_tokens(sample_text) or 0)
        sample_page_count = max(1, min(page_count, options.pdf_sample_pages))
        ratio = page_count / sample_page_count if estimated_text and page_count > 0 else 1.0
        _apply_record_text_estimate(
            rec,
            sample_text=sample_text,
            sample_tokens=sample_tokens,
            estimated_text=estimated_text,
            ratio=ratio,
        )
    if page_count > 0 and per_page_chars:
        rec.pdf_pages = _build_pdf_page_breakdown(
            page_count=page_count,
            per_page_chars=per_page_chars,
            scan_max_chars=options.pdf_scan_max_chars,
            text_min_chars=options.pdf_text_min_chars,
        )
    return sample_text, estimated_text


def _extract_sample_text(
    path: Path,
    *,
    ext: str,
    size: int,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> tuple[str, bool]:
    if not options.enable_text_extract:
        return "", False
    if ext in TEXTLIKE_EXTS:
        return _extract_textlike_sample(path, size=size, rec=rec, options=options)
    if ext == ".pdf":
        return _extract_pdf_sample(path, rec=rec, state=state, options=options)
    return "", False


def _detect_record_language(sample_text: str, *, rec: _FileRecord, options: _ScanOptions) -> None:
    try:
        lang = detect_language(sample_text, min_chars=options.language_min_chars)
        rec.language = _normalize_language_bucket(getattr(lang, "language", "unknown"))
        rec.language_confidence = float(getattr(lang, "confidence", 0.0) or 0.0)
    except Exception:
        rec.language = "unknown"
        rec.language_confidence = 0.0


def _apply_text_quality_score_findings(
    sample_text: str,
    *,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    try:
        tq = score_parsed_text_quality(sample_text)
    except Exception:
        tq = None
    if tq is None:
        return
    replacement_ratio = float(getattr(tq, "replacement_ratio", 0.0) or 0.0)
    chars_non_space = int(getattr(tq, "chars_non_space", 0) or 0)
    density = float(getattr(tq, "density", 1.0) or 1.0)
    if replacement_ratio >= options.text_high_replacement_ratio_threshold:
        _append_finding(rec, state, "gibberish_text")
    if chars_non_space >= 200 and density < options.text_density_threshold:
        _append_finding(rec, state, "low_density_text")
    if chars_non_space >= 1000 and density < options.text_gibberish_density_threshold:
        _append_finding(rec, state, "gibberish_text")


def _apply_text_findings(
    sample_text: str,
    *,
    ext: str,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    if not options.enable_text_extract:
        return
    if ext in TEXTLIKE_EXTS and not sample_text.strip():
        _append_finding(rec, state, "empty_text")
    if (
        int(rec.text_characters or 0) > 0
        and options.text_short_chars_threshold > 0
        and int(rec.text_characters) < options.text_short_chars_threshold
    ):
        _append_finding(rec, state, "short_text")
    if not sample_text:
        return
    _detect_record_language(sample_text, rec=rec, options=options)
    _apply_text_quality_score_findings(sample_text, rec=rec, state=state, options=options)


def _append_simhash_entry(rec: _FileRecord, state: _ScanAccumulator, *, sample_text: str) -> None:
    if not sample_text:
        return
    try:
        sim = _simhash64(sample_text)
    except Exception:
        sim = 0
    if sim:
        rec.text_simhash64 = f"{int(sim) & ((1 << 64) - 1):016x}"
        state.simhash_entries.append(
            (
                rec.name,
                int(sim),
                int(rec.file_size or 0),
                int(rec.text_characters or 0),
                int(rec.file_mtime or 0),
            )
        )


def _apply_pdf_scan_findings(rec: _FileRecord, *, state: _ScanAccumulator, options: _ScanOptions) -> None:
    if not options.enable_pdf_quality:
        return
    if "parse_failed" in rec.findings:
        rec.pdf_scanned = None
        return
    breakdown = rec.pdf_pages if isinstance(rec.pdf_pages, dict) else None
    page_count = int(breakdown.get("page_count") or 0) if breakdown else 0
    if page_count <= 0:
        rec.pdf_scanned = None
        _append_finding(rec, state, "pdf_unknown")
        state.pdf_unknown += 1
        return
    scan_ratio = float(breakdown.get("scan_ratio") or 0.0) if breakdown else 0.0
    low_density_ratio = float(breakdown.get("low_density_ratio") or 0.0) if breakdown else 0.0
    scanned = bool(scan_ratio >= options.pdf_scan_ratio_threshold)
    rec.pdf_scanned = scanned
    if scanned:
        _append_finding(rec, state, "pdf_scanned")
        state.pdf_scanned += 1
    else:
        state.pdf_not_scanned += 1
    if not breakdown:
        return
    if int(breakdown.get("scanned_pages") or 0) > 0 and int(breakdown.get("text_pages") or 0) > 0:
        _append_finding(rec, state, "pdf_mixed")
    if low_density_ratio >= options.pdf_low_density_ratio_threshold:
        _append_finding(rec, state, "pdf_low_density")


def _csv_spreadsheet_stats_from_sample(
    *,
    sample_text: str,
    estimated_text: bool,
    size: int,
    text_max_bytes: int,
) -> dict[str, Any] | None:
    if not sample_text:
        return None
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
        try:
            dialect: csv.Dialect = csv.Sniffer().sniff(sniff_sample, delimiters=",\t;|")
        except Exception:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(sample_text), dialect)
        for row in reader:
            if row and any(str(c).strip() for c in row):
                col_count = int(len(row))
                break
    except Exception:
        col_count = 0
    return {
        "row_count": int(row_count),
        "col_count": int(col_count),
        "sheet_count": 1,
        "merged_cell_ratio": 0.0,
        "estimated_rows": bool(estimated_rows),
        "estimated_cols": False,
    }


def _apply_spreadsheet_findings(rec: _FileRecord, *, state: _ScanAccumulator, options: _ScanOptions) -> None:
    if not isinstance(rec.spreadsheet, dict):
        return
    rows = int(rec.spreadsheet.get("row_count") or 0)
    cols = int(rec.spreadsheet.get("col_count") or 0)
    sheets = int(rec.spreadsheet.get("sheet_count") or 0)
    try:
        merged_ratio = float(rec.spreadsheet.get("merged_cell_ratio") or 0.0)
    except Exception:
        merged_ratio = 0.0
    if options.spreadsheet_large_row_threshold > 0 and rows >= options.spreadsheet_large_row_threshold:
        _append_finding(rec, state, "large_spreadsheet")
    if options.spreadsheet_wide_col_threshold > 0 and cols >= options.spreadsheet_wide_col_threshold:
        _append_finding(rec, state, "wide_spreadsheet")
    if options.spreadsheet_sheet_threshold > 0 and sheets >= options.spreadsheet_sheet_threshold:
        _append_finding(rec, state, "many_sheets_spreadsheet")
    if options.spreadsheet_merged_ratio_threshold > 0.0 and merged_ratio >= options.spreadsheet_merged_ratio_threshold:
        _append_finding(rec, state, "merged_heavy_spreadsheet")


def _mask_sample_context(text: str) -> str:
    masked = anonymize_pii(text, enabled=True, mode="mask").text
    masked = redact_secrets(masked, enabled=True, mode="mask").text
    return masked[:2000] + "..." if len(masked) > 2000 else masked


def _collect_match_context(sample_text: str, *, start: int, end: int, context_chars: int) -> str:
    ctx_start = max(0, start - int(context_chars))
    ctx_end = min(len(sample_text), end + int(context_chars))
    return _mask_sample_context(sample_text[ctx_start:ctx_end])


def _apply_pii_findings(sample_text: str, *, rec: _FileRecord, state: _ScanAccumulator, options: _ScanOptions) -> None:
    if not (sample_text and options.enable_pii):
        return
    pii = anonymize_pii(sample_text, enabled=True, mode="mask")
    if pii.hits:
        rec.pii_hits = {str(k): int(v) for k, v in pii.hits.items() if int(v) > 0}
        if rec.pii_hits:
            _append_finding(rec, state, "pii")
            for k, v in rec.pii_hits.items():
                state.pii_totals[k] = state.pii_totals.get(k, 0) + int(v)
    if not (options.enable_pii_samples and options.pii_max_samples_per_file > 0):
        return
    for match in find_pii_matches(sample_text, max_matches=options.pii_max_samples_per_file):
        start = int(getattr(match, "start", 0) or 0)
        end = int(getattr(match, "end", 0) or 0)
        if end <= start:
            continue
        rec.pii_samples.append(
            {
                "kind": str(getattr(match, "kind", "") or "pii"),
                "masked": _mask_pii_value(
                    str(getattr(match, "kind", "") or ""),
                    str(getattr(match, "text", "") or ""),
                ),
                "context": _collect_match_context(
                    sample_text,
                    start=start,
                    end=end,
                    context_chars=options.pii_context_chars,
                ),
                "start": start,
                "end": end,
            }
        )


def _apply_secret_findings(
    sample_text: str,
    *,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    if not (sample_text and options.enable_secrets):
        return
    sec = redact_secrets(sample_text, enabled=True, mode="mask")
    if sec.hits:
        rec.secrets_hits = {str(k): int(v) for k, v in sec.hits.items() if int(v) > 0}
        if rec.secrets_hits:
            _append_finding(rec, state, "secrets")
            for k, v in rec.secrets_hits.items():
                state.secrets_totals[k] = state.secrets_totals.get(k, 0) + int(v)
    if not (options.enable_secrets_samples and options.secrets_max_samples_per_file > 0):
        return
    for match in find_secret_matches(sample_text, max_matches=options.secrets_max_samples_per_file):
        start = int(getattr(match, "start", 0) or 0)
        end = int(getattr(match, "end", 0) or 0)
        if end <= start:
            continue
        rec.secrets_samples.append(
            {
                "kind": str(getattr(match, "kind", "") or "secret"),
                "masked": _mask_secret_value(
                    str(getattr(match, "kind", "") or ""),
                    str(getattr(match, "text", "") or ""),
                ),
                "context": _collect_match_context(
                    sample_text,
                    start=start,
                    end=end,
                    context_chars=options.secrets_context_chars,
                ),
                "start": start,
                "end": end,
            }
        )


def _apply_file_hash(path: Path, *, rec: _FileRecord, state: _ScanAccumulator) -> None:
    sha = _safe_hash_file(path, algo="sha256")
    rec.file_sha256 = sha
    state.sha_counts[sha] = state.sha_counts.get(sha, 0) + 1


def _apply_spreadsheet_stats(
    path: Path,
    *,
    ext: str,
    size: int,
    sample_text: str,
    estimated_text: bool,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    if ext not in {".csv", ".xlsx"}:
        return
    if ext == ".csv":
        rec.spreadsheet = _csv_spreadsheet_stats_from_sample(
            sample_text=sample_text,
            estimated_text=estimated_text,
            size=size,
            text_max_bytes=options.text_max_bytes,
        )
    else:
        stats, xlsx_err = _xlsx_spreadsheet_stats(path)
        if isinstance(stats, dict) and stats:
            rec.spreadsheet = stats
        elif xlsx_err:
            rec.error_message = str(xlsx_err)[:200]
            _append_finding(rec, state, "parse_failed")
            state.errors += 1
    _apply_spreadsheet_findings(rec, state=state, options=options)


def _process_record_content(
    path: Path,
    *,
    ext: str,
    size: int,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    sample_text = ""
    estimated_text = False
    try:
        sample_text, estimated_text = _extract_sample_text(
            path,
            ext=ext,
            size=size,
            rec=rec,
            state=state,
            options=options,
        )
        _apply_text_findings(sample_text, ext=ext, rec=rec, state=state, options=options)
        if options.enable_near_dup:
            _append_simhash_entry(rec, state, sample_text=sample_text)
        if ext == ".pdf":
            _apply_pdf_scan_findings(rec, state=state, options=options)
        _apply_spreadsheet_stats(
            path,
            ext=ext,
            size=size,
            sample_text=sample_text,
            estimated_text=estimated_text,
            rec=rec,
            state=state,
            options=options,
        )
        _apply_pii_findings(sample_text, rec=rec, state=state, options=options)
        _apply_secret_findings(sample_text, rec=rec, state=state, options=options)
        if options.compute_file_hash:
            _apply_file_hash(path, rec=rec, state=state)
    except Exception as exc:  # noqa: BLE001
        _record_parse_failure(rec, state, file_type=rec.file_type, error_message=str(exc))


def _update_directory_stats(
    directory_stats: dict[str, dict[str, Any]],
    *,
    name: str,
    file_size: int,
    findings: list[str],
) -> None:
    d = _dir_key(name)
    entry = directory_stats.get(d)
    if entry is None:
        entry = {
            "path": d,
            "total_files": 0,
            "total_size_bytes": 0,
            "risky_files": 0,
            "findings": {},
        }
        directory_stats[d] = entry
    entry["total_files"] = int(entry.get("total_files") or 0) + 1
    entry["total_size_bytes"] = int(entry.get("total_size_bytes") or 0) + int(file_size or 0)
    fset = {str(value or "").strip().lower() for value in (findings or []) if str(value or "").strip()}
    if fset and (fset & _RISKY_FINDING_KEYS):
        entry["risky_files"] = int(entry.get("risky_files") or 0) + 1
    counts = entry.get("findings")
    if not isinstance(counts, dict):
        counts = {}
        entry["findings"] = counts
    for fk in fset:
        counts[fk] = int(counts.get(fk, 0) or 0) + 1


def _update_risk_bucket_counts(state: _ScanAccumulator, *, file_type: str, findings: list[str]) -> None:
    try:
        for bucket in risk_buckets_for_file(file_type=file_type, findings=findings):
            state.risk_bucket_counts[bucket] = int(state.risk_bucket_counts.get(bucket, 0) or 0) + 1
    except Exception as exc:
        logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)


def _ensure_parse_failure_kind(rec: _FileRecord, state: _ScanAccumulator) -> None:
    if not (rec.error_message and rec.parse_failure_kind is None and "parse_failed" in rec.findings):
        return
    parse_failure_kind = classify_parse_failure_kind(file_type=rec.file_type, error_message=rec.error_message)
    rec.parse_failure_kind = parse_failure_kind
    if parse_failure_kind:
        _append_finding(rec, state, parse_failure_kind)


def _apply_record_tags(rec: _FileRecord, state: _ScanAccumulator) -> str:
    file_type = str(rec.file_type or "unknown").strip().lower() or "unknown"
    rec.primary_tag = infer_primary_tag(file_type=file_type, findings=rec.findings)
    rec.processing_paths = infer_processing_paths(primary_tag=rec.primary_tag, findings=rec.findings)
    state.primary_tag_counts[rec.primary_tag] += 1
    for path_key in rec.processing_paths:
        state.processing_path_counts[str(path_key or "")] += 1
    return file_type


def _aggregate_record_metrics(rec: _FileRecord, *, file_type: str, state: _ScanAccumulator) -> None:
    state.by_type[file_type] = state.by_type.get(file_type, 0) + 1
    state.bytes_by_type[file_type] = state.bytes_by_type.get(file_type, 0) + int(rec.file_size or 0)
    state.file_sizes.append(int(rec.file_size or 0))
    if int(rec.text_characters or 0) > 0:
        state.text_lengths.append(int(rec.text_characters))
    if int(rec.text_tokens_est or 0) > 0:
        state.token_lengths.append(int(rec.text_tokens_est))
    state.language_counts[_normalize_language_bucket(rec.language)] += 1
    _update_directory_stats(
        state.directory_stats,
        name=rec.name,
        file_size=int(rec.file_size or 0),
        findings=list(rec.findings or []),
    )
    _update_risk_bucket_counts(state, file_type=file_type, findings=rec.findings)


def _write_record(jf: Any, rec: _FileRecord) -> None:
    jf.write(json.dumps(asdict(rec), ensure_ascii=False, separators=(",", ":")))
    jf.write("\n")


def _finalize_record(rec: _FileRecord, *, state: _ScanAccumulator, jf: Any) -> None:
    _ensure_parse_failure_kind(rec, state)
    file_type = _apply_record_tags(rec, state)
    _aggregate_record_metrics(rec, file_type=file_type, state=state)
    _write_record(jf, rec)


def _prev_has_parse_failed(prev_findings: list[Any]) -> bool:
    return "parse_failed" in {str(x or "").strip().lower() for x in prev_findings}


def _accumulate_reused_hit_totals(target: dict[str, int], hits: dict[str, Any]) -> None:
    for key, value in hits.items():
        try:
            target[str(key)] = target.get(str(key), 0) + int(value or 0)
        except Exception:
            get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)


def _apply_reused_text_metrics(prev: dict[str, Any], *, file_type: str, state: _ScanAccumulator) -> tuple[int, int]:
    file_size = int(prev.get("file_size") or 0)
    state.by_type[file_type] = state.by_type.get(file_type, 0) + 1
    state.bytes_by_type[file_type] = state.bytes_by_type.get(file_type, 0) + file_size
    state.file_sizes.append(file_size)
    text_chars = int(prev.get("text_characters") or 0)
    if text_chars > 0:
        state.text_lengths.append(text_chars)
    text_tokens = int(prev.get("text_tokens_est") or 0)
    if text_tokens > 0:
        state.token_lengths.append(text_tokens)
    state.language_counts[_normalize_language_bucket(prev.get("language"))] += 1
    return file_size, text_chars


def _apply_reused_pdf_and_findings(
    prev: dict[str, Any],
    *,
    file_type: str,
    file_size: int,
    rec: _FileRecord,
    state: _ScanAccumulator,
) -> list[Any]:
    prev_findings = prev.get("findings") if isinstance(prev.get("findings"), list) else []
    pdf_scanned = prev.get("pdf_scanned")
    if pdf_scanned is True:
        state.pdf_scanned += 1
    elif pdf_scanned is False:
        state.pdf_not_scanned += 1
    elif file_type == "pdf":
        state.pdf_unknown += 1
    if isinstance(prev_findings, list):
        for finding in {str(fk or "").strip().lower() for fk in prev_findings if str(fk or "").strip()}:
            if finding in state.finding_counts:
                state.finding_counts[finding] += 1
    _update_risk_bucket_counts(state, file_type=file_type, findings=prev_findings)
    _update_directory_stats(state.directory_stats, name=rec.name, file_size=file_size, findings=list(prev_findings))
    return prev_findings


def _apply_reused_signatures(
    prev: dict[str, Any],
    *,
    file_size: int,
    text_chars: int,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    if options.enable_near_dup:
        sim_hex = str(prev.get("text_simhash64") or "").strip().lower()
        if sim_hex:
            try:
                state.simhash_entries.append(
                    (
                        rec.name,
                        int(sim_hex, 16),
                        file_size,
                        text_chars,
                        int(prev.get("file_mtime") or 0),
                    )
                )
            except Exception as exc:
                logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)
    if options.compute_file_hash:
        sha = str(prev.get("file_sha256") or "").strip().lower()
        if sha:
            state.sha_counts[sha] = state.sha_counts.get(sha, 0) + 1


def _apply_reused_record(
    prev: dict[str, Any],
    *,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
) -> None:
    prev["name"] = rec.name
    prev["file_size"] = rec.file_size
    prev["file_mtime"] = rec.file_mtime
    file_type = str(prev.get("file_type") or rec.file_type or "unknown").strip().lower() or "unknown"
    file_size, text_chars = _apply_reused_text_metrics(prev, file_type=file_type, state=state)
    _apply_reused_pdf_and_findings(prev, file_type=file_type, file_size=file_size, rec=rec, state=state)
    _accumulate_reused_hit_totals(
        state.pii_totals,
        prev.get("pii_hits") if isinstance(prev.get("pii_hits"), dict) else {},
    )
    _accumulate_reused_hit_totals(
        state.secrets_totals,
        prev.get("secrets_hits") if isinstance(prev.get("secrets_hits"), dict) else {},
    )
    _apply_reused_signatures(
        prev,
        file_size=file_size,
        text_chars=text_chars,
        rec=rec,
        state=state,
        options=options,
    )


def _try_reuse_previous_record(
    prev_records: dict[str, dict[str, Any]],
    *,
    rec: _FileRecord,
    state: _ScanAccumulator,
    options: _ScanOptions,
    jf: Any,
    idx: int,
    flush_progress: Any,
) -> bool:
    prev = prev_records.get(rec.name)
    if not isinstance(prev, dict):
        return False
    try:
        prev_size = int(prev.get("file_size") or 0)
        prev_mtime = int(prev.get("file_mtime") or 0)
    except Exception:
        return False
    prev_findings = prev.get("findings") if isinstance(prev.get("findings"), list) else []
    if _prev_has_parse_failed(prev_findings):
        return False
    if prev_size != rec.file_size or prev_mtime != rec.file_mtime:
        return False
    state.reused_files += 1
    prev_copy = dict(prev)
    _apply_reused_record(prev_copy, rec=rec, state=state, options=options)
    _write_record(jf, _FileRecord(**{k: v for k, v in prev_copy.items() if k in _FileRecord.__dataclass_fields__}))
    flush_progress(idx)
    return True


def _process_candidate(
    path: Path,
    *,
    idx: int,
    root: Path,
    prev_records: dict[str, dict[str, Any]],
    state: _ScanAccumulator,
    options: _ScanOptions,
    jf: Any,
    flush_progress: Any,
) -> None:
    rec, ext, size = _build_file_record(path=path, root=root, idx=idx, redact_paths=options.redact_paths)
    if prev_records and not options.redact_paths:
        if _try_reuse_previous_record(
            prev_records,
            rec=rec,
            state=state,
            options=options,
            jf=jf,
            idx=idx,
            flush_progress=flush_progress,
        ):
            return
    _process_record_content(path, ext=ext, size=size, rec=rec, state=state, options=options)
    _finalize_record(rec, state=state, jf=jf)
    flush_progress(idx)


def _count_exact_duplicates(sha_counts: dict[str, int]) -> int:
    return sum(int(cnt) for cnt in sha_counts.values() if int(cnt) > 1)


def _find_union_root(parent: list[int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union_union_find(parent: list[int], rank: list[int], a: int, b: int) -> None:
    ra = _find_union_root(parent, a)
    rb = _find_union_root(parent, b)
    if ra == rb:
        return
    if rank[ra] < rank[rb]:
        parent[ra] = rb
    elif rank[ra] > rank[rb]:
        parent[rb] = ra
    else:
        parent[rb] = ra
        rank[ra] += 1


def _collect_near_dup_pairs(
    *, hashes: list[int], names: list[str], threshold: int, max_pairs: int
) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    buckets: dict[tuple[int, int], list[int]] = {}
    pairs: list[dict[str, Any]] = []
    parent = list(range(len(hashes)))
    rank = [0] * len(hashes)
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
            distance = _hamming_distance64(h, hashes[j])
            if distance <= threshold:
                pairs.append({"a": names[j], "b": names[i], "distance": int(distance)})
                _union_union_find(parent, rank, i, j)
                if len(pairs) >= max_pairs:
                    return pairs, parent, rank
    return pairs, parent, rank


def _cluster_keep_score(
    simhash_entries: list[tuple[str, int, int, int, int]],
    names: list[str],
    idx: int,
) -> tuple[int, int, int, str]:
    try:
        name, _hash, size, text_len, mtime = simhash_entries[idx]
        return int(text_len or 0), int(size or 0), int(mtime or 0), str(name or "")
    except Exception:
        return 0, 0, 0, names[idx]


def _build_near_dup_clusters(
    *,
    parent: list[int],
    names: list[str],
    simhash_entries: list[tuple[str, int, int, int, int]],
) -> tuple[list[dict[str, Any]], set[str]]:
    groups: dict[int, list[int]] = {}
    for idx in range(len(names)):
        groups.setdefault(_find_union_root(parent, idx), []).append(idx)
    clusters: list[dict[str, Any]] = []
    for root_id, members in groups.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda idx: _cluster_keep_score(simhash_entries, names, idx), reverse=True)
        keep_idx = ordered[0]
        member_names = [names[i] for i in ordered]
        cluster: dict[str, Any] = {
            "id": str(root_id),
            "members": member_names,
            "keep_candidate": str(names[keep_idx]),
            "keep_strategy": "max_text_chars_then_size_then_mtime",
            "review_candidates": member_names[1 : min(len(member_names), 21)],
        }
        member_stats = []
        for i in ordered[: min(50, len(ordered))]:
            try:
                name, _hash, size, text_len, mtime = simhash_entries[i]
                member_stats.append(
                    {
                        "name": str(name),
                        "file_size": int(size or 0),
                        "text_characters": int(text_len or 0),
                        "file_mtime": int(mtime or 0),
                    }
                )
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
        if member_stats:
            cluster["member_stats"] = member_stats
        clusters.append(cluster)
    clusters.sort(key=lambda c: (-len(c.get("members") or []), str(c.get("id") or "")))
    affected = {member for cluster in clusters for member in (cluster.get("members") or [])}
    return clusters, affected


def _build_near_dup_artifact(
    *,
    state: _ScanAccumulator,
    options: _ScanOptions,
    near_dup_path: Path,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not (
        options.enable_near_dup
        and state.simhash_entries
        and options.near_dup_hamming_threshold > 0
        and options.near_dup_max_pairs > 0
    ):
        return None, None
    names = [name for name, _hash, _size, _text_len, _mtime in state.simhash_entries]
    hashes = [int(_hash) for _name, _hash, _size, _text_len, _mtime in state.simhash_entries]
    pairs, parent, _rank = _collect_near_dup_pairs(
        hashes=hashes,
        names=names,
        threshold=options.near_dup_hamming_threshold,
        max_pairs=options.near_dup_max_pairs,
    )
    clusters, affected = _build_near_dup_clusters(
        parent=parent,
        names=names,
        simhash_entries=state.simhash_entries,
    )
    if affected:
        state.finding_counts["near_dup"] = int(len(affected))
    payload = {
        "threshold": int(options.near_dup_hamming_threshold),
        "max_pairs": int(options.near_dup_max_pairs),
        "pairs_returned": int(len(pairs)),
        "clusters_returned": int(len(clusters)),
        "clusters": clusters[:2000],
        "pairs": pairs[:5000],
    }
    near_dup_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return payload, near_dup_path.resolve(strict=False)


def _maybe_write_samples_artifact(
    *, jsonl_path: Path, samples_path: Path, enable_sampling: bool, sample_size: int
) -> bool:
    if not (enable_sampling and sample_size > 0):
        return False
    try:
        payload = _build_samples_payload(jsonl_path=jsonl_path, target_size=sample_size)
        samples_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write samples.json: %s", str(exc)[:200])
        return False


def _build_file_type_stats(by_type: dict[str, int], bytes_by_type: dict[str, int]) -> list[dict[str, Any]]:
    stats = [
        {
            "file_type": str(file_type or "unknown"),
            "count": int(count or 0),
            "total_size_bytes": int(bytes_by_type.get(str(file_type or "unknown"), 0) or 0),
        }
        for file_type, count in by_type.items()
    ]
    stats.sort(
        key=lambda o: (
            -int(o.get("count") or 0),
            -int(o.get("total_size_bytes") or 0),
            str(o.get("file_type") or ""),
        )
    )
    return stats[:500]


def _build_language_mix(language_counts: Counter[str]) -> dict[str, int]:
    return {bucket: int(language_counts.get(bucket, 0) or 0) for bucket in ("zh", "en", "mixed", "unknown")}


def _build_directory_items(directory_stats: dict[str, dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path, entry in directory_stats.items():
        if not isinstance(entry, dict):
            continue
        item = {
            "path": str(entry.get("path") or path or "."),
            "total_files": int(entry.get("total_files") or 0),
            "total_size_bytes": int(entry.get("total_size_bytes") or 0),
            "risky_files": int(entry.get("risky_files") or 0),
            "findings": entry.get("findings") if isinstance(entry.get("findings"), dict) else {},
        }
        if len(item["path"]) > 512:
            item["path"] = item["path"][:512]
        items.append(item)
    items.sort(
        key=lambda o: (
            -int(o.get("risky_files") or 0),
            -int(o.get("total_files") or 0),
            str(o.get("path") or ""),
        )
    )
    return items[: int(limit)] if int(limit or 0) > 0 else []


def _build_scan_summary(
    *,
    dataset_id: UUID,
    run_id: UUID,
    dataset_metadata: dict[str, Any],
    state: _ScanAccumulator,
    options: _ScanOptions,
    near_dup_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    state.file_sizes.sort()
    state.text_lengths.sort()
    state.token_lengths.sort()
    language_mix = _build_language_mix(state.language_counts)
    return {
        "dataset_id": str(dataset_id),
        "scan_run_id": str(run_id),
        "generated_at": _now_utc().isoformat(),
        "schema_id": "mimirq.dataset_precheck_summary.v3",
        "schema_version": 3,
        "total_files": int(len(state.file_sizes)),
        "total_size_bytes": int(sum(state.file_sizes)),
        "reused_files": int(state.reused_files),
        "by_file_type": {k: int(v) for k, v in sorted(state.by_type.items(), key=lambda kv: (-kv[1], kv[0]))},
        "by_file_type_bytes": {
            k: int(v)
            for k, v in sorted(
                state.bytes_by_type.items(),
                key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")),
            )
            if int(v or 0) > 0
        },
        "file_type_stats": _build_file_type_stats(state.by_type, state.bytes_by_type),
        "language_mix": language_mix,
        "embedding_advisories": build_embedding_language_advisories(
            language_mix=language_mix,
            dataset_metadata=dataset_metadata,
        ),
        "directory_stats": _build_directory_items(state.directory_stats, limit=options.directory_stats_limit),
        "file_size_histogram": histogram(state.file_sizes, FILE_SIZE_BINS),
        "length_percentiles": {
            "p25": percentile_from_sorted(state.text_lengths, 25),
            "p50": percentile_from_sorted(state.text_lengths, 50),
            "p75": percentile_from_sorted(state.text_lengths, 75),
            "p90": percentile_from_sorted(state.text_lengths, 90),
            "p99": percentile_from_sorted(state.text_lengths, 99),
        },
        "length_histogram": histogram(state.text_lengths, TEXT_LENGTH_BINS),
        "token_percentiles": {
            "p25": percentile_from_sorted(state.token_lengths, 25),
            "p50": percentile_from_sorted(state.token_lengths, 50),
            "p75": percentile_from_sorted(state.token_lengths, 75),
            "p90": percentile_from_sorted(state.token_lengths, 90),
            "p99": percentile_from_sorted(state.token_lengths, 99),
        },
        "token_histogram": histogram(state.token_lengths, TEXT_TOKEN_BINS),
        "pdf_scan": {
            "scanned": int(state.pdf_scanned),
            "not_scanned": int(state.pdf_not_scanned),
            "unknown": int(state.pdf_unknown),
        },
        "pdf_detection": {
            "sample_pages": int(options.pdf_sample_pages),
            "scan_max_chars_per_page": int(options.pdf_scan_max_chars),
            "text_min_chars_per_page": int(options.pdf_text_min_chars),
            "scan_ratio_threshold": float(options.pdf_scan_ratio_threshold),
        },
        "risk_buckets": {
            k: int(v)
            for k, v in sorted(
                state.risk_bucket_counts.items(),
                key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")),
            )
            if int(v or 0) > 0
        },
        "primary_tag_counts": {
            k: int(v)
            for k, v in sorted(
                state.primary_tag_counts.items(),
                key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")),
            )
            if int(v or 0) > 0
        },
        "processing_path_counts": {
            k: int(v)
            for k, v in sorted(
                state.processing_path_counts.items(),
                key=lambda kv: (-int(kv[1] or 0), str(kv[0] or "")),
            )
            if int(v or 0) > 0
        },
        "near_dup_summary": summarize_near_dup_payload(near_dup_payload),
        "pii_hits_total": {k: int(v) for k, v in state.pii_totals.items()},
        "secrets_hits_total": {k: int(v) for k, v in state.secrets_totals.items()},
        "findings": [
            {
                "key": k,
                "label": v.get("label", k),
                "severity": v.get("severity", "info"),
                "count": int(state.finding_counts.get(k, 0) or 0),
                "description": v.get("description"),
            }
            for k, v in FINDING_KEY_REASONS.items()
        ],
    }


def _finalize_scan_run(
    db: Session,
    *,
    run: DBDatasetPrecheckScanRun,
    root: Path,
    options: _ScanOptions,
    jsonl_path: Path,
    samples_path: Path,
    near_dup_path: Path | None,
    samples_written: bool,
    summary: dict[str, Any],
    cancelled: bool,
) -> None:
    if not cancelled:
        run.status = "completed"
        run.progress = 100
    run.finished_at = _now_utc()
    run.updated_at = run.finished_at
    run.summary = summary
    run.artifacts = {
        "files_jsonl": str(jsonl_path),
        "root_path": REDACTED_MASK if options.redact_paths else str(root),
    }
    if near_dup_path is not None:
        run.artifacts["near_dups_json"] = str(near_dup_path)
    if samples_written:
        run.artifacts["samples_json"] = str(samples_path)
    db.commit()


def _parse_reuse_scan_run_id(cfg: dict[str, Any]) -> UUID | None:
    raw_reuse_id = cfg.get("reuse_from_scan_run_id")
    if not raw_reuse_id:
        return None
    try:
        return UUID(str(raw_reuse_id))
    except Exception:
        return None


def _validate_scan_root(*, cfg: dict[str, Any], root_path: str) -> Path:
    if not root_path:
        raise ValueError("root_path_required")
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError("root_path_not_found")
    if not _is_local_scan_allowed_for_root(cfg=cfg, root=root):
        raise ValueError("local_scan_disabled")
    _assert_scan_root_allowed(root)
    return root


def _complete_empty_scan_run(
    db: Session,
    *,
    run: DBDatasetPrecheckScanRun,
    dataset_id: UUID,
    root: Path,
    options: _ScanOptions,
    jsonl_path: Path,
) -> dict[str, Any]:
    run.status = "completed"
    run.progress = 100
    run.finished_at = _now_utc()
    run.summary = _build_empty_scan_summary(
        dataset_id=dataset_id,
        scan_run_id=run.id,
        generated_at=run.finished_at,
        pdf_sample_pages=options.pdf_sample_pages,
        pdf_scan_max_chars=options.pdf_scan_max_chars,
        pdf_text_min_chars=options.pdf_text_min_chars,
        pdf_scan_ratio_threshold=options.pdf_scan_ratio_threshold,
    )
    run.artifacts = {
        "files_jsonl": str(jsonl_path),
        "root_path": REDACTED_MASK if options.redact_paths else str(root),
    }
    db.commit()
    return {"ok": True, "files": 0}


def _scan_candidates_to_jsonl(
    *,
    jsonl_path: Path,
    candidates: list[Path],
    root: Path,
    prev_records: dict[str, dict[str, Any]],
    state: _ScanAccumulator,
    options: _ScanOptions,
    flush_progress: Any,
) -> None:
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for idx, path in enumerate(candidates, start=1):
            if state.cancelled:
                return
            _process_candidate(
                path,
                idx=idx,
                root=root,
                prev_records=prev_records,
                state=state,
                options=options,
                jf=jf,
                flush_progress=flush_progress,
            )


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
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
                continue
            # Ensure the resolved path stays within the scan root to prevent symlink escape.
            try:
                path.resolve(strict=False).relative_to(root_resolved)
            except Exception:
                get_logger(__name__).debug(NON_CRITICAL_EXCEPTION_LOG_MESSAGE, exc_info=True)
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

    dataset_metadata_raw = (
        db.query(DBDataset.dataset_metadata)
        .filter(DBDataset.id == dataset_id, DBDataset.tenant_id == tenant_id)
        .scalar()
    )
    dataset_metadata = dict(dataset_metadata_raw) if isinstance(dataset_metadata_raw, dict) else {}
    _mark_run_running(db, run)

    cfg = dict(getattr(run, "config", None) or {})
    options = _build_scan_options(cfg=cfg)
    root = _validate_scan_root(cfg=cfg, root_path=options.root_path)
    reuse_from_scan_run_id = _parse_reuse_scan_run_id(cfg)

    _artifact_root, jsonl_path, samples_path, near_dups_path = _prepare_artifact_paths(
        tenant_id=tenant_id,
        scan_run_id=run.id,
    )
    candidates, candidate_type_counts = _collect_scan_candidates(
        root=root,
        allowed_exts=options.allowed_exts,
        max_files=options.max_files,
        max_total_bytes=options.max_total_bytes,
    )
    total = len(candidates)
    sample_size = _resolve_precheck_sample_target(
        total_files=total,
        file_type_counts=candidate_type_counts,
        requested_size=options.sample_size_override,
    )
    if total == 0:
        return _complete_empty_scan_run(
            db,
            run=run,
            dataset_id=dataset_id,
            root=root,
            options=options,
            jsonl_path=jsonl_path,
        )

    state = _ScanAccumulator()
    prev_records = _load_previous_records(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        options=options,
        reuse_from_scan_run_id=reuse_from_scan_run_id,
    )

    last_progress_write = time.monotonic()

    def flush_progress(processed: int, *, force: bool = False) -> None:
        nonlocal last_progress_write
        now = time.monotonic()
        if not force and (now - last_progress_write) < 0.5:
            return
        last_progress_write = now
        run.progress = max(0, min(100, int((processed / max(1, total)) * 100)))
        run.updated_at = _now_utc()
        db.commit()
        try:
            db.refresh(run)
            if str(getattr(run, "status", "") or "").lower() == "cancelled":
                state.cancelled = True
        except Exception as exc:
            logger.debug(_PRECHECK_RUNNER_FALLBACK_LOG_MESSAGE, exc)

    _scan_candidates_to_jsonl(
        jsonl_path=jsonl_path,
        candidates=candidates,
        root=root,
        prev_records=prev_records,
        state=state,
        options=options,
        flush_progress=flush_progress,
    )

    if state.cancelled:
        run.status = "cancelled"
    if options.compute_file_hash:
        exact_dup_total = _count_exact_duplicates(state.sha_counts)
        if exact_dup_total > 0:
            state.finding_counts["exact_dup"] = int(exact_dup_total)

    near_dup_payload, near_dup_path = _build_near_dup_artifact(
        state=state,
        options=options,
        near_dup_path=near_dups_path.resolve(strict=False),
    )
    samples_written = _maybe_write_samples_artifact(
        jsonl_path=jsonl_path,
        samples_path=samples_path,
        enable_sampling=options.enable_sampling,
        sample_size=sample_size,
    )
    summary = _build_scan_summary(
        dataset_id=dataset_id,
        run_id=run.id,
        dataset_metadata=dataset_metadata,
        state=state,
        options=options,
        near_dup_payload=near_dup_payload,
    )
    _finalize_scan_run(
        db,
        run=run,
        root=root,
        options=options,
        jsonl_path=jsonl_path,
        samples_path=samples_path,
        near_dup_path=near_dup_path,
        samples_written=samples_written,
        summary=summary,
        cancelled=state.cancelled,
    )
    return {"ok": True, "files": int(total), "errors": int(state.errors), "reused": int(state.reused_files)}

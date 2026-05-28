"""
Governance diagnostics (best-effort issue detection + suggestions).

This module is used by preview tooling (e.g. /pipeline/clean-preview) to surface:
- common artifacts from HTML->MD and PDF->MD conversions
- actionable suggestions to tune governance options

It must be safe and fast:
- Operates on a bounded prefix of text.
- Uses conservative heuristics (no heavy NLP).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.rag.core.logging import get_logger
from app.rag.preprocessing.cleaning import build_repeated_line_signatures
from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only

_HTML_TAG_RE = re.compile(r"<[^>]{1,200}>")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK_RE = re.compile(r"(?m)(?P<a>[A-Za-z])-\n(?P<b>[A-Za-z])")
_MD_TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
_TRACKING_PARAM_RE = re.compile(r"(?i)[?&](utm_[a-z0-9_]+|gclid|fbclid|mc_cid|mc_eid)=")
_URL_RE = re.compile(r"(?i)\bhttps?://[^\s)>\"]+")
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")

_ALNUM_CJK_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]")
logger = get_logger(__name__)


@dataclass(frozen=True)
class GovernanceIssue:
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    count: int = 0
    samples: list[str] | None = None
    suggested_pipeline_patch: dict[str, Any] | None = None


def _clip_samples(samples: list[str], *, limit: int = 5, max_len: int = 160) -> list[str]:
    out: list[str] = []
    for s in samples[: max(0, int(limit))]:
        val = (s or "").strip()
        if not val:
            continue
        out.append(val[:max_len])
    return out


def _line_stats(text: str) -> tuple[int, float, float, float]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return 0, 0.0, 0.0, 0.0
    lengths = [len(ln) for ln in lines]
    n = len(lengths)
    avg = sum(lengths) / max(1, n)
    short_ratio = sum(1 for x in lengths if x <= 80) / max(1, n)
    very_short_ratio = sum(1 for x in lengths if x <= 40) / max(1, n)
    return n, float(avg), float(short_ratio), float(very_short_ratio)


def _density(text: str) -> float:
    raw = text or ""
    non_space = sum(1 for ch in raw if not ch.isspace())
    if non_space <= 0:
        return 0.0
    alnum = len(_ALNUM_CJK_RE.findall(raw))
    return float(alnum / non_space)


def analyze_governance(
    before: str,
    after: str,
    *,
    input_format: str = "markdown",
    options: dict[str, Any] | None = None,
    max_chars: int = 200_000,
) -> tuple[list[GovernanceIssue], dict[str, Any]]:
    """
    Analyze text for common governance problems and return (issues, suggested_pipeline_patch).

    - before/after: best-effort; many heuristics look at `before` only, but some compare with `after`.
    - options: CleanPreviewRequest-like flags (unwrap_lines/remove_common_lines/etc) used to avoid suggesting
      actions that are already enabled.
    """
    opts = options or {}
    raw_before = (before or "")[: max(0, int(max_chars))]
    raw_after = (after or "")[: max(0, int(max_chars))]

    issues: list[GovernanceIssue] = []
    patch: dict[str, Any] = {}

    # 1) HTML artifacts present in "markdown" mode
    if str(input_format or "markdown").lower() != "html":
        html_hits = _HTML_TAG_RE.findall(raw_before)
        if len(html_hits) >= 3:
            samples = _clip_samples(html_hits, limit=3)
            issues.append(
                GovernanceIssue(
                    code="html_tags_present",
                    severity="warning",
                    message="检测到 HTML 标签残留：建议使用 HTML 输入格式并配合 XPath 提取正文，或在解析阶段选择更适合的网页解析器。",
                    count=len(html_hits),
                    samples=samples,
                    suggested_pipeline_patch={},
                )
            )

    # 2) Control chars
    ctrl_hits = _CONTROL_CHARS_RE.findall(raw_before)
    if ctrl_hits:
        issues.append(
            GovernanceIssue(
                code="control_chars",
                severity="error",
                message="检测到控制字符，可能影响切块与检索质量。",
                count=len(ctrl_hits),
                samples=[],
                suggested_pipeline_patch={},
            )
        )

    # 3) PDF soft line breaks (line-wrapped paragraphs)
    lines_n, avg_len, short_ratio, very_short_ratio = _line_stats(raw_before)
    if lines_n >= 80 and avg_len < 90 and short_ratio > 0.75 and very_short_ratio < 0.55:
        if not bool(opts.get("unwrap_lines", True)):
            patch["governance_unwrap_lines"] = True
        issues.append(
            GovernanceIssue(
                code="pdf_soft_line_breaks",
                severity="warning",
                message="疑似 PDF 导出导致的段落断行：建议开启“合并软换行”。",
                count=lines_n,
                samples=[],
                suggested_pipeline_patch={"governance_unwrap_lines": True} if not bool(opts.get("unwrap_lines", True)) else {},
            )
        )

    # 4) Hyphenation breaks (exam-\\nple)
    hyphen_breaks = list(_HYPHEN_BREAK_RE.finditer(raw_before))
    if len(hyphen_breaks) >= 5:
        if not bool(opts.get("unwrap_lines", True)):
            patch["governance_unwrap_lines"] = True
        issues.append(
            GovernanceIssue(
                code="pdf_hyphenation_breaks",
                severity="info",
                message="检测到较多断字连字符（'-\\n'）：合并软换行/去连字符可改善连贯性。",
                count=len(hyphen_breaks),
                samples=[],
                suggested_pipeline_patch={"governance_unwrap_lines": True} if not bool(opts.get("unwrap_lines", True)) else {},
            )
        )

    # 5) Repeated lines (headers/footers)
    repeated = sorted(build_repeated_line_signatures(raw_before, min_occurrences=3, max_line_length=120))
    if repeated:
        if not bool(opts.get("remove_common_lines", True)):
            patch["governance_remove_common_lines"] = True
        issues.append(
            GovernanceIssue(
                code="repeated_lines",
                severity="warning",
                message="检测到跨页重复行（疑似页眉/页脚/水印）：建议开启“去重页眉页脚”。",
                count=len(repeated),
                samples=_clip_samples(repeated, limit=5),
                suggested_pipeline_patch={"governance_remove_common_lines": True} if not bool(opts.get("remove_common_lines", True)) else {},
            )
        )

    # 6) Markdown tables (normalize)
    table_rows = _MD_TABLE_ROW_RE.findall(raw_before)
    if len(table_rows) >= 20 and not bool(opts.get("normalize_tables", False)):
        patch["governance_normalize_tables"] = True
        issues.append(
            GovernanceIssue(
                code="tables_detected",
                severity="info",
                message="检测到较多 Markdown 表格：建议开启“规范化表格”。",
                count=len(table_rows),
                samples=[],
                suggested_pipeline_patch={"governance_normalize_tables": True},
            )
        )

    # 7) URL tracking params
    urls = _URL_RE.findall(raw_before)
    tracking = sum(1 for u in urls if _TRACKING_PARAM_RE.search(u))
    if tracking >= 3 and not bool(opts.get("normalize_urls", False)):
        patch["governance_normalize_urls"] = True
        patch["governance_normalize_urls_strip_tracking"] = True
        issues.append(
            GovernanceIssue(
                code="tracking_urls",
                severity="info",
                message="检测到带追踪参数的 URL：建议开启“规范化 URL（去追踪参）”。",
                count=int(tracking),
                samples=[],
                suggested_pipeline_patch={
                    "governance_normalize_urls": True,
                    "governance_normalize_urls_strip_tracking": True,
                },
            )
        )

    # 8) Images
    images = _MD_IMAGE_RE.findall(raw_before)
    if len(images) >= 8 and str(opts.get("remove_images", "none")).strip().lower() == "none":
        patch["governance_remove_images"] = "decorative"
        issues.append(
            GovernanceIssue(
                code="many_images",
                severity="info",
                message="检测到较多图片引用：可考虑移除装饰性图片以降低噪声。",
                count=len(images),
                samples=[],
                suggested_pipeline_patch={"governance_remove_images": "decorative"},
            )
        )

    # 9) Would-drop signals (outline-only / low-density) as warnings when filters are OFF.
    try:
        outline_decision = drop_if_outline_only(
            raw_before,
            min_content_chars=int(opts.get("drop_outline_min_content_chars", 200) or 200),
            max_heading_ratio=float(opts.get("drop_outline_max_heading_ratio", 0.85) or 0.85),
        )
        if outline_decision.dropped and not bool(opts.get("drop_outline_only", False)):
            patch["governance_drop_outline_only"] = True
            issues.append(
                GovernanceIssue(
                    code="outline_only_risk",
                    severity="warning",
                    message="疑似大纲/目录型文档（正文密度偏低）：可考虑开启“丢弃大纲文档”。",
                    count=0,
                    samples=[],
                    suggested_pipeline_patch={"governance_drop_outline_only": True},
                )
            )
    except Exception as exc:
        logger.debug("Ignoring non-critical governance diagnostics fallback failure: %s", exc)

    try:
        low_density_decision = drop_if_low_density(raw_before, threshold=float(opts.get("drop_low_density_threshold", 0.12) or 0.12))
        if low_density_decision.dropped and not bool(opts.get("drop_low_density", False)):
            patch["governance_drop_low_density"] = True
            issues.append(
                GovernanceIssue(
                    code="low_density_risk",
                    severity="warning",
                    message=f"疑似乱码/低密度文本（density={_density(raw_before):.3f}）：可考虑开启“丢弃低密度文本”。",
                    count=0,
                    samples=[],
                    suggested_pipeline_patch={"governance_drop_low_density": True},
                )
            )
    except Exception as exc:
        logger.debug("Ignoring non-critical governance diagnostics fallback failure: %s", exc)

    # If after-clean still has very low density, surface it.
    if raw_after and _density(raw_after) < 0.08:
        issues.append(
            GovernanceIssue(
                code="low_density_after_clean",
                severity="warning",
                message=f"清洗后文本密度仍偏低（density={_density(raw_after):.3f}）：建议检查解析器/是否为扫描件。",
                count=0,
                samples=[],
                suggested_pipeline_patch={},
            )
        )

    # Merge issue-level patches into one patch (best-effort, last wins).
    for it in issues:
        if it.suggested_pipeline_patch:
            patch.update(dict(it.suggested_pipeline_patch))

    return issues, patch

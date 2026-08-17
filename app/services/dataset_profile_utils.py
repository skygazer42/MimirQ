"""
Dataset profile helpers (aggregation utils).

Keep this module pure and dependency-free so it can be used from:
- API endpoints (real-time summary)
- background jobs (deep scan runs)
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


def safe_int(value: object, *, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(default)
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return int(default)


def safe_float(value: object, *, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        if isinstance(value, bool):
            return float(default)
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)


def safe_bool(value: object, *, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def percentile_from_sorted(sorted_values: Sequence[int], p: int) -> int:
    if not sorted_values:
        return 0
    pp = max(0, min(100, int(p)))
    pos = int((pp / 100.0) * (len(sorted_values) - 1))
    pos = max(0, min(len(sorted_values) - 1, pos))
    return int(sorted_values[pos] or 0)


@dataclass(frozen=True)
class HistogramBinSpec:
    label: str
    min: int | None = None
    max: int | None = None

    def contains(self, value: int) -> bool:
        v = int(value or 0)
        if self.min is not None and v < int(self.min):
            return False
        if self.max is not None and v >= int(self.max):
            return False
        return True


def histogram(values: Iterable[int], bins: list[HistogramBinSpec]) -> list[dict]:
    specs = list(bins or [])
    counts = [0 for _ in specs]
    for raw in values:
        v = int(raw or 0)
        for i, spec in enumerate(specs):
            if spec.contains(v):
                counts[i] += 1
                break
    out: list[dict] = []
    for spec, count in zip(specs, counts, strict=False):
        out.append({"label": spec.label, "min": spec.min, "max": spec.max, "count": int(count)})
    return out


# Default bins (v1): tune later based on real customer corpora.
TEXT_LENGTH_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-500", 0, 500),
    HistogramBinSpec("500-2k", 500, 2_000),
    HistogramBinSpec("2k-10k", 2_000, 10_000),
    HistogramBinSpec("10k-50k", 10_000, 50_000),
    HistogramBinSpec("50k+", 50_000, None),
]

# Best-effort token-length bins for precheck reports (rough cost proxy).
TEXT_TOKEN_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-200", 0, 200),
    HistogramBinSpec("200-1k", 200, 1_000),
    HistogramBinSpec("1k-5k", 1_000, 5_000),
    HistogramBinSpec("5k-20k", 5_000, 20_000),
    HistogramBinSpec("20k+", 20_000, None),
]

FILE_SIZE_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-100KB", 0, 100 * 1024),
    HistogramBinSpec("100KB-1MB", 100 * 1024, 1 * 1024 * 1024),
    HistogramBinSpec("1-5MB", 1 * 1024 * 1024, 5 * 1024 * 1024),
    HistogramBinSpec("5-20MB", 5 * 1024 * 1024, 20 * 1024 * 1024),
    HistogramBinSpec("20MB+", 20 * 1024 * 1024, None),
]

PAGE_COUNT_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("1-2", 1, 3),
    HistogramBinSpec("3-5", 3, 6),
    HistogramBinSpec("6-10", 6, 11),
    HistogramBinSpec("11-25", 11, 26),
    HistogramBinSpec("26-50", 26, 51),
    HistogramBinSpec("50+", 51, None),
]

# Chunk-level proxies derived from per-document stats:
# - chunk_count: number of chunks per document
# - avg_chunk_chars: approximate avg chunk length = total_characters / chunk_count
CHUNK_COUNT_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("1-5", 1, 6),
    HistogramBinSpec("6-10", 6, 11),
    HistogramBinSpec("11-20", 11, 21),
    HistogramBinSpec("21-50", 21, 51),
    HistogramBinSpec("51-100", 51, 101),
    HistogramBinSpec("100+", 101, None),
]

AVG_CHUNK_CHARS_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-200", 0, 200),
    HistogramBinSpec("200-500", 200, 500),
    HistogramBinSpec("500-800", 500, 800),
    HistogramBinSpec("800-1.2k", 800, 1_200),
    HistogramBinSpec("1.2k-2k", 1_200, 2_000),
    HistogramBinSpec("2k+", 2_000, None),
]

# Chunk length bins (per-chunk distribution). Keep aligned with AVG_CHUNK_CHARS_BINS for now so
# charts are comparable (doc-level proxy vs real chunk-level).
CHUNK_LENGTH_BINS: list[HistogramBinSpec] = list(AVG_CHUNK_CHARS_BINS)

# Token-length bins for chunk-level stats (used by chunk preview + ingest-time token stats).
# Note: This is intentionally coarse; tune later based on real corpora.
CHUNK_TOKEN_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-50", 0, 50),
    HistogramBinSpec("50-100", 50, 100),
    HistogramBinSpec("100-200", 100, 200),
    HistogramBinSpec("200-400", 200, 400),
    HistogramBinSpec("400-800", 400, 800),
    HistogramBinSpec("800+", 800, None),
]

# Doc-level proxy: average tokens per chunk (derived from ingest-time token stats).
AVG_CHUNK_TOKENS_BINS: list[HistogramBinSpec] = list(CHUNK_TOKEN_BINS)

# Chunk coverage / overlap waste distributions (percentage points).
# These are computed from ingest-time `chunk_coverage.*_ratio` values multiplied by 100.
COVERAGE_PCT_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-50%", 0, 50),
    HistogramBinSpec("50-80%", 50, 80),
    HistogramBinSpec("80-90%", 80, 90),
    HistogramBinSpec("90-98%", 90, 98),
    HistogramBinSpec("98-100%", 98, 101),  # include 100
]

OVERLAP_WASTE_PCT_BINS: list[HistogramBinSpec] = [
    HistogramBinSpec("0-10%", 0, 10),
    HistogramBinSpec("10-20%", 10, 20),
    HistogramBinSpec("20-35%", 20, 35),
    HistogramBinSpec("35-60%", 35, 60),
    HistogramBinSpec("60%+", 60, None),
]


def _as_pct(numerator: int, denominator: int) -> int:
    den = int(max(0, denominator))
    if den <= 0:
        return 0
    num = int(max(0, numerator))
    return int(round((num / den) * 100.0))


def _risk_severity(*, pct: int, warn: int, error: int) -> str | None:
    if int(pct) >= int(error):
        return "error"
    if int(pct) >= int(warn):
        return "warning"
    return None


def build_recall_risk_hints(
    *,
    total_documents: int,
    chunk_token_bins_by_label: dict[str, int] | None,
    chunk_token_total: int,
    duplicate_like_docs: int,
    low_density_docs: int,
    parse_low_quality_docs: int,
) -> list[dict[str, Any]]:
    """
    Build non-blocking recall-risk hints from dataset-profile aggregates.

    The heuristics are intentionally lightweight and deterministic:
    - short-chunk ratio from token histogram
    - duplicate-like document ratio from chunk_quality_gate reason codes
    - low text quality ratio from existing low-density/parse-quality counters
    """

    hints: list[dict[str, Any]] = []
    total_docs = int(max(0, total_documents))
    token_total = int(max(0, chunk_token_total))
    by_label = dict(chunk_token_bins_by_label or {})

    if token_total > 0:
        short_cnt = int(max(0, by_label.get("0-50", 0))) + int(max(0, by_label.get("50-100", 0)))
        short_pct = _as_pct(short_cnt, token_total)
        sev = _risk_severity(pct=short_pct, warn=20, error=35)
        if sev is not None:
            hints.append(
                {
                    "key": "short_chunks_heavy",
                    "label": "短 Chunk 占比偏高",
                    "severity": sev,
                    "observed": {
                        "short_chunks": int(short_cnt),
                        "total_chunks": int(token_total),
                        "short_chunk_pct": int(short_pct),
                    },
                    "target": {"short_chunk_pct_warn": 20, "short_chunk_pct_error": 35},
                    "message": f"短 chunk（<=100 tokens）占比 {short_pct}%，可能导致召回碎片化与排序不稳定。",
                    "suggestions": [
                        "提高 chunk_size 或降低切分强度，减少碎片化。",
                        "优先使用结构化切分（如 markdown_header/outline）保持语义完整度。",
                    ],
                }
            )

    if total_docs > 0:
        dup_docs = int(max(0, duplicate_like_docs))
        dup_pct = _as_pct(dup_docs, total_docs)
        sev = _risk_severity(pct=dup_pct, warn=10, error=25)
        if sev is not None:
            hints.append(
                {
                    "key": "low_lexical_diversity",
                    "label": "词汇多样性偏低（重复风险）",
                    "severity": sev,
                    "observed": {
                        "duplicate_docs": int(dup_docs),
                        "total_documents": int(total_docs),
                        "duplicate_docs_pct": int(dup_pct),
                    },
                    "target": {"duplicate_docs_pct_warn": 10, "duplicate_docs_pct_error": 25},
                    "message": f"疑似重复/低多样性文档占比 {dup_pct}%，可能压缩有效召回空间。",
                    "suggestions": [
                        "检查 chunk_quality_gate 的 duplicate 相关原因项，优先治理重复段落。",
                        "在入库链路启用重复段落去重或 near_dedup（按需）。",
                    ],
                }
            )

        quality_affected = int(max(0, low_density_docs)) + int(max(0, parse_low_quality_docs))
        # Best-effort upper bound for potentially overlapping sets.
        quality_affected = int(min(total_docs, quality_affected))
        quality_pct = _as_pct(quality_affected, total_docs)
        sev = _risk_severity(pct=quality_pct, warn=15, error=30)
        if sev is not None:
            hints.append(
                {
                    "key": "low_text_quality",
                    "label": "低文本质量占比偏高",
                    "severity": sev,
                    "observed": {
                        "affected_docs": int(quality_affected),
                        "total_documents": int(total_docs),
                        "affected_docs_pct": int(quality_pct),
                        "low_density_docs": int(max(0, low_density_docs)),
                        "parse_low_quality_docs": int(max(0, parse_low_quality_docs)),
                    },
                    "target": {"affected_docs_pct_warn": 15, "affected_docs_pct_error": 30},
                    "message": f"低密度/低解析质量文档占比 {quality_pct}%，可能影响召回覆盖和相关性。",
                    "suggestions": [
                        "优先处理扫描件/OCR 路由与低质量解析文档。",
                        "结合 dataset profile findings 做文件级回灌与重解析。",
                    ],
                }
            )

    sev_order = {"error": 2, "warning": 1, "info": 0}
    hints.sort(
        key=lambda h: (
            -int(sev_order.get(str(h.get("severity") or "warning"), 1)),
            -int(
                (h.get("observed") or {}).get("short_chunk_pct", (h.get("observed") or {}).get("duplicate_docs_pct", 0))
                or 0
            ),
            str(h.get("key") or ""),
        )
    )
    return hints[:8]

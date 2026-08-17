"""
Chunk quality gate (heuristics; best-effort).

This logic is shared across:
- chunk preview (API)
- ingest-time audit metadata
- offline evaluators

Important: This module is intentionally dependency-light and returns JSON-safe dicts.
"""

from typing import Any, Literal


def _as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or isinstance(v, bool):
            return int(default)
        return int(v)
    except Exception:
        return int(default)


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or isinstance(v, bool):
            return float(default)
        return float(v)
    except Exception:
        return float(default)


class _ChunkQualityGateAccumulator:
    def __init__(self) -> None:
        self.reason_items: list[dict[str, Any]] = []
        self.recommendations: list[str] = []
        self.patches: list[dict[str, Any]] = []

    def add_reason(
        self,
        *,
        code: str,
        severity: Literal["info", "warning", "error"],
        message: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.reason_items.append(
                {
                    "code": str(code)[:80],
                    "severity": str(severity),
                    "message": str(message)[:200],
                    "meta": dict(meta or {}),
                }
            )
        except Exception:
            return

    def add_patch(
        self,
        *,
        id: str,
        title: str,
        description: str,
        target: Literal["preview", "pipeline", "perf"],
        patch: dict[str, Any],
    ) -> None:
        if not patch:
            return
        try:
            self.patches.append(
                {
                    "id": str(id)[:80],
                    "title": str(title)[:120],
                    "description": str(description)[:400],
                    "target": str(target),
                    "patch": dict(patch),
                }
            )
        except Exception:
            return


def _bounded_overlap_target(*, chunk_size: int, ratio: float) -> int:
    target_overlap = int(round(chunk_size * ratio))
    target_overlap = max(0, min(1000, target_overlap))
    if target_overlap >= chunk_size:
        return max(0, chunk_size - 1)
    return target_overlap


def _recommend_overlap_patch(
    acc: _ChunkQualityGateAccumulator,
    *,
    chunk_size: int,
    chunk_overlap: int,
    ratio: float,
    patch_id: str,
    title: str,
    description: str,
) -> None:
    if chunk_overlap <= 0 or chunk_size <= 0:
        return
    target_overlap = _bounded_overlap_target(chunk_size=chunk_size, ratio=ratio)
    if target_overlap == chunk_overlap:
        return
    acc.add_patch(
        id=patch_id,
        title=title,
        description=description,
        target="preview",
        patch={"chunk_overlap": target_overlap},
    )


def _evaluate_coverage_signals(
    acc: _ChunkQualityGateAccumulator,
    *,
    total_characters: int,
    covered_chars: int,
    coverage_ratio: float,
    gap_count: int,
) -> None:
    if total_characters <= 0 or covered_chars <= 0:
        return
    if coverage_ratio < 0.90:
        acc.add_reason(
            code="coverage_lt_90",
            severity="error",
            message=f"coverage < 90% ({coverage_ratio:.0%})",
            meta={"coverage_ratio": coverage_ratio, "gap_count": gap_count},
        )
        acc.recommendations.append("Check parser_backend and governance settings; content may be dropped unexpectedly.")
        return
    if coverage_ratio < 0.98 or gap_count > 0:
        acc.add_reason(
            code="coverage_lt_98",
            severity="warning",
            message=f"coverage < 98% ({coverage_ratio:.0%})",
            meta={"coverage_ratio": coverage_ratio, "gap_count": gap_count},
        )
        acc.recommendations.append("Check parser/page metadata; gaps may indicate start_char/page mapping issues.")


def _evaluate_short_chunk_signals(
    acc: _ChunkQualityGateAccumulator,
    *,
    short_ratio: float,
) -> None:
    if short_ratio > 0.60:
        acc.add_reason(
            code="too_many_short_chunks",
            severity="error",
            message=f"too many short chunks ({short_ratio:.0%})",
            meta={"short_ratio": short_ratio},
        )
        acc.recommendations.append(
            "Increase chunk_size or use a structure-aware chunk_strategy (outline/markdown_header/etc.)."
        )
        return
    if short_ratio > 0.30:
        acc.add_reason(
            code="many_short_chunks",
            severity="warning",
            message=f"many short chunks ({short_ratio:.0%})",
            meta={"short_ratio": short_ratio},
        )
        acc.recommendations.append("Consider increasing chunk_size to reduce fragmentation.")


def _evaluate_duplicate_signals(
    acc: _ChunkQualityGateAccumulator,
    *,
    dup_ratio: float,
) -> None:
    if dup_ratio > 0.40:
        acc.add_reason(
            code="too_many_duplicates",
            severity="error",
            message=f"too many duplicates ({dup_ratio:.0%})",
            meta={"duplicate_ratio": dup_ratio},
        )
        acc.recommendations.append("Enable governance_drop_duplicate_paragraphs or near_dedup to reduce repetition.")
        return
    if dup_ratio > 0.15:
        acc.add_reason(
            code="many_duplicates",
            severity="warning",
            message=f"many duplicates ({dup_ratio:.0%})",
            meta={"duplicate_ratio": dup_ratio},
        )
        acc.recommendations.append("Consider enabling governance_drop_duplicate_paragraphs / near_dedup.")


def _evaluate_overlap_waste_signals(
    acc: _ChunkQualityGateAccumulator,
    *,
    waste_ratio: float,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    if waste_ratio > 0.60:
        acc.add_reason(
            code="high_overlap_waste",
            severity="warning",
            message=f"high overlap waste ({waste_ratio:.0%})",
            meta={"overlap_waste_ratio": waste_ratio},
        )
        acc.recommendations.append("Reduce chunk_overlap to lower duplicated embedding work.")
        _recommend_overlap_patch(
            acc,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            ratio=0.15,
            patch_id="reduce_overlap",
            title="Reduce overlap",
            description="High overlap waste; reduce chunk_overlap (vector cost control).",
        )
        return
    if waste_ratio > 0.35:
        acc.add_reason(
            code="overlap_waste",
            severity="warning",
            message=f"overlap waste ({waste_ratio:.0%})",
            meta={"overlap_waste_ratio": waste_ratio},
        )
        acc.recommendations.append("Consider reducing chunk_overlap (enterprise cost control).")
        _recommend_overlap_patch(
            acc,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            ratio=0.2,
            patch_id="tune_overlap",
            title="Tune overlap",
            description="Moderate overlap waste; consider lowering chunk_overlap.",
        )


def _chunk_count_patch(
    *,
    chunk_size: int,
    chunk_overlap: int,
    growth: float,
) -> dict[str, int] | None:
    if chunk_size <= 0:
        return None
    target_size = min(4000, int(round(chunk_size * growth)))
    if target_size == chunk_size:
        return None
    ratio = (chunk_overlap / chunk_size) if chunk_size > 0 else 0.2
    target_overlap = int(round(target_size * ratio))
    target_overlap = max(0, min(1000, min(target_overlap, target_size - 1)))
    return {"chunk_size": target_size, "chunk_overlap": target_overlap}


def _evaluate_chunk_count_signals(
    acc: _ChunkQualityGateAccumulator,
    *,
    total_chunks: int,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    if total_chunks > 10_000:
        acc.add_reason(code="too_many_chunks_gt_10k", severity="warning", message="too many chunks (>10k)")
        acc.recommendations.append(
            "Increase chunk_size or switch strategy; very high chunk counts hurt latency and cost."
        )
        patch = _chunk_count_patch(chunk_size=chunk_size, chunk_overlap=chunk_overlap, growth=1.5)
        if patch is not None:
            acc.add_patch(
                id="increase_chunk_size",
                title="Increase chunk_size",
                description="Chunk count is very high; increase chunk_size to reduce indexing and retrieval overhead.",
                target="preview",
                patch=patch,
            )
        return
    if total_chunks > 5_000:
        acc.add_reason(code="many_chunks_gt_5k", severity="warning", message="many chunks (>5k)")
        acc.recommendations.append("Consider increasing chunk_size to reduce chunk count.")
        patch = _chunk_count_patch(chunk_size=chunk_size, chunk_overlap=chunk_overlap, growth=1.25)
        if patch is not None:
            acc.add_patch(
                id="increase_chunk_size_light",
                title="Increase chunk_size (light)",
                description="Chunk count is high; consider increasing chunk_size.",
                target="preview",
                patch=patch,
            )


def _evaluate_original_text_signals(
    acc: _ChunkQualityGateAccumulator,
    *,
    original_text_included: bool,
    original_text_truncated: bool,
    original_text_max_chars: int,
) -> None:
    if not original_text_truncated or original_text_included:
        return
    acc.recommendations.append(
        "Original text omitted due to size; increase original_text_max_chars if you need precise highlighting."
    )
    cur_max = max(0, original_text_max_chars)
    if not cur_max or cur_max >= 2_000_000:
        return
    target_max = min(2_000_000, max(cur_max * 2, 120_000))
    if target_max == cur_max:
        return
    acc.add_patch(
        id="increase_original_text_max_chars",
        title="Increase original_text_max_chars",
        description="Original text was omitted; increase the max to enable precise highlighting.",
        target="perf",
        patch={"original_text_max_chars": int(target_max), "include_original_text": True},
    )


def _dedupe_recommendations(recommendations: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for recommendation in recommendations:
        key = (recommendation or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _gate_grade(reason_items: list[dict[str, Any]]) -> Literal["pass", "warn", "fail"]:
    if any(str(item.get("severity")) == "error" for item in reason_items):
        return "fail"
    if reason_items:
        return "warn"
    return "pass"


def compute_chunk_quality_gate(
    *,
    stats: dict[str, Any],
    total_chunks: int,
    total_characters: int,
    chunk_size: int,
    chunk_overlap: int,
    original_text_included: bool,
    original_text_truncated: bool,
    original_text_max_chars: int,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """
    Compute an enterprise-friendly chunking quality gate.

    Returns:
      - gate: { grade, reasons, reason_items[] }
      - recommendations: list[str]
      - patches: list[ { id, title, description, target, patch } ]
    """
    count = _as_int(stats.get("count"), 0) or _as_int(total_chunks, 0)
    short_count = _as_int(stats.get("short_count"), 0)
    dup_count = _as_int(stats.get("duplicate_count"), 0)

    covered_chars = _as_int(stats.get("covered_chars"), 0)
    coverage_ratio = _as_float(stats.get("coverage_ratio"), 0.0)
    waste_ratio = _as_float(stats.get("overlap_waste_ratio"), 0.0)
    gap_count = _as_int(stats.get("gap_count"), 0)

    acc = _ChunkQualityGateAccumulator()

    if count <= 0:
        acc.add_reason(code="no_chunks", severity="error", message="no chunks produced")
        acc.recommendations.append("Try a different parser_backend or chunk_strategy; check governance drop settings.")

    short_ratio = (short_count / count) if count > 0 else 0.0
    dup_ratio = (dup_count / count) if count > 0 else 0.0

    _evaluate_coverage_signals(
        acc,
        total_characters=_as_int(total_characters, 0),
        covered_chars=covered_chars,
        coverage_ratio=coverage_ratio,
        gap_count=gap_count,
    )
    _evaluate_short_chunk_signals(acc, short_ratio=short_ratio)
    _evaluate_duplicate_signals(acc, dup_ratio=dup_ratio)
    _evaluate_overlap_waste_signals(
        acc,
        waste_ratio=waste_ratio,
        chunk_size=_as_int(chunk_size, 0),
        chunk_overlap=_as_int(chunk_overlap, 0),
    )
    _evaluate_chunk_count_signals(
        acc,
        total_chunks=_as_int(total_chunks, 0),
        chunk_size=_as_int(chunk_size, 0),
        chunk_overlap=_as_int(chunk_overlap, 0),
    )
    _evaluate_original_text_signals(
        acc,
        original_text_included=bool(original_text_included),
        original_text_truncated=bool(original_text_truncated),
        original_text_max_chars=_as_int(original_text_max_chars, 0),
    )

    # Best-effort extra patch: duplicates -> suggest governance-based dedup.
    if dup_ratio > 0.15:
        acc.add_patch(
            id="enable_governance_drop_duplicate_paragraphs",
            title="Enable duplicate paragraph drop",
            description=(
                "Many duplicate chunks; consider enabling governance_drop_duplicate_paragraphs to reduce repetition."
            ),
            target="pipeline",
            patch={"governance_enabled": True, "governance_drop_duplicate_paragraphs": True},
        )

    legacy_reasons = [
        str(reason.get("message", "")).strip() for reason in acc.reason_items if str(reason.get("message", "")).strip()
    ]
    gate = {
        "grade": str(_gate_grade(acc.reason_items)),
        "reasons": legacy_reasons[:10],
        "reason_items": acc.reason_items[:10],
    }
    return gate, _dedupe_recommendations(acc.recommendations)[:10], acc.patches[:10]


__all__ = ["compute_chunk_quality_gate"]

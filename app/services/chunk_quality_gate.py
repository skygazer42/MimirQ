"""
Chunk quality gate (heuristics; best-effort).

This logic is shared across:
- chunk preview (API)
- ingest-time audit metadata
- offline evaluators

Important: This module is intentionally dependency-light and returns JSON-safe dicts.
"""


from typing import Any, Literal


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

    count = _as_int(stats.get("count"), 0) or _as_int(total_chunks, 0)
    short_count = _as_int(stats.get("short_count"), 0)
    dup_count = _as_int(stats.get("duplicate_count"), 0)

    covered_chars = _as_int(stats.get("covered_chars"), 0)
    coverage_ratio = _as_float(stats.get("coverage_ratio"), 0.0)
    waste_ratio = _as_float(stats.get("overlap_waste_ratio"), 0.0)
    gap_count = _as_int(stats.get("gap_count"), 0)

    reason_items: list[dict[str, Any]] = []
    recs: list[str] = []
    patches: list[dict[str, Any]] = []

    def _add_reason(
        *,
        code: str,
        severity: Literal["info", "warning", "error"],
        message: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        try:
            reason_items.append(
                {
                    "code": str(code)[:80],
                    "severity": str(severity),
                    "message": str(message)[:200],
                    "meta": dict(meta or {}),
                }
            )
        except Exception:
            return

    def _add_patch(
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
            patches.append(
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

    if count <= 0:
        _add_reason(code="no_chunks", severity="error", message="no chunks produced")
        recs.append("Try a different parser_backend or chunk_strategy; check governance drop settings.")

    short_ratio = (short_count / count) if count > 0 else 0.0
    dup_ratio = (dup_count / count) if count > 0 else 0.0

    # Coverage signals are only meaningful when indices look plausible.
    if _as_int(total_characters, 0) > 0 and covered_chars > 0:
        if coverage_ratio < 0.90:
            _add_reason(
                code="coverage_lt_90",
                severity="error",
                message=f"coverage < 90% ({coverage_ratio:.0%})",
                meta={"coverage_ratio": coverage_ratio, "gap_count": gap_count},
            )
            recs.append("Check parser_backend and governance settings; content may be dropped unexpectedly.")
        elif coverage_ratio < 0.98 or gap_count > 0:
            _add_reason(
                code="coverage_lt_98",
                severity="warning",
                message=f"coverage < 98% ({coverage_ratio:.0%})",
                meta={"coverage_ratio": coverage_ratio, "gap_count": gap_count},
            )
            recs.append("Check parser/page metadata; gaps may indicate start_char/page mapping issues.")

    if short_ratio > 0.60:
        _add_reason(
            code="too_many_short_chunks",
            severity="error",
            message=f"too many short chunks ({short_ratio:.0%})",
            meta={"short_ratio": short_ratio},
        )
        recs.append("Increase chunk_size or use a structure-aware chunk_strategy (outline/markdown_header/etc.).")
    elif short_ratio > 0.30:
        _add_reason(
            code="many_short_chunks",
            severity="warning",
            message=f"many short chunks ({short_ratio:.0%})",
            meta={"short_ratio": short_ratio},
        )
        recs.append("Consider increasing chunk_size to reduce fragmentation.")

    if dup_ratio > 0.40:
        _add_reason(
            code="too_many_duplicates",
            severity="error",
            message=f"too many duplicates ({dup_ratio:.0%})",
            meta={"duplicate_ratio": dup_ratio},
        )
        recs.append("Enable governance_drop_duplicate_paragraphs or near_dedup to reduce repetition.")
    elif dup_ratio > 0.15:
        _add_reason(
            code="many_duplicates",
            severity="warning",
            message=f"many duplicates ({dup_ratio:.0%})",
            meta={"duplicate_ratio": dup_ratio},
        )
        recs.append("Consider enabling governance_drop_duplicate_paragraphs / near_dedup.")

    if waste_ratio > 0.60:
        _add_reason(
            code="high_overlap_waste",
            severity="warning",
            message=f"high overlap waste ({waste_ratio:.0%})",
            meta={"overlap_waste_ratio": waste_ratio},
        )
        recs.append("Reduce chunk_overlap to lower duplicated embedding work.")
        if _as_int(chunk_overlap, 0) > 0 and _as_int(chunk_size, 0) > 0:
            target_overlap = int(round(_as_int(chunk_size, 0) * 0.15))
            target_overlap = max(0, min(1000, target_overlap))
            if target_overlap >= _as_int(chunk_size, 0):
                target_overlap = max(0, _as_int(chunk_size, 0) - 1)
            if target_overlap != _as_int(chunk_overlap, 0):
                _add_patch(
                    id="reduce_overlap",
                    title="Reduce overlap",
                    description="High overlap waste; reduce chunk_overlap (vector cost control).",
                    target="preview",
                    patch={"chunk_overlap": target_overlap},
                )
    elif waste_ratio > 0.35:
        _add_reason(
            code="overlap_waste",
            severity="warning",
            message=f"overlap waste ({waste_ratio:.0%})",
            meta={"overlap_waste_ratio": waste_ratio},
        )
        recs.append("Consider reducing chunk_overlap (enterprise cost control).")
        if _as_int(chunk_overlap, 0) > 0 and _as_int(chunk_size, 0) > 0:
            target_overlap = int(round(_as_int(chunk_size, 0) * 0.2))
            target_overlap = max(0, min(1000, target_overlap))
            if target_overlap >= _as_int(chunk_size, 0):
                target_overlap = max(0, _as_int(chunk_size, 0) - 1)
            if target_overlap != _as_int(chunk_overlap, 0):
                _add_patch(
                    id="tune_overlap",
                    title="Tune overlap",
                    description="Moderate overlap waste; consider lowering chunk_overlap.",
                    target="preview",
                    patch={"chunk_overlap": target_overlap},
                )

    if _as_int(total_chunks, 0) > 10_000:
        _add_reason(code="too_many_chunks_gt_10k", severity="warning", message="too many chunks (>10k)")
        recs.append("Increase chunk_size or switch strategy; very high chunk counts hurt latency and cost.")
        if _as_int(chunk_size, 0) > 0:
            target_size = min(4000, int(round(_as_int(chunk_size, 0) * 1.5)))
            if target_size != _as_int(chunk_size, 0):
                ratio = (_as_int(chunk_overlap, 0) / _as_int(chunk_size, 0)) if _as_int(chunk_size, 0) > 0 else 0.2
                target_overlap = int(round(target_size * ratio))
                target_overlap = max(0, min(1000, min(target_overlap, target_size - 1)))
                _add_patch(
                    id="increase_chunk_size",
                    title="Increase chunk_size",
                    description="Chunk count is very high; increase chunk_size to reduce indexing and retrieval overhead.",
                    target="preview",
                    patch={"chunk_size": target_size, "chunk_overlap": target_overlap},
                )
    elif _as_int(total_chunks, 0) > 5_000:
        _add_reason(code="many_chunks_gt_5k", severity="warning", message="many chunks (>5k)")
        recs.append("Consider increasing chunk_size to reduce chunk count.")
        if _as_int(chunk_size, 0) > 0:
            target_size = min(4000, int(round(_as_int(chunk_size, 0) * 1.25)))
            if target_size != _as_int(chunk_size, 0):
                ratio = (_as_int(chunk_overlap, 0) / _as_int(chunk_size, 0)) if _as_int(chunk_size, 0) > 0 else 0.2
                target_overlap = int(round(target_size * ratio))
                target_overlap = max(0, min(1000, min(target_overlap, target_size - 1)))
                _add_patch(
                    id="increase_chunk_size_light",
                    title="Increase chunk_size (light)",
                    description="Chunk count is high; consider increasing chunk_size.",
                    target="preview",
                    patch={"chunk_size": target_size, "chunk_overlap": target_overlap},
                )

    if bool(original_text_truncated) and not bool(original_text_included):
        recs.append("Original text omitted due to size; increase original_text_max_chars if you need precise highlighting.")
        cur_max = max(0, _as_int(original_text_max_chars, 0))
        if cur_max and cur_max < 2_000_000:
            target_max = min(2_000_000, max(cur_max * 2, 120_000))
            if target_max != cur_max:
                _add_patch(
                    id="increase_original_text_max_chars",
                    title="Increase original_text_max_chars",
                    description="Original text was omitted; increase the max to enable precise highlighting.",
                    target="perf",
                    patch={"original_text_max_chars": int(target_max), "include_original_text": True},
                )

    # Grade: fail if any error reasons, warn if any reasons, otherwise pass.
    grade: Literal["pass", "warn", "fail"] = "pass"
    if any(str(r.get("severity")) == "error" for r in reason_items):
        grade = "fail"
    elif reason_items:
        grade = "warn"

    # Deduplicate recommendations while preserving order.
    deduped: list[str] = []
    seen: set[str] = set()
    for r in recs:
        key = (r or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)

    # Best-effort extra patch: duplicates -> suggest governance-based dedup.
    if dup_ratio > 0.15:
        _add_patch(
            id="enable_governance_drop_duplicate_paragraphs",
            title="Enable duplicate paragraph drop",
            description="Many duplicate chunks; consider enabling governance_drop_duplicate_paragraphs to reduce repetition.",
            target="pipeline",
            patch={"governance_enabled": True, "governance_drop_duplicate_paragraphs": True},
        )

    legacy_reasons = [str(r.get("message", "")).strip() for r in reason_items if str(r.get("message", "")).strip()]
    gate = {
        "grade": str(grade),
        "reasons": legacy_reasons[:10],
        "reason_items": reason_items[:10],
    }
    return gate, deduped[:10], patches[:10]


__all__ = ["compute_chunk_quality_gate"]


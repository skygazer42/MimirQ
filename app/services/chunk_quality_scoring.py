"""
Chunk-level quality scoring (heuristics; best-effort).

Goal:
- Provide a lightweight per-chunk signal for "noise/boilerplate" detection.
- Keep dependency-light and JSON-safe so it can be stored in doc_metadata and used by UI/retrieval.
"""


import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.normalization import normalize_text

_PAGE_MARKER_RE = re.compile(r"(?i)^\s*page\s+\d+(?:\s+of\s+\d+)?\s*$")


def _as_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except Exception:
        return None
    if out < 0.0:
        return 0.0
    if out > 1.0:
        return 1.0
    return out


def _grade_bucket(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"good", "ok", "bad"}:
        return raw
    return "unknown"


def score_chunk_quality(text: str, *, meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Score chunk quality in [0,1] and emit a small, explainable payload.

    Output schema (JSON-safe):
      {
        "schema": "mimirq.chunk_quality.v1",
        "score": 0.0-1.0,
        "grade": "good"|"ok"|"bad",
        "labels": [..],
        "signals": {..}
      }
    """
    meta = meta or {}
    norm = normalize_text(text or "", normalize_line_endings=True, remove_control_chars=True).strip()

    labels: list[str] = []
    signals: dict[str, Any] = {}

    if not norm:
        return {
            "schema": "mimirq.chunk_quality.v1",
            "score": 0.0,
            "grade": "bad",
            "labels": ["empty"],
            "signals": {"chars": 0, "lines": 0},
        }

    chars = len(norm)
    lines = norm.count("\n") + 1
    signals["chars"] = int(chars)
    signals["lines"] = int(lines)

    letters = 0
    digits = 0
    symbols = 0
    for ch in norm:
        if ch.isalpha():
            letters += 1
            continue
        if ch.isdigit():
            digits += 1
            continue
        if ch.isspace():
            continue
        symbols += 1

    alpha_ratio = float(letters) / float(chars) if chars else 0.0
    digit_ratio = float(digits) / float(chars) if chars else 0.0
    symbol_ratio = float(symbols) / float(chars) if chars else 0.0
    signals.update(
        {
            "alpha_ratio": round(alpha_ratio, 3),
            "digit_ratio": round(digit_ratio, 3),
            "symbol_ratio": round(symbol_ratio, 3),
        }
    )

    # Boilerplate detection signals (conservative).
    boiler = remove_markdown_boilerplate(norm)
    if getattr(boiler, "changed", False):
        removed_sections = int(getattr(boiler, "removed_sections", 0) or 0)
        removed_lines = int(getattr(boiler, "removed_lines", 0) or 0)
        if removed_sections > 0 or removed_lines > 0:
            labels.append("boilerplate_removed")
        signals["boilerplate_removed_sections"] = removed_sections
        signals["boilerplate_removed_lines"] = removed_lines

    if _PAGE_MARKER_RE.match(norm):
        labels.append("boilerplate_page_marker")

    # Repetition (line-level).
    if lines >= 6:
        ln = [x.strip() for x in norm.splitlines() if x.strip()]
        if ln:
            unique = len(set(ln))
            unique_ratio = float(unique) / float(len(ln))
            signals["unique_line_ratio"] = round(unique_ratio, 3)
            if unique_ratio < 0.5:
                labels.append("repetitive_lines")

    # Score composition (multiplicative, bounded).
    score = 1.0
    if chars < 30:
        score *= 0.2
        labels.append("too_short")
    elif chars < 60:
        score *= 0.7
        labels.append("short")

    if "boilerplate_page_marker" in labels:
        score *= 0.2
    if "boilerplate_removed" in labels:
        score *= 0.5
    if "repetitive_lines" in labels:
        score *= 0.8

    if symbol_ratio > 0.35 and alpha_ratio < 0.25:
        score *= 0.6
        labels.append("noisy_symbols")

    # Clamp and grade.
    score = max(0.0, min(float(score), 1.0))
    if score >= 0.7:
        grade = "good"
    elif score >= 0.4:
        grade = "ok"
    else:
        grade = "bad"

    return {
        "schema": "mimirq.chunk_quality.v1",
        "score": round(float(score), 3),
        "grade": grade,
        "labels": labels,
        "signals": signals,
    }


def summarize_retrieved_chunk_quality(
    docs: Sequence[Any] | None,
    *,
    max_candidates: int = 20,
    max_items: int = 8,
) -> dict[str, Any] | None:
    """
    Build a bounded chunk-quality summary for retrieval traces.

    Output schema:
      {
        "schema": "mimirq.chunk_quality_trace.v1",
        "candidates_considered": int,
        "bucket_counts": {"good":..,"ok":..,"bad":..,"unknown":..},
        "score_summary": {"count":..,"avg":..,"p50":..,"p90":..},
        "top_candidates": [{"rank":..,"chunk_id":..,"grade":..,"score":..,"labels":[..]}]
      }
    """
    rows = list(docs or [])
    if not rows:
        return None

    candidates_limit = max(0, min(int(max_candidates or 0), 200))
    items_limit = max(0, min(int(max_items or 0), 32))
    if candidates_limit <= 0:
        return None

    bucket_counts: dict[str, int] = {"good": 0, "ok": 0, "bad": 0, "unknown": 0}
    top_candidates: list[dict[str, Any]] = []
    scores: list[float] = []
    considered = 0

    for idx, doc in enumerate(rows):
        if considered >= candidates_limit:
            break
        considered += 1

        meta = getattr(doc, "metadata", None)
        meta = meta if isinstance(meta, dict) else {}
        cq = meta.get("chunk_quality")
        cq = cq if isinstance(cq, dict) else {}

        grade = _grade_bucket(cq.get("grade"))
        score = _as_float_or_none(cq.get("score"))
        if score is None:
            score = _as_float_or_none(meta.get("chunk_quality_score"))
        if score is not None:
            scores.append(float(score))
        bucket_counts[grade] = int(bucket_counts.get(grade, 0) or 0) + 1

        if len(top_candidates) >= items_limit:
            continue

        labels_raw = cq.get("labels")
        labels_raw = labels_raw if isinstance(labels_raw, list) else []
        labels: list[str] = []
        for raw in labels_raw:
            text = str(raw or "").strip().lower()
            if not text or text in labels:
                continue
            labels.append(text[:48])
            if len(labels) >= 3:
                break

        chunk_id = getattr(doc, "id", None) or meta.get("chunk_id")
        entry = {
            "rank": int(idx + 1),
            "chunk_id": str(chunk_id) if chunk_id is not None else None,
            "grade": grade,
            "score": (round(float(score), 3) if score is not None else None),
            "labels": labels,
        }
        top_candidates.append(entry)

    score_summary: dict[str, Any] = {"count": 0, "avg": None, "p50": None, "p90": None}
    if scores:
        sorted_scores = sorted(float(x) for x in scores)
        n = len(sorted_scores)
        p50_idx = min(n - 1, max(0, int(0.50 * (n - 1))))
        p90_idx = min(n - 1, max(0, int(0.90 * (n - 1))))
        score_summary = {
            "count": int(n),
            "avg": round(float(sum(sorted_scores) / float(n)), 3),
            "p50": round(float(sorted_scores[p50_idx]), 3),
            "p90": round(float(sorted_scores[p90_idx]), 3),
        }

    return {
        "schema": "mimirq.chunk_quality_trace.v1",
        "candidates_considered": int(considered),
        "bucket_counts": {
            "good": int(bucket_counts.get("good", 0) or 0),
            "ok": int(bucket_counts.get("ok", 0) or 0),
            "bad": int(bucket_counts.get("bad", 0) or 0),
            "unknown": int(bucket_counts.get("unknown", 0) or 0),
        },
        "score_summary": score_summary,
        "top_candidates": top_candidates,
    }


__all__ = ["score_chunk_quality", "summarize_retrieved_chunk_quality"]

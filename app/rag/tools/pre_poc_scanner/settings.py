from __future__ import annotations

from typing import Any

from app.core.config import settings


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        out = int(value if value is not None else default)
    except Exception:
        out = int(default)
    return max(minimum, min(maximum, out))


def _coerce_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        out = float(value if value is not None else default)
    except Exception:
        out = float(default)
    return round(max(minimum, min(maximum, out)), 4)


def resolve_pre_poc_scanner_thresholds(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = dict(overrides or {})
    return {
        "schema": "mimirq.pre_poc.thresholds.v1",
        "pdf_scan_ratio_threshold": _coerce_float(
            cfg.get("pdf_scan_ratio_threshold"),
            default=float(getattr(settings, "PRECHECK_PDF_SCAN_RATIO_THRESHOLD", 0.7) or 0.7),
            minimum=0.0,
            maximum=1.0,
        ),
        "pdf_low_density_ratio_threshold": _coerce_float(
            cfg.get("pdf_low_density_ratio_threshold"),
            default=float(getattr(settings, "PRECHECK_PDF_LOW_DENSITY_RATIO_THRESHOLD", 0.3) or 0.3),
            minimum=0.0,
            maximum=1.0,
        ),
        "text_short_chars_threshold": _coerce_int(
            cfg.get("text_short_chars_threshold"),
            default=int(getattr(settings, "PRECHECK_TEXT_SHORT_CHARS_THRESHOLD", 200) or 200),
            minimum=0,
            maximum=100_000,
        ),
        "text_density_threshold": _coerce_float(
            cfg.get("text_density_threshold"),
            default=float(getattr(settings, "PRECHECK_TEXT_LOW_DENSITY_THRESHOLD", 0.12) or 0.12),
            minimum=0.0,
            maximum=1.0,
        ),
        "text_gibberish_density_threshold": _coerce_float(
            cfg.get("text_gibberish_density_threshold"),
            default=float(getattr(settings, "PRECHECK_TEXT_GIBBERISH_DENSITY_THRESHOLD", 0.06) or 0.06),
            minimum=0.0,
            maximum=1.0,
        ),
        "text_high_replacement_ratio_threshold": _coerce_float(
            cfg.get("text_high_replacement_ratio_threshold"),
            default=float(getattr(settings, "PRECHECK_TEXT_HIGH_REPLACEMENT_RATIO_THRESHOLD", 0.08) or 0.08),
            minimum=0.0,
            maximum=1.0,
        ),
        "near_dup_hamming_threshold": _coerce_int(
            cfg.get("near_dup_hamming_threshold"),
            default=int(getattr(settings, "PRECHECK_NEAR_DUP_HAMMING_THRESHOLD", 5) or 5),
            minimum=0,
            maximum=32,
        ),
        "near_dup_max_pairs": _coerce_int(
            cfg.get("near_dup_max_pairs"),
            default=int(getattr(settings, "PRECHECK_NEAR_DUP_MAX_PAIRS", 5000) or 5000),
            minimum=0,
            maximum=200_000,
        ),
        "sample_size": _coerce_int(
            cfg.get("sample_size"),
            default=int(getattr(settings, "PRECHECK_SAMPLE_SIZE", 60) or 60),
            minimum=0,
            maximum=2000,
        ),
    }


__all__ = ["resolve_pre_poc_scanner_thresholds"]


from collections.abc import Mapping
from typing import Any

from app.parsing.processors.parse_quality_schema import ParseQualityGateDecision


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_float(*values: Any) -> float | None:
    for value in values:
        out = _coerce_float(value)
        if out is not None:
            return out
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        out = _coerce_int(value)
        if out is not None:
            return out
    return None


def _low_confidence_span_count(meta: Mapping[str, Any]) -> int:
    candidates = [
        _mapping(meta.get("ocr")).get("low_confidence_spans"),
        _mapping(meta.get("ocr_quality")).get("low_confidence_spans"),
        meta.get("low_confidence_spans"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return int(len(value))
    return 0


def _table_metrics(table: Mapping[str, Any]) -> tuple[int, int]:
    rows = _first_int(table.get("row_count"), table.get("rows"))
    cols = _first_int(table.get("col_count"), table.get("cols"))
    shape = table.get("source_table_shape") or table.get("table_shape")
    if isinstance(shape, (list, tuple)) and len(shape) >= 2:
        rows = rows if rows is not None else _coerce_int(shape[0])
        cols = cols if cols is not None else _coerce_int(shape[1])
    if isinstance(shape, Mapping):
        rows = rows if rows is not None else _coerce_int(shape.get("rows") or shape.get("row_count"))
        cols = cols if cols is not None else _coerce_int(shape.get("cols") or shape.get("col_count"))
    return max(0, int(rows or 0)), max(0, int(cols or 0))


def _large_tables(
    meta: Mapping[str, Any],
    *,
    row_threshold: int,
    col_threshold: int,
) -> list[dict[str, Any]]:
    table_store = _mapping(meta.get("table_store"))
    tables = table_store.get("tables")
    if not isinstance(tables, list):
        return []

    out: list[dict[str, Any]] = []
    for index, raw in enumerate(tables):
        if not isinstance(raw, Mapping):
            continue
        rows, cols = _table_metrics(raw)
        truncated = bool(_coerce_bool(raw.get("truncated")) is True)
        if rows >= int(row_threshold) or cols >= int(col_threshold) or truncated:
            out.append(
                {
                    "index": int(index),
                    "table_id": str(raw.get("table_id") or raw.get("source_element_id") or index),
                    "row_count": int(rows),
                    "col_count": int(cols),
                    "truncated": bool(truncated),
                }
            )
    return out


def evaluate_parse_quality_gate(
    meta: Mapping[str, Any] | None,
    *,
    min_parse_score: float = 0.65,
    fail_parse_score: float = 0.55,
    min_ocr_confidence: float = 0.70,
    min_table_structure_confidence: float = 0.60,
    watermark_removed_ratio_threshold: float = 0.35,
    watermark_removed_count_threshold: int = 20,
    reading_order_unstable_min_items: int = 12,
    reading_order_unstable_min_column_pages: int = 2,
    table_tag_row_threshold: int = 5000,
    table_tag_col_threshold: int = 80,
) -> ParseQualityGateDecision:
    source = _mapping(meta)
    parse_quality = _mapping(source.get("parse_quality"))
    parsed_text_quality = _mapping(source.get("parsed_text_quality"))
    ocr = _mapping(source.get("ocr"))
    ocr_quality = _mapping(source.get("ocr_quality"))
    watermark = _mapping(source.get("watermark_removal"))
    reading_order = _mapping(source.get("reading_order_fix"))
    table_structure = _mapping(source.get("table_structure"))

    parse_score = _first_float(parse_quality.get("score"), source.get("parse_quality_score"))
    ocr_confidence = _first_float(
        ocr.get("confidence_avg"),
        ocr.get("avg_confidence"),
        ocr_quality.get("confidence_avg"),
        ocr_quality.get("avg_confidence"),
        parsed_text_quality.get("ocr_confidence_avg"),
        source.get("ocr_confidence_avg"),
        _mapping(source.get("pdf_quality")).get("ocr_confidence_avg"),
    )
    table_structure_confidence = _first_float(
        table_structure.get("confidence_avg"),
        table_structure.get("avg_confidence"),
        table_structure.get("score"),
        source.get("table_structure_confidence_avg"),
    )

    watermark_removed = max(0, int(_first_int(watermark.get("removed_count"), source.get("watermark_removed_count")) or 0))
    watermark_input = max(0, int(_first_int(watermark.get("input_count"), watermark.get("total_count"), source.get("watermark_input_count")) or 0))
    watermark_ratio = (float(watermark_removed) / float(watermark_input)) if watermark_input > 0 else None

    reading_changed = bool(_coerce_bool(reading_order.get("changed")) is True)
    reading_items = max(0, int(_first_int(reading_order.get("items"), source.get("reading_order_items")) or 0))
    reading_column_pages = max(0, int(_first_int(reading_order.get("column_pages"), source.get("reading_order_column_pages")) or 0))

    low_confidence_spans = _low_confidence_span_count(source)
    large_tables = _large_tables(
        source,
        row_threshold=int(table_tag_row_threshold),
        col_threshold=int(table_tag_col_threshold),
    )

    flags = {
        "parse_score_low": bool(parse_score is not None and float(parse_score) < float(min_parse_score)),
        "ocr_low_confidence": bool(
            (ocr_confidence is not None and float(ocr_confidence) < float(min_ocr_confidence))
            or (ocr_confidence is None and low_confidence_spans > 0)
        ),
        "table_structure_low_confidence": bool(
            table_structure_confidence is not None
            and float(table_structure_confidence) < float(min_table_structure_confidence)
        ),
        "reading_order_unstable": bool(
            reading_changed
            and (
                reading_items >= int(reading_order_unstable_min_items)
                or reading_column_pages >= int(reading_order_unstable_min_column_pages)
            )
        ),
        "noise_removal_risky": bool(
            watermark_removed > 0
            and (
                (watermark_ratio is not None and watermark_ratio >= float(watermark_removed_ratio_threshold))
                or (watermark_ratio is None and watermark_removed >= int(watermark_removed_count_threshold))
            )
        ),
        "tag_sidecar_recommended": bool(large_tables),
    }

    hard_fail = bool(
        (parse_score is not None and float(parse_score) < float(fail_parse_score))
        or (flags["ocr_low_confidence"] and flags["parse_score_low"])
    )
    if hard_fail:
        grade = "fail"
    elif any(flags.values()):
        grade = "warn"
    else:
        grade = "pass"
    needs_review = grade != "pass"
    actions = {
        "parser_fallback_recommended": bool(
            flags["parse_score_low"]
            or flags["ocr_low_confidence"]
            or flags["table_structure_low_confidence"]
            or flags["reading_order_unstable"]
        ),
        "tag_sidecar_recommended": bool(flags["tag_sidecar_recommended"]),
        "metadata_only": True,
    }
    evidence = {
        "parse_score": parse_score,
        "ocr_confidence_avg": ocr_confidence,
        "low_confidence_spans": int(low_confidence_spans),
        "table_structure_confidence_avg": table_structure_confidence,
        "watermark_removed_count": int(watermark_removed),
        "watermark_removed_ratio": (round(float(watermark_ratio), 4) if watermark_ratio is not None else None),
        "reading_order_changed": bool(reading_changed),
        "reading_order_items": int(reading_items),
        "reading_order_column_pages": int(reading_column_pages),
        "large_tables": large_tables,
    }
    thresholds = {
        "min_parse_score": float(min_parse_score),
        "fail_parse_score": float(fail_parse_score),
        "min_ocr_confidence": float(min_ocr_confidence),
        "min_table_structure_confidence": float(min_table_structure_confidence),
        "watermark_removed_ratio_threshold": float(watermark_removed_ratio_threshold),
        "watermark_removed_count_threshold": int(watermark_removed_count_threshold),
        "reading_order_unstable_min_items": int(reading_order_unstable_min_items),
        "reading_order_unstable_min_column_pages": int(reading_order_unstable_min_column_pages),
        "table_tag_row_threshold": int(table_tag_row_threshold),
        "table_tag_col_threshold": int(table_tag_col_threshold),
    }
    return ParseQualityGateDecision(
        grade=grade,
        needs_review=needs_review,
        flags=flags,
        actions=actions,
        evidence=evidence,
        thresholds=thresholds,
    )


def apply_parse_quality_gate_metadata(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(meta or {})
    decision = evaluate_parse_quality_gate(out)
    gate = decision.to_metadata()
    out["parse_quality_gate"] = gate
    out["parse_quality_flags"] = dict(gate.get("flags") or {})

    parse_quality = dict(_mapping(out.get("parse_quality")))
    parse_quality["needs_review"] = bool(gate.get("needs_review"))
    parse_quality["gate_grade"] = str(gate.get("grade") or "pass")
    parse_quality["flags"] = dict(gate.get("flags") or {})
    for key, value in dict(gate.get("flags") or {}).items():
        parse_quality[str(key)] = bool(value)
    out["parse_quality"] = parse_quality
    return out


__all__ = [
    "apply_parse_quality_gate_metadata",
    "evaluate_parse_quality_gate",
]


from collections import defaultdict
from pathlib import Path
from typing import Any

from app.parsing.quality.grits import compute_table_collection_grits, compute_table_grits

DEFAULT_FIXTURE_DIR = Path("tests/fixtures/parsing_golden_broader")
DEFAULT_MANIFEST = DEFAULT_FIXTURE_DIR / "manifest.json"


def classify_doc_type(case_row: dict[str, Any]) -> str:
    file_type = str(case_row.get("file_type") or "").strip().lower()
    case_id = str(case_row.get("id") or "").strip().lower()
    text = f"{case_id} {file_type}"
    if "qr" in text or "barcode" in text:
        return "code_image"
    if "chart" in text:
        return "chart"
    if "diagram" in text:
        return "diagram"
    if "table" in text or file_type == "xlsx":
        return "table"
    if "handwriting" in text or "scan" in text or "watermark" in text:
        return "scan_ocr"
    if "two_column" in text or "multilingual" in text or "mixed_layout" in text or "header_footer" in text:
        return "complex_layout"
    if file_type in {"docx", "md"} or "formula" in text:
        return "office_text"
    return file_type or "unknown"


def build_doc_type_matrix(report: dict[str, Any]) -> dict[str, Any]:
    rows = report.get("cases") if isinstance(report, dict) else None
    if not isinstance(rows, list):
        return {}

    buckets: dict[str, dict[str, dict[str, list[float] | int]]] = defaultdict(
        lambda: defaultdict(
            lambda: {
                "cases": 0,
                "ok": 0,
                "text_edit_similarity": [],
                "text_coverage": [],
                "table_grits_f1": [],
                "table_grits_topology": [],
                "table_grits_content": [],
                "table_continuity": [],
            }
        )
    )

    for case_row in rows:
        if not isinstance(case_row, dict):
            continue
        doc_type = classify_doc_type(case_row)
        attempts = case_row.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            backend = str(attempt.get("backend") or "").strip().lower() or "unknown"
            bucket = buckets[backend][doc_type]
            bucket["cases"] = int(bucket["cases"]) + 1
            if bool(attempt.get("ok")):
                bucket["ok"] = int(bucket["ok"]) + 1
            for key, source_key in (
                ("text_edit_similarity", "golden_similarity"),
                ("text_coverage", "golden_coverage_ratio"),
                ("table_continuity", "table_continuity_recall"),
            ):
                value = attempt.get(source_key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bucket[key].append(float(value))  # type: ignore[union-attr]
            table_grits = attempt.get("table_grits") if isinstance(attempt.get("table_grits"), dict) else {}
            for key in ("table_grits_f1", "table_grits_topology", "table_grits_content"):
                source_key = key.replace("table_grits_", "")
                value = table_grits.get(source_key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bucket[key].append(float(value))  # type: ignore[union-attr]

    matrix: dict[str, Any] = {}
    for backend, doc_type_map in sorted(buckets.items()):
        matrix[backend] = {}
        for doc_type, bucket in sorted(doc_type_map.items()):
            total = int(bucket["cases"])
            row: dict[str, Any] = {
                "cases": total,
                "ok_rate": round(float(bucket["ok"]) / float(total), 4) if total else None,
            }
            for key in (
                "text_edit_similarity",
                "text_coverage",
                "table_grits_f1",
                "table_grits_topology",
                "table_grits_content",
                "table_continuity",
            ):
                values = [float(item) for item in bucket[key]]  # type: ignore[union-attr]
                row[f"{key}_mean"] = round(sum(values) / float(len(values)), 4) if values else None
            matrix[backend][doc_type] = row
    return matrix


__all__ = [
    "DEFAULT_FIXTURE_DIR",
    "DEFAULT_MANIFEST",
    "build_doc_type_matrix",
    "classify_doc_type",
    "compute_table_collection_grits",
    "compute_table_grits",
]

"""
Precheck risk buckets.

Goal: convert low-level per-file findings into a small, explainable set of "risk buckets"
that is easier to visualize and report on.

Buckets (v3):
- ocr: likely needs OCR / stronger PDF pipeline
- garbage: likely decode/parse garbage (replacement chars, parse failed, etc.)
- low_density: low signal / noisy text extraction
- boilerplate: HTML/web scrape boilerplate prone
- table_heavy: spreadsheet-like content (often better served by structured indexing)
"""


from collections.abc import Iterable


def risk_buckets_for_file(*, file_type: str, findings: Iterable[str] | None) -> list[str]:
    ft = str(file_type or "").strip().lower()
    fset = {str(x or "").strip().lower() for x in (findings or []) if str(x or "").strip()}

    buckets: set[str] = set()

    # OCR / PDF quality.
    if ft == "pdf" and ({"pdf_scanned", "pdf_unknown"} & fset):
        buckets.add("ocr")

    # Garbage / decode failures.
    if "gibberish_text" in fset or "parse_failed" in fset:
        buckets.add("garbage")

    # Low signal density.
    if "low_density_text" in fset or "pdf_low_density" in fset:
        buckets.add("low_density")

    # Web/HTML boilerplate (navigation/headers/scripts).
    if ft in {"html", "htm"}:
        buckets.add("boilerplate")

    # Table-like / structured data.
    if ft in {"csv", "xls", "xlsx"}:
        buckets.add("table_heavy")

    return sorted(buckets)


__all__ = ["risk_buckets_for_file"]


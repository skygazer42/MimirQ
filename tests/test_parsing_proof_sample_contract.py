from __future__ import annotations

import json
from pathlib import Path


def test_parsing_proof_summary_baseline_matches_current_sample_contract() -> None:
    payload = json.loads(Path("ci/parsing_retrieval_proof_summary_baseline.v1.json").read_text(encoding="utf-8"))

    assert payload.get("schema") == "mimirq.parsing_retrieval_proof_summary.v1"
    assert payload.get("cases_total") == 12
    assert payload.get("hit_at_k_mean") == 1.0
    assert payload.get("mrr_mean") == 1.0
    assert payload.get("failed_case_ids") == []

    case_ids = [str(item.get("id") or "") for item in (payload.get("cases") or []) if isinstance(item, dict)]
    assert case_ids == [
        "chart_pdf_case",
        "line_chart_pdf_case",
        "diagram_pdf_case",
        "qr_image_case",
        "barcode_image_case",
        "cross_page_table_pdf_case",
        "borderless_table_scan_case",
        "merged_header_table_pdf_case",
        "table_with_leading_paragraph_pdf_case",
        "two_column_pdf_case",
        "header_footer_noise_pdf_case",
        "mixed_layout_pdf_case",
    ]

from __future__ import annotations

from app.services.parser_strategy_policy import recommend_parser_strategy


def test_recommend_parser_strategy_prefers_pdf_ocr_layout_for_image_heavy_pdf() -> None:
    out = recommend_parser_strategy(
        {
            "mime_type": "application/pdf",
            "file_extension": "pdf",
            "page_count": 8,
            "image_ratio": 0.72,
            "ocr_ratio": 0.4,
            "table_density": 0.05,
        }
    )
    assert out.get("schema") == "mimirq.parser_strategy_recommendation.v1"
    assert out.get("strategy") == "pdf_ocr_layout"
    assert "image_or_ocr_heavy_pdf" in list(out.get("reason_codes") or [])
    assert float(out.get("confidence") or 0.0) >= 0.85


def test_recommend_parser_strategy_prefers_pdf_text_fast_for_text_pdf() -> None:
    out = recommend_parser_strategy(
        {
            "mime_type": "application/pdf",
            "file_extension": "pdf",
            "page_count": 12,
            "image_ratio": 0.1,
            "ocr_ratio": 0.0,
            "table_density": 0.02,
            "has_tables": False,
        }
    )
    assert out.get("strategy") == "pdf_text_fast"
    assert "text_dominant_pdf" in list(out.get("reason_codes") or [])


def test_recommend_parser_strategy_handles_spreadsheet_and_fallback() -> None:
    spreadsheet = recommend_parser_strategy(
        {
            "mime_type": "text/csv",
            "file_extension": "csv",
        }
    )
    assert spreadsheet.get("strategy") == "spreadsheet_structured"

    fallback = recommend_parser_strategy(
        {
            "mime_type": "application/octet-stream",
            "file_extension": "bin",
        }
    )
    assert fallback.get("strategy") == "generic_balanced"
    assert "fallback_generic" in list(fallback.get("reason_codes") or [])


def test_recommend_parser_strategy_prefers_pdf_ocr_layout_for_low_seal_confidence() -> None:
    out = recommend_parser_strategy(
        {
            "mime_type": "application/pdf",
            "file_extension": "pdf",
            "page_count": 6,
            "image_ratio": 0.12,
            "ocr_ratio": 0.04,
            "table_density": 0.01,
            "seal_expected": True,
            "seal_confidence": 0.18,
            "seal_candidate_count": 2,
        }
    )
    assert out.get("strategy") == "pdf_ocr_layout"
    assert "low_seal_confidence" in list(out.get("reason_codes") or [])
    assert bool((out.get("parser_options") or {}).get("seal_review")) is True

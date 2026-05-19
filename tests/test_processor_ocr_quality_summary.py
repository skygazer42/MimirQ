from __future__ import annotations

from langchain_core.documents import Document


def test_build_ocr_quality_summary_aggregates_element_confidence() -> None:
    from app.parsing.processors.processor import _build_ocr_quality_summary

    summary = _build_ocr_quality_summary(
        [
            Document(
                page_content="低置信文本",
                metadata={
                    "derived_elements": [
                        {
                            "id": "e1",
                            "text": "低置信文本",
                            "page": 1,
                            "confidence": 0.52,
                            "bbox": {"x0": 1, "x1": 10, "y0": 2, "y1": 12},
                        },
                        {"id": "e2", "text": "正常文本", "page": 1, "confidence": 0.92},
                    ]
                },
            )
        ],
        low_confidence_threshold=0.7,
    )

    assert summary is not None
    assert summary["confidence_avg"] == 0.72
    assert summary["low_confidence_count"] == 1
    assert summary["low_confidence_spans"][0]["element_id"] == "e1"
    assert summary["low_confidence_spans"][0]["text"] == "低置信文本"

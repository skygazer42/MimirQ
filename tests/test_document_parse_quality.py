from __future__ import annotations

import pytest


def test_score_document_parse_quality_combines_pdf_and_text_signals():
    from app.parsing.quality.document_quality import score_document_parse_quality  # noqa: WPS433

    out = score_document_parse_quality(
        pdf_quality={"score": 0.8, "is_scanned": False},
        parsed_text_quality={"density": 0.2, "replacement_ratio": 0.0},
    )
    assert out["score"] == pytest.approx(0.62)


def test_score_document_parse_quality_uses_text_density_when_no_pdf_score():
    from app.parsing.quality.document_quality import score_document_parse_quality  # noqa: WPS433

    out = score_document_parse_quality(
        pdf_quality=None,
        parsed_text_quality={"density": 0.4, "replacement_ratio": 0.0},
    )
    assert out["score"] == pytest.approx(0.4)


def test_score_document_parse_quality_penalizes_high_replacement_ratio():
    from app.parsing.quality.document_quality import score_document_parse_quality  # noqa: WPS433

    out = score_document_parse_quality(
        pdf_quality={"score": 0.8, "is_scanned": False},
        parsed_text_quality={"density": 0.2, "replacement_ratio": 0.1},
    )
    # Base: 0.7*0.8 + 0.3*0.2 = 0.62. Penalty: min(0.5, 0.1*5) = 0.5 => 0.31.
    assert out["score"] == pytest.approx(0.31)


def test_score_document_parse_quality_penalizes_low_confidence_seal_documents():
    from app.parsing.quality.document_quality import score_document_parse_quality  # noqa: WPS433

    out = score_document_parse_quality(
        pdf_quality={"score": 0.91, "is_scanned": False},
        parsed_text_quality={"density": 0.8, "replacement_ratio": 0.0},
        specialty_signals={"seal_expected": True, "seal_confidence": 0.22, "seal_candidate_count": 2},
    )

    assert out["score"] < 0.7
    assert out["components"]["seal_confidence"] == pytest.approx(0.22)
    assert out["components"]["seal_candidate_count"] == 2

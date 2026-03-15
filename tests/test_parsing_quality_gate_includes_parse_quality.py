from __future__ import annotations

import pytest


def test_parsing_quality_gate_includes_parse_quality_score():
    from app.api.v1.parsing import _compute_parsing_quality_gate  # noqa: WPS433

    gate = _compute_parsing_quality_gate(
        "hello world",
        pdf_quality={"score": 0.8, "is_scanned": False},
        min_content_chars=0,
        is_pdf=True,
    )
    ev = gate.evidence or {}
    assert "parse_quality" in ev
    assert ev["parse_quality"]["score"] == pytest.approx(0.86)


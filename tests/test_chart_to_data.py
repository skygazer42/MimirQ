from __future__ import annotations

from pathlib import Path

import pytest


def test_add_chart_data_blocks_noops_when_backend_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.parsing.enrich.chart_to_data import add_chart_data_blocks

    monkeypatch.setattr(settings, "CHART_TO_DATA_ENABLED", False, raising=False)

    image_path = tmp_path / "chart.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nchart")
    markdown = "![chart](chart.png)"

    out_md, added, audit = add_chart_data_blocks(markdown, origin_path=tmp_path)

    assert out_md == markdown
    assert added == 0
    assert audit.applied is False
    assert audit.backend == "chart_to_data"


def test_add_chart_data_blocks_inserts_structured_payload_when_backend_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.parsing.enrich.chart_to_data import add_chart_data_blocks

    monkeypatch.setattr(settings, "CHART_TO_DATA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CHART_TO_DATA_API_URL", "http://chart.local/extract", raising=False)
    monkeypatch.setattr(
        "app.parsing.enrich.chart_to_data._call_chart_backend",
        lambda **_kwargs: (
            {
                "title": "Q1 Revenue",
                "series": [{"name": "Revenue", "points": [["Jan", 10], ["Feb", 12], ["Mar", 15]]}],
            },
            "ok_json",
        ),
    )

    image_path = tmp_path / "chart.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nchart")
    markdown = "![chart](chart.png)"

    out_md, added, audit = add_chart_data_blocks(markdown, origin_path=tmp_path)

    assert added == 1
    assert "Chart data:" in out_md
    assert '"title": "Q1 Revenue"' in out_md
    assert audit.applied is True
    assert audit.charts_added == 1

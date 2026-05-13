from __future__ import annotations

import json
from pathlib import Path

import pytest


def _extract_chart_json(markdown: str) -> dict:
    marker = "Chart data:\n```json\n"
    start = markdown.index(marker) + len(marker)
    end = markdown.index("\n```", start)
    return json.loads(markdown[start:end])


def test_chart_data_block_uses_v1_schema_and_stable_cache_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.parsing.enrich.chart_to_data import add_chart_data_blocks

    monkeypatch.setattr(settings, "CHART_TO_DATA_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "CHART_TO_DATA_API_URL", "http://chart.local/extract", raising=False)

    async def _fake_backend_async(**_kwargs):  # noqa: ANN001
        return (
            {
                "title": "Revenue Trend",
                "series": [{"name": "Revenue", "points": [["2024", 120], ["2025", 150]]}],
                "units": "CNY million",
                "confidence": 0.91,
            },
            "ok_json",
        )

    monkeypatch.setattr("app.parsing.enrich.chart_to_data._call_chart_backend_async", _fake_backend_async)

    image_path = tmp_path / "finance-chart.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfinance-chart")

    out_md, added, audit = add_chart_data_blocks(
        "![Revenue chart](finance-chart.png)",
        origin_path=tmp_path,
    )
    payload = _extract_chart_json(out_md)

    assert added == 1
    assert payload["schema"] == "mimirq.chart_data.v1"
    assert payload["chart_id"].startswith("chart_")
    assert payload["source_image"] == "finance-chart.png"
    assert payload["alt"] == "Revenue chart"
    assert payload["title"] == "Revenue Trend"
    assert payload["series"][0]["name"] == "Revenue"
    assert payload["units"] == "CNY million"
    assert payload["confidence"] == 0.91
    assert payload["cache_key"].startswith("chart_data:v1:")
    assert audit.chart_elements[0]["chart_id"] == payload["chart_id"]
    assert audit.chart_elements[0]["cache_key"] == payload["cache_key"]

import re

import pytest

from app.services.report_html import render_precheck_html


def _render(summary):
    return render_precheck_html(
        title="Precheck", dataset_name=None, dataset_id=None, root_path=None,
        generated_at=None, summary=summary,
    )


def test_precheck_report_keeps_zero_detection_thresholds_visible():
    html = _render({"pdf_detection": {
        "sample_pages": 0, "scan_max_chars_per_page": 0,
        "text_min_chars_per_page": 0, "scan_ratio_threshold": 0.0,
    }})
    cells = dict(re.findall(r'<td class="k">([^<]+)</td><td class="v">([^<]*)</td>', html))
    for field in ("sample_pages", "scan_max_chars_per_page", "text_min_chars_per_page"):
        assert cells[field] == "0"
    assert cells["scan_ratio_threshold"] == "0.0"


def test_precheck_report_exposes_a_corrupt_required_detection_field():
    with pytest.raises(KeyError, match="sample_pages"):
        _render({"pdf_detection": {}})

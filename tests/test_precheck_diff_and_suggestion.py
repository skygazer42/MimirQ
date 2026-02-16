from __future__ import annotations

import uuid

from app.services.dataset_precheck_diff import diff_precheck_summaries


def test_precheck_diff_basic():
    base_id = uuid.uuid4()
    target_id = uuid.uuid4()
    out = diff_precheck_summaries(
        base_scan_run_id=base_id,
        target_scan_run_id=target_id,
        base_summary={
            "total_files": 10,
            "total_size_bytes": 100,
            "by_file_type": {"pdf": 5, "md": 5},
            "pdf_scan": {"scanned": 2, "unknown": 1},
            "findings": [{"key": "parse_failed", "count": 1}],
        },
        target_summary={
            "total_files": 12,
            "total_size_bytes": 140,
            "by_file_type": {"pdf": 6, "md": 4, "docx": 2},
            "pdf_scan": {"scanned": 3, "unknown": 0},
            "findings": [{"key": "parse_failed", "count": 0}, {"key": "pii", "count": 2}],
        },
    )
    assert out["total_files"]["delta"] == 2
    assert out["pdf_scanned"]["delta"] == 1
    assert any(x["key"] == "docx" for x in out["by_file_type"])
    assert any(x["key"] == "pii" for x in out["findings"])

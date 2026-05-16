from __future__ import annotations

import json
from pathlib import Path


def test_precheck_sample_target_uses_ratio_and_present_types() -> None:
    from app.services.dataset_precheck_scan_runner import _resolve_precheck_sample_target

    assert (
        _resolve_precheck_sample_target(
            total_files=1000,
            file_type_counts={"pdf": 500, "xlsx": 300, "docx": 200},
            requested_size=None,
        )
        == 3
    )
    assert (
        _resolve_precheck_sample_target(
            total_files=1000,
            file_type_counts={"pdf": 400, "xlsx": 250, "docx": 200, "html": 100, "md": 50},
            requested_size=None,
        )
        == 5
    )
    assert (
        _resolve_precheck_sample_target(
            total_files=7,
            file_type_counts={"pdf": 1, "xlsx": 1, "html": 2, "md": 3},
            requested_size=None,
        )
        == 4
    )
    assert (
        _resolve_precheck_sample_target(
            total_files=7,
            file_type_counts={"pdf": 1, "xlsx": 1, "html": 2, "md": 3},
            requested_size=0,
        )
        == 0
    )


def test_precheck_samples_payload_covers_each_present_file_type(tmp_path: Path) -> None:
    from app.services.dataset_precheck_scan_runner import _build_samples_payload

    rows = [
        {"name": "a.pdf", "file_type": "pdf", "file_size": 100, "file_mtime": 1, "findings": []},
        {"name": "b.pdf", "file_type": "pdf", "file_size": 200, "file_mtime": 2, "findings": []},
        {"name": "c.xlsx", "file_type": "xlsx", "file_size": 300, "file_mtime": 3, "findings": []},
        {"name": "d.html", "file_type": "html", "file_size": 400, "file_mtime": 4, "findings": []},
        {"name": "e.md", "file_type": "md", "file_size": 500, "file_mtime": 5, "findings": []},
    ]
    jsonl = tmp_path / "files.jsonl"
    jsonl.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    payload = _build_samples_payload(jsonl_path=jsonl, target_size=1)
    representative_types = {item["file_type"] for item in payload["representative"]}

    assert payload["requested"] == 4
    assert representative_types == {"pdf", "xlsx", "html", "md"}

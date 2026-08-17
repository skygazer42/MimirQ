from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc

from app.services import dataset_precheck_scan_runner as runner


class _QueryStub:
    def __init__(self, *, run: object, dataset_metadata: object) -> None:
        self._run = run
        self._dataset_metadata = dataset_metadata

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN201
        return self._run

    def scalar(self):  # noqa: ANN201
        return self._dataset_metadata


class _FakeDB:
    def __init__(self, *, run: object, dataset_metadata: object | None = None) -> None:
        self._run = run
        self._dataset_metadata = dataset_metadata
        self.commits = 0

    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return _QueryStub(run=self._run, dataset_metadata=self._dataset_metadata)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _run: object) -> None:
        return None


def _write_jsonl(path: Path, rows: list[object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write("not-json\n")
        handle.write("[]\n")
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def test_build_samples_payload_preserves_type_coverage_and_review_sorting(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "files.jsonl"
    rows = [
        {"name": "a.pdf", "file_type": "pdf", "file_size": 400, "pdf_scanned": True, "text_characters": 20, "findings": ["pdf_scanned"]},
        {"name": "b.txt", "file_type": "txt", "file_size": 500, "text_characters": 300, "findings": ["pii"]},
        {"name": "c.csv", "file_type": "csv", "file_size": 700, "text_characters": 120, "findings": ["large_spreadsheet"]},
        {"name": "d.md", "file_type": "md", "file_size": 100, "text_characters": 50, "findings": []},
        {"name": "e.txt", "file_type": "txt", "file_size": 900, "text_characters": 900, "findings": ["pii", "short_text"]},
    ]
    _write_jsonl(jsonl_path, rows)

    payload = runner._build_samples_payload(jsonl_path=jsonl_path, target_size=2)

    assert payload["requested"] == 4
    assert payload["strata_count"] == 4
    assert {item["file_type"] for item in payload["representative"]} == {"pdf", "txt", "csv", "md"}
    assert [item["name"] for item in payload["needs_review"]["pii"]] == ["e.txt"]
    assert [item["file_size"] for item in payload["top_large_files"][:3]] == [900, 700, 500]
    assert [item["text_characters"] for item in payload["top_long_text"][:2]] == [900, 300]


def test_xlsx_spreadsheet_stats_uses_first_sheet_merges_and_closes_workbook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Range:
        def __init__(self, size: int) -> None:
            self.size = size

    class _Sheet:
        def __init__(self, *, max_row: int, max_column: int, merged_sizes: list[int]) -> None:
            self.max_row = max_row
            self.max_column = max_column
            self.merged_cells = SimpleNamespace(ranges=[_Range(size) for size in merged_sizes])

    class _Workbook:
        def __init__(self) -> None:
            self.closed = False
            self.sheetnames = ["Summary", "Details"]
            self._sheets = {
                "Summary": _Sheet(max_row=4, max_column=2, merged_sizes=[4]),
                "Details": _Sheet(max_row=6, max_column=5, merged_sizes=[50]),
            }

        def __getitem__(self, name: str) -> object:
            return self._sheets[name]

        def close(self) -> None:
            self.closed = True

    workbook = _Workbook()
    fake_openpyxl = SimpleNamespace(load_workbook=lambda *_args, **_kwargs: workbook)
    monkeypatch.setattr(runner, "_get_openpyxl", lambda: fake_openpyxl)

    stats, error = runner._xlsx_spreadsheet_stats(tmp_path / "sample.xlsx")

    assert error is None
    assert stats == {
        "row_count": 6,
        "col_count": 5,
        "sheet_count": 2,
        "merged_cell_ratio": 0.133333,
        "estimated_rows": False,
        "estimated_cols": False,
    }
    assert workbook.closed is True


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("email", "alice@example.com", "a***@example.com"),
        ("ip", "10.20.30.40", "10.20.30.***"),
        ("phone", "+86 138-0013-8000", "861****00"),
        ("credit_card", "4111 1111 1111 1234", "4111****1234"),
        ("cn_id", "110101199001011234", "110101********34"),
        ("ssn", "123-45-6789", "***-**-****"),
        ("unknown", "value", runner.REDACTED_MASK),
    ],
)
def test_mask_pii_value_preserves_existing_formats(kind: str, raw: str, expected: str) -> None:
    assert runner._mask_pii_value(kind, raw) == expected


def test_run_dataset_precheck_scan_keeps_completed_status_for_file_parse_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    scan_run_id = uuid4()
    upload_root = tmp_path / "uploads"
    root = upload_root / "scan-root"
    root.mkdir(parents=True)
    (root / "broken.txt").write_text("boom", encoding="utf-8")

    run = SimpleNamespace(
        id=scan_run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        config={"root_path": str(root)},
        status="queued",
        progress=None,
        started_at=None,
        updated_at=None,
        finished_at=None,
        error_message="stale",
        summary=None,
        artifacts=None,
    )
    db = _FakeDB(run=run, dataset_metadata={"language": "en"})

    monkeypatch.setattr(runner.settings, "LOCAL_SCAN_ENABLED", True, raising=False)
    monkeypatch.setattr(runner.settings, "UPLOAD_DIR", str(upload_root), raising=False)
    monkeypatch.setattr(runner.settings, "LOCAL_SCAN_ROOTS", "", raising=False)
    monkeypatch.setattr(
        runner,
        "resolve_pre_poc_scanner_thresholds",
        lambda _cfg: {
            "sample_size": 0,
            "pdf_scan_ratio_threshold": 0.5,
            "text_short_chars_threshold": 100,
            "text_density_threshold": 0.2,
            "text_gibberish_density_threshold": 0.05,
            "text_high_replacement_ratio_threshold": 0.3,
            "pdf_low_density_ratio_threshold": 0.5,
        },
    )
    monkeypatch.setattr(runner, "_read_text_sample", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(runner, "classify_parse_failure_kind", lambda **_kwargs: "other_parse_failure")
    monkeypatch.setattr(runner, "build_embedding_language_advisories", lambda **_kwargs: [])
    build_scan_options = runner._build_scan_options
    monkeypatch.setattr(
        runner,
        "_build_scan_options",
        lambda *, cfg: replace(build_scan_options(cfg=cfg), allowed_exts={".txt"}),
    )

    result = runner.run_dataset_precheck_scan(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )

    findings = {entry["key"]: entry["count"] for entry in run.summary["findings"]}
    jsonl_path = Path(run.artifacts["files_jsonl"])

    assert result == {"ok": True, "files": 1, "errors": 1, "reused": 0}
    assert run.status == "completed"
    assert run.progress == 100
    assert run.error_message is None
    assert run.summary["total_files"] == 1
    assert findings["parse_failed"] == 1
    assert findings["other_parse_failure"] == 1
    assert Path(run.artifacts["samples_json"]).is_file()
    record = json.loads(jsonl_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["error_message"] == "boom"
    assert record["findings"] == ["parse_failed", "other_parse_failure"]

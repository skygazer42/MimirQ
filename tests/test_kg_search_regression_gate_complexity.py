import json
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import kg_search_regression_gate as gate


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _Client:
    def __init__(self, calls: list[tuple[str, str, dict[str, Any]]], **kwargs: Any) -> None:
        calls.append(("init", "", kwargs))
        self.calls = calls

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("get", url, kwargs))
        return _Response(
            {
                "items": [
                    {
                        "id": "case-1",
                        "dataset_id": "dataset-1",
                        "question": "What changed?",
                    }
                ],
                "total": 1,
            }
        )

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append(("post", url, kwargs))
        return _Response(
            {
                "summary": {
                    "baseline_hit_rate": 0.9,
                    "baseline_mrr": 0.8,
                }
            }
        )


def test_check_thresholds_reports_missing_non_numeric_min_and_max() -> None:
    assert gate._check_thresholds(
        summary={"low": 0.2, "high": 0.9, "bad": "nope"},
        thresholds={
            "missing": {"min": 0.1},
            "bad": {"min": 0.1},
            "low": {"min": 0.5},
            "high": {"max": 0.7},
        },
    ) == [
        "missing metric in summary: missing",
        "non-numeric metric bad: 'nope'",
        "low=0.2000 < min 0.5000",
        "high=0.9000 > max 0.7000",
    ]


def test_main_lists_cases_runs_diagnostics_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    thresholds_path = tmp_path / "thresholds.json"
    report_path = tmp_path / "reports" / "diagnostics.json"
    cases_path.write_text(
        json.dumps({"dataset_id": "dataset-1", "items": [{"question": "What changed?"}]}),
        encoding="utf-8",
    )
    thresholds_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "metrics": {
                    "baseline_hit_rate": {"min": 0.8},
                    "baseline_mrr": 0.7,
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(gate.httpx, "Client", lambda **kwargs: _Client(calls, **kwargs))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "kg_search_regression_gate.py",
            "--base-url",
            "http://example.test/api/v1/",
            "--user-id",
            "user-1",
            "--cases",
            str(cases_path),
            "--thresholds",
            str(thresholds_path),
            "--k",
            "75",
            "--skip-import",
            "--auto-extract-kg",
            "--out-run-json",
            str(report_path),
        ],
    )

    assert gate.main() == 0

    assert json.loads(report_path.read_text(encoding="utf-8")) == {
        "summary": {"baseline_hit_rate": 0.9, "baseline_mrr": 0.8}
    }
    assert calls[0][0] == "init"
    assert calls[0][2]["headers"] == {"Content-Type": "application/json", "X-User-ID": "user-1"}
    assert calls[1] == (
        "get",
        "http://example.test/api/v1/evaluations/ragas/regression/cases",
        {"params": {"skip": 0, "limit": 200, "dataset_id": "dataset-1"}},
    )
    assert calls[2][1] == "http://example.test/api/v1/evaluations/kg/search/diagnostics"
    assert calls[2][2]["json"]["case_ids"] == ["case-1"]
    assert calls[2][2]["json"]["k"] == 50
    assert calls[2][2]["json"]["auto_extract_kg"] is True
    output = capsys.readouterr().out
    assert "matched cases: 1/1" in output
    assert "[kg_search_regression_gate] PASS" in output

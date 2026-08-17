import json
from pathlib import Path
from typing import Any

import pytest

from scripts import eval_retrieval_fusion_offline as fusion_eval


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _Client:
    def __init__(self, calls: list[dict[str, Any]], **_kwargs: Any) -> None:
        self.calls = calls

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        index = len(self.calls)
        return _Response(
            {
                "citations": [{"chunk_id": f"chunk-{index}"}],
                "abstain_triggered": index == 2,
                "abstain_reason": "low_confidence" if index == 2 else None,
            }
        )


def test_main_evaluates_default_base_and_budgeted_rrf_variants(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    out_json = tmp_path / "reports" / "fusion.json"
    out_md = tmp_path / "reports" / "fusion.md"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {"question": "What changed?", "reference_sources": ["chunk-1"]},
                    {"question": "Ignored", "reference_sources": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(fusion_eval.httpx, "Client", lambda **kwargs: _Client(calls, **kwargs))
    monkeypatch.setattr(
        fusion_eval,
        "compute_retrieval_item_meta",
        lambda *, case, citations: {"question": case["question"], "citations": citations},
    )
    monkeypatch.setattr(
        fusion_eval,
        "build_retrieval_gate_summary",
        lambda items: {"retrieval_recall": len(items), "abstain_rate": int(bool(items[0]["abstain_triggered"]))},
    )
    timestamps = iter([10.0, 11.25])
    monkeypatch.setattr(fusion_eval.time, "time", lambda: next(timestamps))

    assert (
        fusion_eval.main(
            [
                "--cases",
                str(cases_path),
                "--base-url",
                "http://example.test/api/v1/",
                "--user-id",
                "user-1",
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ]
        )
        == 0
    )

    result = json.loads(out_json.read_text(encoding="utf-8"))
    assert result["elapsed_sec"] == 1.25
    assert result["cases_total"] == 2
    assert [row["label"] for row in result["variants"]] == ["base", "budgeted_rrf"]
    assert [row["cases_used"] for row in result["variants"]] == [1, 1]
    assert result["variants"][0]["summary"] == {"retrieval_recall": 1, "abstain_rate": 0}
    assert result["variants"][1]["summary"] == {"retrieval_recall": 1, "abstain_rate": 1}
    assert calls[0]["url"] == "http://example.test/api/v1/rag/retrieve"
    assert calls[0]["headers"] == {"Content-Type": "application/json", "X-User-ID": "user-1"}
    assert "fusion_strategy" not in calls[0]["json"]["rag_config"]
    assert calls[1]["json"]["rag_config"]["fusion_strategy"] == "budgeted_rrf"
    assert out_md.read_text(encoding="utf-8") + "\n" == capsys.readouterr().out


def test_main_reports_missing_cases_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        fusion_eval.httpx,
        "Client",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not start")),
    )

    assert fusion_eval.main(["--cases", str(tmp_path / "missing.json")]) == 2
    assert "cases file not found" in capsys.readouterr().err

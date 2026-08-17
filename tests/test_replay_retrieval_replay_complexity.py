import json
from pathlib import Path
from typing import Any

import pytest

from scripts import replay_retrieval_replay as replay


class _Response:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _Client:
    def __init__(self, responses: list[object], calls: list[dict[str, Any]], **_kwargs: Any) -> None:
        self.responses = iter(responses)
        self.calls = calls

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return _Response(next(self.responses))


def test_main_reports_matches_skips_and_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captures_path = tmp_path / "captures.jsonl"
    cases_path = tmp_path / "cases.json"
    report_path = tmp_path / "report.json"
    citations = [{"document_id": "doc-1", "chunk_id": "chunk-1"}]
    expected_fingerprint = replay.fingerprint_citations(citations)
    questions = ["first question", "second question"]
    hashes = [replay.stable_hash(question, length=16) for question in questions]
    cases_path.write_text(
        json.dumps({"dataset_id": "dataset-1", "items": [{"question": question} for question in questions]}),
        encoding="utf-8",
    )
    records = [
        {
            "schema": replay.RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1,
            "query_hash": hashes[0],
            "rag_config": {"retrieval_mode": "hybrid"},
            "seed": "7",
            "citations_fingerprint": expected_fingerprint,
            "retrieval_config_hash": "config-1",
        },
        "{",
        {
            "schema": replay.RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1,
            "query_hash": "unknown",
        },
        {
            "schema": replay.RETRIEVAL_REPLAY_CAPTURE_SCHEMA_V1,
            "query_hash": hashes[1],
            "citations_fingerprint": "different",
        },
    ]
    captures_path.write_text(
        "\n".join(record if isinstance(record, str) else json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    calls: list[dict[str, Any]] = []
    responses = [
        {"citations": citations, "metrics": {"retrieval_config_hash": "config-1"}},
        {"citations": []},
    ]
    monkeypatch.setattr(replay.httpx, "Client", lambda **kwargs: _Client(responses, calls, **kwargs))
    monotonic = iter([10.0, 11.234])
    monkeypatch.setattr(replay.time, "monotonic", lambda: next(monotonic))

    assert (
        replay.main(
            [
                "--captures",
                str(captures_path),
                "--cases",
                str(cases_path),
                "--out-json",
                str(report_path),
                "--base-url",
                "http://example.test/api/v1/",
                "--tenant-id",
                "tenant-1",
                "--user-id",
                "user-1",
                "--bearer",
                "secret",
            ]
        )
        == 1
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["totals"] == {"records": 4, "matched": 1, "mismatched": 1, "skipped": 2, "errors": 0}
    assert report["elapsed_sec"] == 1.234
    assert report["mismatches"] == [
        {
            "query_hash": hashes[1],
            "retrieval_config_hash_expected": None,
            "retrieval_config_hash_actual": None,
            "fingerprint_expected": "different",
            "fingerprint_actual": replay.fingerprint_citations([]),
        }
    ]
    assert [call["json"]["query"] for call in calls] == questions
    assert calls[0]["url"] == "http://example.test/api/v1/rag/retrieve"
    assert calls[0]["headers"] == {
        "Content-Type": "application/json",
        "X-Tenant-ID": "tenant-1",
        "X-User-ID": "user-1",
        "Authorization": "Bearer secret",
    }
    assert calls[0]["json"]["seed"] == 7
    assert "records=4 matched=1 mismatched=1 skipped=2 errors=0" in capsys.readouterr().err


def test_main_rejects_missing_capture_before_loading_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        replay,
        "_load_json",
        lambda _path: (_ for _ in ()).throw(AssertionError("cases must not load")),
    )

    assert replay.main(["--captures", str(tmp_path / "missing.jsonl"), "--cases", "cases.json"]) == 2
    assert "captures file not found" in capsys.readouterr().err

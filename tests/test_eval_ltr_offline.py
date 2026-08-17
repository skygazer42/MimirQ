from __future__ import annotations

import datetime
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc

from scripts import eval_ltr_offline as module


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    def __init__(
        self,
        *,
        calls: list[dict[str, Any]],
        payloads: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._calls = calls
        self._payloads = list(payloads or [])
        self._error = error

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _FakeResponse:
        self._calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "json": json,
            }
        )
        if self._error is not None:
            raise self._error
        assert self._payloads, f"unexpected request: {url}"
        return _FakeResponse(self._payloads.pop(0))


def _write_cases_bundle(path: Path, *, items: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "mimirq.regression_cases.v1",
                "dataset_id": "ds-1",
                "items": items,
            }
        ),
        encoding="utf-8",
    )


def _ndcg(rank: int) -> float:
    return 1.0 / math.log2(float(rank) + 1.0)


def test_main_uses_cli_defaults_and_writes_summary_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    model_path = tmp_path / "ltr-model.json"
    out_json_path = tmp_path / "summary.json"
    model_bytes = b'{"learner":{}}'
    model_path.write_bytes(model_bytes)
    _write_cases_bundle(
        cases_path,
        items=[
            {
                "question": "Where is the positive chunk?",
                "reference_sources": [
                    {
                        "chunk_id": "chunk-pos",
                        "pipeline_hash": "pipe-1",
                    }
                ],
            },
            {"question": "", "reference_sources": [{"chunk_id": "skip-empty-question"}]},
            {"question": "Missing refs should be skipped", "reference_sources": []},
        ],
    )

    calls: list[dict[str, Any]] = []
    payloads = [
        {
            "citations": [
                {
                    "chunk_id": "chunk-neg-1",
                    "chunk_content": "neg one",
                    "relevance_score": 0.91,
                },
                {
                    "chunk_id": "chunk-pos",
                    "chunk_content": "positive",
                    "relevance_score": 0.82,
                },
                {
                    "chunk_id": "chunk-neg-2",
                    "chunk_content": "neg two",
                    "relevance_score": 0.73,
                },
            ],
            "retrieval_trace": {
                "retrieval_config": {
                    "schema": "mimirq.retrieval_config.v1",
                    "hash": "cfg-123",
                    "top_k": 50,
                }
            },
        }
    ]

    class _FakeReranker:
        def __init__(self, *, model_path: str, spec: Any) -> None:
            self.model_path = model_path
            self.spec = spec

        def rerank(
            self,
            *,
            query: str,
            candidates: list[Any],
            top_n: int,
        ) -> SimpleNamespace:
            assert query == "Where is the positive chunk?"
            assert [candidate.id for candidate in candidates] == [
                "chunk-neg-1",
                "chunk-pos",
                "chunk-neg-2",
            ]
            assert top_n == 3
            return SimpleNamespace(ordered_ids=["chunk-pos", "chunk-neg-1", "chunk-neg-2"])

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(calls=calls, payloads=payloads),
    )
    monkeypatch.setattr(module, "LTRReranker", _FakeReranker)
    monkeypatch.setattr(module.time, "strftime", lambda *_args: "2026-08-16T00:00:00Z")

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--model",
            str(model_path),
            "--out-json",
            str(out_json_path),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(out_json_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured.err == ""
    assert len(calls) == 1
    assert calls[0]["url"] == "http://localhost:8000/api/v1/rag/retrieve"
    assert calls[0]["headers"] == {"Content-Type": "application/json"}
    assert calls[0]["json"] == {
        "query": "Where is the positive chunk?",
        "history": [],
        "dataset_id": "ds-1",
        "document_ids": [],
        "rag_config": {
            "retrieval_profile": "recall50",
            "retrieval_mode": "hybrid",
            "top_k": 50,
            "score_threshold": 0.0,
            "alpha": 0.6,
            "enable_reranker": False,
            "reranker_provider": "none",
            "reranker_top_n": 0,
        },
    }
    assert summary["schema"] == "mimirq.ltr_offline_eval.v1"
    assert summary["generated_at"] == "2026-08-16T00:00:00Z"
    assert summary["dataset_id"] == "ds-1"
    assert summary["cases_total"] == 3
    assert summary["cases_used"] == 1
    assert summary["k"] == 20
    assert summary["top_k"] == 50
    assert summary["rerank_top_n"] == 30
    assert summary["model"] == str(model_path)
    assert summary["model_sha256"] == hashlib.sha256(model_bytes).hexdigest()
    assert summary["baseline"] == {
        "hit": 1.0,
        "mrr": 0.5,
        "recall": 1.0,
        "ndcg": round(_ndcg(2), 4),
    }
    assert summary["ltr"] == {
        "hit": 1.0,
        "mrr": 1.0,
        "recall": 1.0,
        "ndcg": 1.0,
    }
    assert summary["lineage"] == {
        "schema": "mimirq.ltr_run_lineage.v1",
        "kind": "eval",
        "dataset_id": "ds-1",
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "cases_schema": "mimirq.regression_cases.v1",
        "pipeline_hashes": ["pipe-1"],
        "retrieval_config_hash": "cfg-123",
        "retrieval_config": {
            "schema": "mimirq.retrieval_config.v1",
            "hash": "cfg-123",
            "top_k": 50,
        },
        "model_path": str(model_path),
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "feature_spec_version": 1,
        "feature_spec": module.build_ltr_feature_spec_fingerprint(
            spec=module.LTRFeatureSpec.from_version(1),
            version=1,
        ),
    }
    assert "[eval_ltr] OK cases_total=3 cases_used=1 k=20" in captured.out
    assert f"model={model_path}" in captured.out


def test_main_preserves_reranked_prefix_and_baseline_tail_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.json"
    model_path = tmp_path / "ltr-model.json"
    model_path.write_bytes(b'{"learner":{}}')
    _write_cases_bundle(
        cases_path,
        items=[
            {
                "question": "Which chunks stay ordered?",
                "reference_sources": [{"chunk_id": "chunk-4"}],
            }
        ],
    )

    payloads = [
        {
            "citations": [
                {"chunk_id": "chunk-1", "chunk_content": "one", "relevance_score": 0.9},
                {"chunk_id": "chunk-2", "chunk_content": "two", "relevance_score": 0.8},
                {"chunk_id": "chunk-3", "chunk_content": "three", "relevance_score": 0.7},
                {"chunk_id": "chunk-4", "chunk_content": "four", "relevance_score": 0.6},
            ]
        }
    ]
    seen: dict[str, Any] = {}

    class _FakeReranker:
        def __init__(self, *, model_path: str, spec: Any) -> None:
            self.model_path = model_path
            self.spec = spec

        def rerank(
            self,
            *,
            query: str,
            candidates: list[Any],
            top_n: int,
        ) -> SimpleNamespace:
            seen["query"] = query
            seen["candidate_ids"] = [candidate.id for candidate in candidates]
            seen["top_n"] = top_n
            return SimpleNamespace(ordered_ids=["chunk-2", "chunk-1"])

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(calls=[], payloads=payloads),
    )
    monkeypatch.setattr(module, "LTRReranker", _FakeReranker)

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--model",
            str(model_path),
            "--k",
            "4",
            "--top-k",
            "4",
            "--rerank-top-n",
            "2",
            "--out-json",
            str(tmp_path / "summary.json"),
        ]
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert seen == {
        "query": "Which chunks stay ordered?",
        "candidate_ids": ["chunk-1", "chunk-2"],
        "top_n": 2,
    }
    assert summary["baseline"] == {
        "hit": 1.0,
        "mrr": 0.25,
        "recall": 1.0,
        "ndcg": round(_ndcg(4), 4),
    }
    assert summary["ltr"] == {
        "hit": 1.0,
        "mrr": 0.25,
        "recall": 1.0,
        "ndcg": round(_ndcg(4), 4),
    }


def test_main_slices_raw_citations_before_filtering_rerank_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.json"
    model_path = tmp_path / "ltr-model.json"
    out_json_path = tmp_path / "summary.json"
    model_path.write_bytes(b'{"learner":{}}')
    _write_cases_bundle(
        cases_path,
        items=[
            {
                "question": "Which citations are in the rerank prefix?",
                "reference_sources": [{"chunk_id": "chunk-2"}],
            }
        ],
    )

    payloads = [
        {
            "citations": [
                {"chunk_id": "chunk-1", "chunk_content": "one"},
                "junk",
                {"chunk_id": "chunk-2", "chunk_content": "two"},
            ]
        }
    ]
    seen: dict[str, Any] = {}

    class _FakeReranker:
        def __init__(self, *, model_path: str, spec: Any) -> None:
            self.model_path = model_path
            self.spec = spec

        def rerank(
            self,
            *,
            query: str,
            candidates: list[Any],
            top_n: int,
        ) -> SimpleNamespace:
            seen["candidate_ids"] = [candidate.id for candidate in candidates]
            seen["top_n"] = top_n
            return SimpleNamespace(ordered_ids=[candidate.id for candidate in reversed(candidates)])

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(calls=[], payloads=payloads),
    )
    monkeypatch.setattr(module, "LTRReranker", _FakeReranker)

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--model",
            str(model_path),
            "--k",
            "2",
            "--top-k",
            "3",
            "--rerank-top-n",
            "2",
            "--out-json",
            str(out_json_path),
        ]
    )

    summary = json.loads(out_json_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert seen == {"candidate_ids": ["chunk-1"], "top_n": 1}
    assert summary["ltr"]["mrr"] == 0.5


def test_main_missing_required_args_raises_system_exit() -> None:
    with pytest.raises(SystemExit) as exc_info:
        module.main([])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    ("arg_name", "filename", "message"),
    [
        ("--cases", "missing-cases.json", "[eval_ltr] ERROR: cases file not found:"),
        ("--model", "missing-model.json", "[eval_ltr] ERROR: model file not found:"),
    ],
)
def test_main_returns_2_when_required_input_file_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arg_name: str,
    filename: str,
    message: str,
) -> None:
    cases_path = tmp_path / "cases.json"
    model_path = tmp_path / "ltr-model.json"
    _write_cases_bundle(
        cases_path,
        items=[{"question": "What is missing?", "reference_sources": [{"chunk_id": "chunk-1"}]}],
    )
    model_path.write_bytes(b"model")

    argv = [
        "--cases",
        str(cases_path),
        "--model",
        str(model_path),
    ]
    missing_path = tmp_path / filename
    value_index = argv.index(arg_name) + 1
    argv[value_index] = str(missing_path)

    exit_code = module.main(argv)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert message in captured.err


def test_main_returns_2_when_cases_file_cannot_be_parsed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    model_path = tmp_path / "ltr-model.json"
    cases_path.write_text("{not-json", encoding="utf-8")
    model_path.write_bytes(b"model")

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--model",
            str(model_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "[eval_ltr] ERROR: failed to parse cases:" in captured.err


def test_main_warns_on_retrieve_failure_and_exits_zero_with_empty_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    model_path = tmp_path / "ltr-model.json"
    out_json_path = tmp_path / "summary.json"
    _write_cases_bundle(
        cases_path,
        items=[
            {
                "question": "What retrieval failed?",
                "reference_sources": [{"chunk_id": "chunk-pos"}],
            }
        ],
    )
    model_path.write_bytes(b"model")

    class _FakeReranker:
        def __init__(self, *, model_path: str, spec: Any) -> None:
            self.model_path = model_path
            self.spec = spec

        def rerank(self, *, query: str, candidates: list[Any], top_n: int) -> SimpleNamespace:
            raise AssertionError("rerank should not be called when retrieval fails")

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(calls=[], error=RuntimeError("backend unavailable")),
    )
    monkeypatch.setattr(module, "LTRReranker", _FakeReranker)

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--model",
            str(model_path),
            "--out-json",
            str(out_json_path),
        ]
    )

    captured = capsys.readouterr()
    summary = json.loads(out_json_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "[eval_ltr] WARN: retrieve failed: backend unavailable" in captured.err
    assert summary["cases_total"] == 1
    assert summary["cases_used"] == 0
    assert summary["baseline"] == {"hit": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}
    assert summary["ltr"] == {"hit": 0.0, "mrr": 0.0, "recall": 0.0, "ndcg": 0.0}

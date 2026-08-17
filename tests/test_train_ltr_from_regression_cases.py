
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import train_ltr_from_regression_cases as module


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

    def __enter__(self) -> "_FakeClient":
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


def test_coerce_case_bundle_normalizes_supported_shapes() -> None:
    dataset_id, bundle_items = module.coerce_case_bundle(
        {
            "schema": "mimirq.regression_cases.v1",
            "dataset_id": "ds-1",
            "items": [
                {"dataset_id": "ds-1", "question": "first"},
                "skip-me",
                {"query": "second"},
            ],
        }
    )
    legacy_dataset_id, legacy_items = module.coerce_case_bundle(
        [
            {"dataset_id": "ds-2", "question": "alpha"},
            {"dataset_id": "ds-2", "query": "beta"},
        ]
    )

    assert dataset_id == "ds-1"
    assert bundle_items == [{"question": "first"}, {"query": "second"}]
    assert legacy_dataset_id == "ds-2"
    assert legacy_items == [{"question": "alpha"}, {"query": "beta"}]


def test_coerce_case_bundle_rejects_mixed_dataset_ids() -> None:
    with pytest.raises(ValueError, match="mixed dataset_id"):
        module.coerce_case_bundle(
            [
                {"dataset_id": "ds-1", "question": "first"},
                {"dataset_id": "ds-2", "question": "second"},
            ]
        )


def test_build_ltr_manifest_preserves_schema_and_feature_order() -> None:
    spec = module.LTRFeatureSpec.from_version(1)
    model_bytes = b'{"learner":{}}'
    manifest = module.build_ltr_manifest(
        model_bytes=model_bytes,
        created_at="2026-08-16T12:00:00Z",
        model_file="ltr-model.json",
        spec=spec,
        feature_spec_version="2",
        objective="rank:pairwise",
        num_boost_round=7,
        seed=13,
        training={"rows_total": 3, "rows_pos": 1, "rows_neg": 2},
        dataset_id="ds-1",
        cases_sha256="cases-123",
        cases_schema="mimirq.regression_cases.v1",
        pipeline_hashes=["pipe-1", "pipe-2"],
        retrieval_config={
            "schema": "mimirq.retrieval_config.v1",
            "hash": "cfg-123",
            "top_k": 50,
        },
        hard_negatives_sha256="neg-123",
    )

    assert manifest["schema"] == "mimirq.ltr_model_manifest.v1"
    assert manifest["model_sha256"] == hashlib.sha256(model_bytes).hexdigest()
    assert manifest["feature_names"] == list(spec.feature_names)
    assert manifest["feature_spec_version"] == 2
    assert manifest["objective"] == "rank:pairwise"
    assert manifest["training"] == {"rows_total": 3, "rows_pos": 1, "rows_neg": 2}
    assert manifest["lineage"] == {
        "schema": "mimirq.ltr_run_lineage.v1",
        "kind": "train",
        "dataset_id": "ds-1",
        "cases_sha256": "cases-123",
        "cases_schema": "mimirq.regression_cases.v1",
        "pipeline_hashes": ["pipe-1", "pipe-2"],
        "retrieval_config_hash": "cfg-123",
        "retrieval_config": {
            "schema": "mimirq.retrieval_config.v1",
            "hash": "cfg-123",
            "top_k": 50,
        },
        "hard_negatives_sha256": "neg-123",
    }


def test_main_uses_defaults_filters_cases_and_writes_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    out_model_path = tmp_path / "ltr-model.json"
    out_rows_path = tmp_path / "rows.jsonl"
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
    captured: dict[str, Any] = {}
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
                {"chunk_id": "", "chunk_content": "ignored", "relevance_score": 0.64},
                "not-a-citation",
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

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(calls=calls, payloads=payloads),
    )
    monkeypatch.setattr(
        module,
        "build_ltr_feature_map",
        lambda *, citation, query, spec: {
            "score": float(citation["relevance_score"]),
            "query_len": float(len(query)),
        },
    )

    def fake_train_ltr_xgboost_model(
        *,
        training_rows: list[dict[str, Any]],
        spec: Any,
        num_boost_round: int,
        seed: int,
        objective: str,
        group_sizes: list[int] | None,
    ) -> bytes:
        captured["training_rows"] = training_rows
        captured["feature_schema"] = getattr(spec, "schema", "")
        captured["num_boost_round"] = num_boost_round
        captured["seed"] = seed
        captured["objective"] = objective
        captured["group_sizes"] = group_sizes
        return b'{"trained":true}'

    monkeypatch.setattr(module, "train_ltr_xgboost_model", fake_train_ltr_xgboost_model)
    monkeypatch.setattr(module.time, "strftime", lambda *_args: "2026-08-16T00:00:00Z")

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--out-model",
            str(out_model_path),
            "--out-rows-jsonl",
            str(out_rows_path),
        ]
    )

    captured_io = capsys.readouterr()
    manifest_path = out_model_path.with_suffix(".manifest.json")
    rows = [json.loads(line) for line in out_rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert captured_io.err == ""
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
            "enable_weight_rerank": False,
            "enable_reranker": False,
            "reranker_provider": "none",
            "reranker_top_n": 0,
        },
    }
    assert [row["label"] for row in captured["training_rows"]] == [0, 1, 0]
    assert [row["rank"] for row in captured["training_rows"]] == [1, 2, 3]
    assert [row["chunk_id"] for row in captured["training_rows"]] == [
        "chunk-neg-1",
        "chunk-pos",
        "chunk-neg-2",
    ]
    assert list(captured["training_rows"][0]["features"]) == ["score", "query_len"]
    assert captured["group_sizes"] == [3]
    assert captured["objective"] == "rank:pairwise"
    assert captured["num_boost_round"] == 50
    assert captured["seed"] == 42
    assert out_model_path.read_bytes() == b'{"trained":true}'
    assert [row["chunk_id"] for row in rows] == ["chunk-neg-1", "chunk-pos", "chunk-neg-2"]
    assert rows[0]["hard_negative"] is True
    assert manifest["schema"] == "mimirq.ltr_model_manifest.v1"
    assert manifest["created_at"] == "2026-08-16T00:00:00Z"
    assert manifest["model_file"] == "ltr-model.json"
    assert manifest["training"]["cases_total"] == 3
    assert manifest["training"]["cases_used"] == 1
    assert manifest["training"]["cases_missed"] == 0
    assert manifest["training"]["rows_total"] == 3
    assert manifest["training"]["rows_pos"] == 1
    assert manifest["training"]["rows_neg"] == 2
    assert manifest["training"]["rows_hard_neg"] == 1
    assert manifest["training"]["group_count"] == 1
    assert manifest["lineage"]["dataset_id"] == "ds-1"
    assert manifest["lineage"]["cases_schema"] == "mimirq.regression_cases.v1"
    assert manifest["lineage"]["pipeline_hashes"] == ["pipe-1"]
    assert manifest["lineage"]["retrieval_config_hash"] == "cfg-123"
    assert "[train_ltr] OK cases_total=3 cases_used=1" in captured_io.out
    assert "rows_total=3 rows_pos=1 rows_neg=2 rows_hard_neg=1" in captured_io.out
    assert f"model={out_model_path}" in captured_io.out


def test_main_missing_required_args_raises_system_exit() -> None:
    with pytest.raises(SystemExit) as exc_info:
        module.main([])

    assert exc_info.value.code == 2


def test_main_returns_2_when_cases_file_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = module.main(
        [
            "--cases",
            str(tmp_path / "missing.json"),
            "--out-model",
            str(tmp_path / "ltr-model.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "[train_ltr] ERROR: cases file not found:" in captured.err


def test_main_returns_2_when_cases_file_cannot_be_parsed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("{not-json", encoding="utf-8")

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--out-model",
            str(tmp_path / "ltr-model.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "[train_ltr] ERROR: failed to parse cases:" in captured.err


def test_main_returns_2_when_retrieval_produces_no_training_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases_path = tmp_path / "cases.json"
    _write_cases_bundle(
        cases_path,
        items=[
            {
                "question": "What retrieval failed?",
                "reference_sources": [{"chunk_id": "chunk-pos"}],
            }
        ],
    )

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(
            calls=calls,
            error=RuntimeError("backend unavailable"),
        ),
    )

    exit_code = module.main(
        [
            "--cases",
            str(cases_path),
            "--out-model",
            str(tmp_path / "ltr-model.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert len(calls) == 1
    assert "[train_ltr] WARN: retrieve failed: backend unavailable" in captured.err
    assert "[train_ltr] ERROR: produced zero training rows" in captured.err

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "eval_rerank_pipeline_offline.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("eval_rerank_pipeline_offline", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_pipeline_summary_tracks_wins_losses_and_ties() -> None:
    mod = _load_module()

    summary = mod.build_pipeline_summary(  # type: ignore[attr-defined]
        cases_total=3,
        cases_used=3,
        k=20,
        top_k=50,
        pipeline=[{"provider": "colbert", "top_n": 20}],
        baseline={"hit": 0.4, "mrr": 0.3, "recall": 0.5, "ndcg": 0.35},
        pipeline_metrics={"hit": 0.5, "mrr": 0.31, "recall": 0.45, "ndcg": 0.4},
        case_metrics=[
            {
                "baseline": {"mrr": 0.2, "ndcg": 0.2},
                "pipeline": {"mrr": 0.5, "ndcg": 0.5},
            },
            {
                "baseline": {"mrr": 0.6, "ndcg": 0.6},
                "pipeline": {"mrr": 0.3, "ndcg": 0.3},
            },
            {
                "baseline": {"mrr": 0.4, "ndcg": 0.4},
                "pipeline": {"mrr": 0.4, "ndcg": 0.4},
            },
        ],
    )

    assert summary["schema"] == "mimirq.rerank_pipeline_eval.v1"
    assert summary["delta_counts"]["mrr"] == {"wins": 1, "losses": 1, "ties": 1}
    assert summary["delta_counts"]["ndcg"] == {"wins": 1, "losses": 1, "ties": 1}


def test_build_colbert_reranker_uses_provider_options(monkeypatch) -> None:  # noqa: ANN001
    mod = _load_module()

    captured = {}

    class _FakeColBERTReranker:
        def __init__(self, **kwargs):  # noqa: ANN003
            captured.update(kwargs)

    monkeypatch.setattr(mod, "ColBERTReranker", _FakeColBERTReranker, raising=True)

    args = Namespace(
        colbert_provider="hf",
        colbert_model_name="colbert-ir/colbertv2.0",
        colbert_device="cpu",
        colbert_batch_size=4,
        colbert_max_length=64,
        colbert_deterministic_dim=32,
    )

    _ = mod.build_colbert_reranker(args)  # type: ignore[attr-defined]
    assert captured["provider_name"] == "hf"
    assert captured["model_name"] == "colbert-ir/colbertv2.0"
    assert captured["batch_size"] == 4
    assert captured["max_length"] == 64


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.requests: list[tuple[str, dict, dict]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def post(self, url: str, *, headers: dict, json: dict) -> _FakeResponse:
        self.requests.append((url, headers, json))
        return _FakeResponse(self._payload)


def test_main_evaluates_valid_cases_and_writes_summary(monkeypatch, tmp_path, capsys) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "summary.json"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {
                        "question": "Where is the evidence?",
                        "reference_sources": [{"chunk_id": "relevant"}],
                    },
                    {"question": "Skipped without references", "reference_sources": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    client = _FakeClient(
        {
            "citations": [
                {"chunk_id": "other", "chunk_content": "Other text", "relevance_score": 0.9},
                {"chunk_id": "relevant", "chunk_content": "Evidence", "relevance_score": 0.8},
            ]
        }
    )
    monkeypatch.setattr(mod.httpx, "Client", lambda **kwargs: client)

    result = mod.main(
        [
            "--cases",
            str(cases_path),
            "--pipeline",
            '[{"provider":"none","top_n":0}]',
            "--base-url",
            "http://example.test/api/v1/",
            "--tenant-id",
            "tenant-1",
            "--user-id",
            "user-1",
            "--bearer",
            "secret-token",
            "--k",
            "2",
            "--top-k",
            "3",
            "--out-json",
            str(out_path),
        ]
    )

    summary = json.loads(out_path.read_text(encoding="utf-8"))
    assert result == 0
    assert "[pipeline-eval] OK cases_total=2 cases_used=1 k=2" in capsys.readouterr().out
    assert summary["cases_total"] == 2
    assert summary["cases_used"] == 1
    assert summary["baseline"] == summary["pipeline_metrics"]
    assert summary["baseline"]["mrr"] == 0.5
    assert summary["delta_counts"]["mrr"] == {"wins": 0, "losses": 0, "ties": 1}
    assert out_path.read_bytes().endswith(b"\n")

    [(url, headers, body)] = client.requests
    assert url == "http://example.test/api/v1/rag/retrieve"
    assert headers == {
        "Content-Type": "application/json",
        "X-Tenant-ID": "tenant-1",
        "X-User-ID": "user-1",
        "Authorization": "Bearer secret-token",
    }
    assert body["dataset_id"] == "dataset-1"
    assert body["rag_config"]["top_k"] == 3
    assert body["rag_config"]["enable_reranker"] is False


def test_main_reports_missing_cases_and_empty_pipeline(tmp_path, capsys) -> None:
    mod = _load_module()
    missing_path = tmp_path / "missing.json"

    missing_result = mod.main(["--cases", str(missing_path), "--pipeline", "[]"])
    missing_error = capsys.readouterr().err

    cases_path = tmp_path / "cases.json"
    cases_path.write_text('{"dataset_id":"dataset-1","items":[]}', encoding="utf-8")
    empty_result = mod.main(["--cases", str(cases_path), "--pipeline", "[]"])
    empty_error = capsys.readouterr().err

    assert missing_result == 2
    assert f"cases file not found: {missing_path}" in missing_error
    assert empty_result == 2
    assert "pipeline is empty" in empty_error


def test_main_reports_missing_ltr_model(tmp_path, capsys) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text('{"dataset_id":"dataset-1","items":[]}', encoding="utf-8")

    result = mod.main(
        [
            "--cases",
            str(cases_path),
            "--pipeline",
            '[{"provider":"ltr","top_n":10}]',
        ]
    )

    assert result == 2
    assert "pipeline includes 'ltr' but --ltr-model is missing/not found" in capsys.readouterr().err


def test_main_initializes_colbert_only_when_pipeline_requires_it(monkeypatch, tmp_path) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text('{"dataset_id":"dataset-1","items":[]}', encoding="utf-8")
    sentinel = object()
    calls: list[object] = []

    def build_colbert(args: object) -> object:
        calls.append(args)
        return sentinel

    monkeypatch.setattr(mod, "build_colbert_reranker", build_colbert)
    monkeypatch.setattr(mod.httpx, "Client", lambda **kwargs: _FakeClient({"citations": []}))

    result = mod.main(
        [
            "--cases",
            str(cases_path),
            "--pipeline",
            '[{"provider":"colbert","top_n":10}]',
        ]
    )

    assert result == 0
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"citations": {}}, {"citations": "invalid"}])
def test_main_skips_non_list_citations(monkeypatch, tmp_path, capsys, payload: dict) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {
                        "question": "Question",
                        "reference_sources": [{"chunk_id": "relevant"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod.httpx, "Client", lambda **kwargs: _FakeClient(payload))

    result = mod.main(["--cases", str(cases_path), "--pipeline", '[{"provider":"none","top_n":0}]'])

    captured = capsys.readouterr()
    assert result == 0
    assert "cases_used=0" in captured.out
    assert captured.err == ""


def test_main_warns_and_skips_retrieve_failure(monkeypatch, tmp_path, capsys) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {
                        "question": "Question",
                        "reference_sources": [{"chunk_id": "relevant"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client = _FakeClient({})

    def fail_post(*args: object, **kwargs: object) -> None:
        raise RuntimeError("network down")

    monkeypatch.setattr(client, "post", fail_post)
    monkeypatch.setattr(mod.httpx, "Client", lambda **kwargs: client)

    result = mod.main(["--cases", str(cases_path), "--pipeline", '[{"provider":"none","top_n":0}]'])

    captured = capsys.readouterr()
    assert result == 0
    assert "cases_used=0" in captured.out
    assert captured.err == "[pipeline-eval] WARN: retrieve failed: network down\n"

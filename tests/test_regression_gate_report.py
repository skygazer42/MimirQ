
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "regression_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("regression_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_regression_gate_report_includes_channel_attribution() -> None:
    mod = _load_module()

    report = mod.build_regression_gate_report(  # type: ignore[attr-defined]
        dataset_id="ds-1",
        run_id="run-1",
        matched_case_count=2,
        metrics=["retrieval_recall"],
        thresholds_enabled=True,
        ok=False,
        failures=["retrieval_recall=0.2000 < min 0.3000"],
        run_payload={"retrieval_mode": "hybrid"},
        case_source={
            "kind": "plugin_golden",
            "plugin_ref": "plugin:demo-service@1.0.0:chunk",
            "plugin_id": "demo-service",
            "plugin_version": "1.0.0",
            "plugin_package_hash": "pkg_hash_abc123",
            "import_result": {"created": 2, "updated": 0, "skipped": 0},
        },
        detail={
            "run": {
                "status": "completed",
                "summary": {"retrieval_recall": 0.2},
            },
            "items": [
                {
                    "citations": [
                        {"vector_score": 0.9, "bm25_score": 0.0},
                        {"bm25_score": 0.5, "lexical_score": 0.4},
                        {"sparse_score": 0.3},
                    ],
                    "meta": {
                        "evidence_chain_steps": 2,
                        "multihop_path_completeness": 1.0,
                        "multihop_order_consistency": 0.5,
                        "multihop_chain_hit": True,
                    },
                }
            ],
        },
    )

    assert report["gate_status"] == "fail"
    assert report["case_source"]["kind"] == "plugin_golden"
    assert report["case_source"]["plugin_ref"] == "plugin:demo-service@1.0.0:chunk"
    assert report["case_source"]["plugin_id"] == "demo-service"
    assert report["case_source"]["plugin_version"] == "1.0.0"
    assert report["case_source"]["plugin_package_hash"] == "pkg_hash_abc123"
    assert report["case_source"]["import_result"]["created"] == 2
    assert report["channel_attribution"]["totals"]["vector"] == 1
    assert report["channel_attribution"]["totals"]["bm25"] == 1
    assert report["channel_attribution"]["totals"]["lexical"] == 1
    assert report["channel_attribution"]["totals"]["sparse"] == 1
    assert report["channel_attribution"]["totals"]["multi"] == 1
    assert report["multihop"]["cases_with_expectation"] == 1
    assert report["multihop"]["path_completeness"] == pytest.approx(1.0)


def test_render_regression_gate_markdown_renders_summary_and_failures() -> None:
    mod = _load_module()

    markdown = mod.render_regression_gate_markdown(  # type: ignore[attr-defined]
        {
            "gate_status": "fail",
            "run_status": "completed",
            "dataset_id": "ds-1",
            "run_id": "run-1",
            "matched_case_count": 2,
            "thresholds_enabled": True,
            "case_source": {
                "kind": "plugin_golden",
                "plugin_ref": "plugin:demo-service@1.0.0:chunk",
                "plugin_package_hash": "pkg_hash_abc123",
            },
            "summary": {"retrieval_recall": 0.2},
            "channel_attribution": {"totals": {"vector": 1, "bm25": 2, "lexical": 0, "sparse": 0, "multi": 0}},
            "multihop": {
                "cases_with_expectation": 2,
                "path_completeness": 0.75,
                "order_consistency": 0.6,
                "chain_hit_rate": 0.5,
            },
            "failures": ["retrieval_recall=0.2000 < min 0.3000"],
        }
    )

    assert "# Retrieval Regression Gate Report" in markdown
    assert "`fail`" in markdown
    assert "Case source: `plugin_golden`" in markdown
    assert "Plugin Golden ref: `plugin:demo-service@1.0.0:chunk`" in markdown
    assert "Plugin package hash: `pkg_hash_abc123`" in markdown
    assert "| retrieval_recall | 0.2000 |" in markdown
    assert "| bm25 | 2 |" in markdown
    assert "retrieval_recall=0.2000 < min 0.3000" in markdown
    assert "## Multi-hop Diagnostics" in markdown


def test_main_refetches_completed_run_with_items_for_final_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = _load_module()
    cases_path = tmp_path / "cases.json"
    out_path = tmp_path / "run.detail.json"
    cases_path.write_text(
        '{"dataset_id":"ds-1","items":[{"question":"What is retried?"}]}',
        encoding="utf-8",
    )

    requests_seen: list[tuple[str, str, dict | None]] = []

    def _response(method: str, url: str, payload: dict) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=payload,
            request=httpx.Request(method, url),
        )

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, json: dict | None = None) -> httpx.Response:
            requests_seen.append(("POST", url, json))
            assert url.endswith("/evaluations/ragas/regression/runs")
            return _response("POST", url, {"id": "run-1"})

        def get(self, url: str, params: dict | None = None) -> httpx.Response:
            requests_seen.append(("GET", url, params))
            if url.endswith("/evaluations/ragas/regression/cases"):
                return _response(
                    "GET",
                    url,
                    {
                        "items": [{"id": "case-1", "question": "What is retried?", "dataset_id": "ds-1"}],
                        "total": 1,
                    },
                )
            if params == {"include_items": False}:
                return _response(
                    "GET",
                    url,
                    {"run": {"status": "completed", "summary": {"retrieval_recall": 1.0}}, "items": []},
                )
            if params == {"include_items": True, "include_contexts": False}:
                return _response(
                    "GET",
                    url,
                    {
                        "run": {"status": "completed", "summary": {"retrieval_recall": 1.0}},
                        "items": [{"id": "item-1", "meta": {"must_recall_passed": True}}],
                    },
                )
            raise AssertionError(f"unexpected GET params: {params}")

    client_kwargs: dict[str, object] = {}

    def _client_factory(**kwargs: object) -> _FakeClient:
        client_kwargs.update(kwargs)
        return _FakeClient()

    monkeypatch.setattr(mod.httpx, "Client", _client_factory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "regression_gate.py",
            "--base-url",
            "http://example.test/api/v1",
            "--user-id",
            "ci-bot",
            "--cases",
            str(cases_path),
            "--skip-import",
            "--metrics",
            "retrieval_recall",
            "--out-run-json",
            str(out_path),
        ],
    )

    assert mod.main() == 0  # type: ignore[attr-defined]
    artifact = json.loads(out_path.read_text(encoding="utf-8"))

    assert client_kwargs["trust_env"] is False
    assert artifact["items"] == [{"id": "item-1", "meta": {"must_recall_passed": True}}]
    assert requests_seen[-1] == (
        "GET",
        "http://example.test/api/v1/evaluations/ragas/regression/runs/run-1",
        {"include_items": True, "include_contexts": False},
    )

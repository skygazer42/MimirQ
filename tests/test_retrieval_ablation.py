
import json
from pathlib import Path
from typing import Any

from scripts import retrieval_ablation as module


class _FakeResponse:
    def __init__(
        self,
        *,
        json_data: Any = None,
        text: str = "",
        error: Exception | None = None,
    ) -> None:
        self._json_data = json_data
        self.text = text
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> Any:
        return self._json_data


class _FakeClient:
    def __init__(self, plan: list[dict[str, Any]], calls: list[dict[str, Any]]) -> None:
        self._plan = list(plan)
        self.calls = calls

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "json": json})
        action = self._next("POST", url)
        if "exception" in action:
            raise action["exception"]
        return _FakeResponse(json_data=action.get("json"))

    def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "params": params})
        action = self._next("GET", url)
        if "exception" in action:
            raise action["exception"]
        return _FakeResponse(
            json_data=action.get("json"),
            text=str(action.get("text") or ""),
        )

    def _next(self, method: str, url: str) -> dict[str, Any]:
        assert self._plan, f"unexpected request: {method} {url}"
        action = self._plan.pop(0)
        assert action["method"] == method
        assert action["url"] == url
        return action


def _write_bundle(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {
                        "dataset_id": "dataset-1",
                        "question": "What is the answer?",
                        "reference_sources": [{"doc_id": "doc-1"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_matrix(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "base": {
                    "label": "base",
                    "rag_params": {"top_k": 5, "ignored_base": "drop-me"},
                },
                "variants": [
                    {"label": "alpha", "rag_params": {"top_k": 7, "ignored_variant": "x"}},
                    {"label": "beta", "rag_params": {"enable_multi_query": True}},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_build_variant_plan_preserves_order_and_characterization() -> None:
    base, variants = module.build_variant_plan(
        {
            "base": {"label": "control", "rag_params": {"top_k": 5, "alpha": 0.1}},
            "variants": [
                {"label": "control", "rag_params": {"top_k": 5}},
                {"label": "alpha", "rag_params": {"top_k": 7}},
                {"label": "alpha", "rag_params": {"enable_multi_query": True}},
                {"rag_params": {"alpha": 0.1}},
            ],
            "grid": {
                "retrieval_mode": ["hybrid", "keyword"],
                "top_k": [5, 9],
            },
        }
    )

    assert base == {
        "label": "control",
        "rag_params": {"top_k": 5, "alpha": 0.1},
    }
    assert variants == [
        {"label": "alpha", "rag_params": {"top_k": 7, "alpha": 0.1}},
        {
            "label": "alpha__2",
            "rag_params": {
                "top_k": 5,
                "alpha": 0.1,
                "enable_multi_query": True,
            },
        },
        {
            "label": "retrieval_mode=hybrid__top_k=5",
            "rag_params": {"top_k": 5, "alpha": 0.1, "retrieval_mode": "hybrid"},
        },
        {
            "label": "retrieval_mode=hybrid__top_k=9",
            "rag_params": {"top_k": 9, "alpha": 0.1, "retrieval_mode": "hybrid"},
        },
        {
            "label": "retrieval_mode=keyword__top_k=5",
            "rag_params": {
                "top_k": 5,
                "alpha": 0.1,
                "retrieval_mode": "keyword",
            },
        },
        {
            "label": "retrieval_mode=keyword__top_k=9",
            "rag_params": {"top_k": 9, "alpha": 0.1, "retrieval_mode": "keyword"},
        },
    ]


def test_main_runs_base_then_variants_and_writes_expected_artifacts(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    cases_path = tmp_path / "cases.json"
    matrix_path = tmp_path / "matrix.json"
    out_dir = tmp_path / "out"
    _write_bundle(cases_path)
    _write_matrix(matrix_path)

    calls: list[dict[str, Any]] = []
    poll_calls: list[str] = []
    plan = [
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/cases/import",
            "json": {"created": 1, "updated": 0, "skipped": 0, "errors": []},
        },
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs",
            "json": {"id": "base-run-001"},
        },
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs",
            "json": {"id": "variant-run-001"},
        },
        {
            "method": "GET",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs/variant-run-001/diff",
            "json": {"summary_delta": {"retrieval_recall": 0.1}},
        },
        {
            "method": "GET",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs/variant-run-001/diff/export-html",
            "text": "<html>alpha</html>",
        },
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs",
            "json": {"id": "variant-run-002"},
        },
        {
            "method": "GET",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs/variant-run-002/diff",
            "json": {"summary_delta": {"retrieval_recall": -0.2}},
        },
        {
            "method": "GET",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs/variant-run-002/diff/export-html",
            "text": "<html>beta</html>",
        },
    ]

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(plan=plan, calls=calls),
    )
    monkeypatch.setattr(
        module,
        "_resolve_case_ids",
        lambda **_kwargs: ["case-1"],
    )

    def _fake_poll_run(**kwargs: Any) -> dict[str, Any]:
        run_id = str(kwargs["run_id"])
        poll_calls.append(run_id)
        summaries = {
            "base-run-001": {"retrieval_recall": 0.5, "items": 1},
            "variant-run-001": {
                "retrieval_recall": 0.9,
                "retrieval_hit_at_20": 0.8,
                "retrieval_mrr": 0.7,
                "retrieval_ndcg_at_20": 0.6,
                "abstain_rate": 0.0,
                "items": 1,
            },
            "variant-run-002": {
                "retrieval_recall": 0.3,
                "retrieval_hit_at_20": 0.4,
                "retrieval_mrr": 0.2,
                "retrieval_ndcg_at_20": 0.1,
                "abstain_rate": 0.1,
                "items": 1,
            },
        }
        return {"run": {"summary": summaries[run_id]}}

    monkeypatch.setattr(module, "_poll_run", _fake_poll_run)
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "retrieval_ablation.py",
            "--base-url",
            "http://example.test/api/v1",
            "--user-id",
            "user-1",
            "--cases",
            str(cases_path),
            "--matrix",
            str(matrix_path),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert module.main() == 0

    stdout = capsys.readouterr().out
    assert poll_calls == ["base-run-001", "variant-run-001", "variant-run-002"]
    assert [call["method"] for call in calls] == [
        "POST",
        "POST",
        "POST",
        "GET",
        "GET",
        "POST",
        "GET",
        "GET",
    ]
    assert "base run started: base id=base-run-001" in stdout
    assert "variant started: alpha id=variant-run-001" in stdout
    assert "variant started: beta id=variant-run-002" in stdout
    assert "base ignored rag_params keys: ignored_base" in stdout
    assert "alpha ignored rag_params keys: ignored_base, ignored_variant" in stdout
    assert "done. variants=2 out_dir=" in stdout

    plan_json = json.loads((out_dir / "plan.resolved.json").read_text(encoding="utf-8"))
    assert plan_json == {
        "dataset_id": "dataset-1",
        "base": {
            "label": "base",
            "rag_params": {"top_k": 5, "ignored_base": "drop-me"},
        },
        "variants": [
            {
                "label": "alpha",
                "rag_params": {
                    "top_k": 7,
                    "ignored_base": "drop-me",
                    "ignored_variant": "x",
                },
            },
            {
                "label": "beta",
                "rag_params": {
                    "top_k": 5,
                    "ignored_base": "drop-me",
                    "enable_multi_query": True,
                },
            },
        ],
        "run_param_fields": list(module._RUN_PARAM_FIELDS),
    }

    alpha_post = calls[2]["json"]
    beta_post = calls[5]["json"]
    assert alpha_post == {
        "case_ids": ["case-1"],
        "dataset_id": "dataset-1",
        "metrics": [],
        "skip_empty_contexts": True,
        "max_cases": 1,
        "top_k": 7,
    }
    assert beta_post == {
        "case_ids": ["case-1"],
        "dataset_id": "dataset-1",
        "metrics": [],
        "skip_empty_contexts": True,
        "max_cases": 1,
        "top_k": 5,
        "enable_multi_query": True,
    }

    leaderboard = json.loads((out_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert leaderboard["base"] == {"label": "base", "run_id": "base-run-001"}
    assert [row["label"] for row in leaderboard["rows"]] == ["alpha", "beta"]
    assert leaderboard["failures"] == []

    alpha_run = json.loads((out_dir / "runs" / "alpha.variant-.run.json").read_text(encoding="utf-8"))
    assert alpha_run == {
        "label": "alpha",
        "run_id": "variant-run-001",
        "rag_params": {
            "top_k": 7,
            "ignored_base": "drop-me",
            "ignored_variant": "x",
        },
        "summary": {
            "retrieval_recall": 0.9,
            "retrieval_hit_at_20": 0.8,
            "retrieval_mrr": 0.7,
            "retrieval_ndcg_at_20": 0.6,
            "abstain_rate": 0.0,
            "items": 1,
        },
    }
    assert (out_dir / "diffs" / "alpha.variant-.diff.html").read_text(encoding="utf-8") == "<html>alpha</html>"


def test_main_returns_one_and_reports_variant_failures(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    cases_path = tmp_path / "cases.json"
    matrix_path = tmp_path / "matrix.json"
    out_dir = tmp_path / "out"
    _write_bundle(cases_path)
    _write_matrix(matrix_path)

    calls: list[dict[str, Any]] = []
    plan = [
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/cases/import",
            "json": {"created": 1, "updated": 0, "skipped": 0, "errors": []},
        },
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs",
            "json": {"id": "base-run-001"},
        },
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs",
            "json": {"id": "variant-run-001"},
        },
        {
            "method": "GET",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs/variant-run-001/diff",
            "json": {"summary_delta": {"retrieval_recall": 0.1}},
        },
        {
            "method": "GET",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs/variant-run-001/diff/export-html",
            "text": "<html>alpha</html>",
        },
        {
            "method": "POST",
            "url": "http://example.test/api/v1/evaluations/ragas/regression/runs",
            "exception": RuntimeError("boom"),
        },
    ]

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **_kwargs: _FakeClient(plan=plan, calls=calls),
    )
    monkeypatch.setattr(module, "_resolve_case_ids", lambda **_kwargs: ["case-1"])
    monkeypatch.setattr(
        module,
        "_poll_run",
        lambda **kwargs: {
            "run": {
                "summary": {
                    "retrieval_recall": 0.5 if kwargs["run_id"] == "base-run-001" else 0.9,
                    "items": 1,
                }
            }
        },
    )
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "retrieval_ablation.py",
            "--base-url",
            "http://example.test/api/v1",
            "--user-id",
            "user-1",
            "--cases",
            str(cases_path),
            "--matrix",
            str(matrix_path),
            "--out-dir",
            str(out_dir),
        ],
    )

    assert module.main() == 1

    captured = capsys.readouterr()
    assert "ERROR: beta: RuntimeError: boom" in captured.err
    assert "completed with failures: 1" in captured.err
    leaderboard = json.loads((out_dir / "leaderboard.json").read_text(encoding="utf-8"))
    assert leaderboard["failures"] == ["beta: RuntimeError: boom"]
    assert [row["label"] for row in leaderboard["rows"]] == ["alpha"]

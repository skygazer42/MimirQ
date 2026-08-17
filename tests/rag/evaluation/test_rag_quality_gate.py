import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_module(name: str, relative_path: str):
    path = _repo_root() / relative_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_build_retrieval_ranking_proxy_summary_is_honest() -> None:
    mod = _load_module("build_rag_quality_gate_artifacts", "scripts/build_rag_quality_gate_artifacts.py")
    payload = mod.build_retrieval_ranking_proxy_summary(  # type: ignore[attr-defined]
        {"summary": {"mrr": 0.81, "ndcg_at_k": 0.73, "hit_at_k": 0.92}}
    )
    assert payload == {
        "schema": "mimirq.retrieval_ranking_proxy_summary.v1",
        "retrieval_mrr": pytest.approx(0.81),
        "retrieval_ndcg_at_k": pytest.approx(0.73),
        "retrieval_hit_at_k": pytest.approx(0.92),
    }


def test_build_retrieval_ranking_proxy_gate_report_uses_retrieval_metrics() -> None:
    mod = _load_module("build_rag_quality_gate_artifacts", "scripts/build_rag_quality_gate_artifacts.py")
    report = mod.build_retrieval_ranking_proxy_gate_report(  # type: ignore[attr-defined]
        {
            "retrieval_mrr": 0.81,
            "retrieval_ndcg_at_k": 0.72,
            "retrieval_hit_at_k": 0.91,
        },
        summary_path="artifacts/retrieval_ranking_proxy.summary.json",
        thresholds={
            "retrieval_mrr": {"min": 0.8},
            "retrieval_ndcg_at_k": {"min": 0.75},
            "retrieval_hit_at_k": {"min": 0.7},
        },
    )

    assert report["schema"] == "mimirq.retrieval_ranking_proxy_gate_report.v1"
    assert report["summary_path"] == "artifacts/retrieval_ranking_proxy.summary.json"
    assert report["checks"]["retrieval_mrr"]["passed"] is True
    assert report["checks"]["retrieval_ndcg_at_k"]["passed"] is False
    assert report["passed"] is False


def test_retrieval_proxy_cli_uses_real_threshold_file_and_fails_closed(tmp_path: Path) -> None:
    mod = _load_module("build_rag_quality_gate_artifacts_cli", "scripts/build_rag_quality_gate_artifacts.py")
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text(
        json.dumps({"summary": {"mrr": 0.2, "ndcg_at_k": 0.3, "hit_at_k": 0.4}}),
        encoding="utf-8",
    )
    summary_out = tmp_path / "summary.json"
    report_out = tmp_path / "report.json"

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--benchmark",
            str(benchmark),
            "--thresholds",
            str(_repo_root() / "ci/retrieval_thresholds.v2.json"),
            "--summary-out",
            str(summary_out),
            "--report-out",
            str(report_out),
        ]
    )

    report = json.loads(report_out.read_text(encoding="utf-8"))
    assert rc == 2
    assert report["passed"] is False
    assert report["checks"]["retrieval_mrr"]["min"] == pytest.approx(1.0)
    assert report["checks"]["retrieval_mrr"]["reason"] == "lt_min"


def test_retrieval_proxy_report_fails_when_metric_or_threshold_is_missing() -> None:
    mod = _load_module("build_rag_quality_gate_artifacts_missing", "scripts/build_rag_quality_gate_artifacts.py")

    report = mod.build_retrieval_ranking_proxy_gate_report(  # type: ignore[attr-defined]
        {"retrieval_mrr": None},
        summary_path="summary.json",
        thresholds={"retrieval_mrr": {"min": 0.5}},
    )

    assert report["passed"] is False
    assert report["checks"]["retrieval_mrr"]["reason"] == "missing_metric"
    assert report["checks"]["retrieval_ndcg_at_k"]["reason"] == "missing_threshold"


def test_build_answer_quality_summary_reads_regression_run_shape(tmp_path: Path) -> None:
    mod = _load_module("build_answer_quality_summary", "scripts/build_answer_quality_summary.py")
    run_path = tmp_path / "run.json"
    run_path.write_text(
        json.dumps(
            {
                "run": {
                    "summary": {
                        "llm_judge_items": 5,
                        "llm_judge_model_used": "provider/model-v1",
                        "llm_judge_version_hash": "judge-hash-v2",
                        "llm_judge_self_consistency_n": 3,
                        "llm_judge_position_bias_enabled": True,
                        "llm_judge_generation_avg": 0.71,
                        "llm_judge_overall_avg": 0.69,
                        "faithfulness_det": 0.33,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    out_path = tmp_path / "summary.json"

    rc = mod.main(["--input", str(run_path), "--out", str(out_path)])  # type: ignore[attr-defined]

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.answer_quality_summary.v2"
    assert payload["llm_judge_items"] == 5
    assert payload["llm_judge_model_used"] == "provider/model-v1"
    assert payload["llm_judge_version_hash"] == "judge-hash-v2"
    assert payload["llm_judge_generation_avg"] == pytest.approx(0.71)
    assert payload["llm_judge_overall_avg"] == pytest.approx(0.69)
    assert payload["faithfulness_det"] == pytest.approx(0.33)


def test_answer_quality_workflow_is_real_provider_nightly_and_pr_ci_is_deterministic() -> None:
    nightly = (_repo_root() / ".github/workflows/rag-quality-gate.yml").read_text(encoding="utf-8")
    ci = (_repo_root() / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Nightly Real-Provider Answer Quality Gate" in nightly
    assert "schedule:" in nightly
    assert 'LLM_MOCK_ENABLED: "false"' in nightly
    assert "secrets.RAG_EVAL_LLM_API_KEY" in nightly
    assert "vars.RAG_EVAL_LLM_API_BASE" in nightly
    assert "vars.RAG_EVAL_LLM_MODEL" in nightly
    assert "Require explicit real-provider configuration" in nightly
    assert "--use-llm-judge" in nightly
    assert "scripts/build_answer_quality_summary.py" in nightly
    assert "scripts/answer_quality_gate.py" in nightly
    assert "artifacts/answer_quality.summary.json" in nightly
    assert "artifacts/answer_quality.gate.json" in nightly

    assert "PR deterministic retrieval-ranking proxy gate" in ci
    assert "artifacts/retrieval_ranking_proxy.summary.json" in ci
    assert "artifacts/retrieval_ranking_proxy_gate.report.json" in ci
    assert "Build deterministic retrieval-ranking proxy artifact" in ci
    assert (
        "artifacts/answer_quality.summary.json"
        not in ci.split("retrieval-only-bounded-gate:", 1)[1].split("retrieval-regression-gate:", 1)[0]
    )

    thresholds = json.loads((_repo_root() / "ci/answer_quality_thresholds.v1.json").read_text(encoding="utf-8"))
    assert thresholds["metrics"]["llm_judge_generation_avg"]["required"] is True
    assert thresholds["metrics"]["llm_judge_overall_avg"]["required"] is True


def test_ci_retrieval_fixture_does_not_claim_parser_or_ocr_coverage() -> None:
    fixture = json.loads((_repo_root() / "ci/retrieval_regression_fixture.v1.json").read_text(encoding="utf-8"))

    assert fixture["fixture_scope"] == "post_parse_retrieval"
    description = str(fixture["dataset"]["description"]).lower()
    assert "does not validate parser or ocr" in description

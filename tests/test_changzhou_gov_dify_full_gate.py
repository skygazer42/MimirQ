from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_module():
    path = Path("scripts/changzhou_gov_dify_full_gate.py")
    spec = importlib.util.spec_from_file_location("changzhou_gov_dify_full_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _workflow() -> dict:
    return {
        "graph": {
            "nodes": [
                {
                    "id": "1711528914102",
                    "data": {
                        "type": "start",
                        "title": "Start",
                        "variables": [
                            {
                                "label": "区域",
                                "required": False,
                                "type": "text-input",
                                "variable": "areaName",
                            }
                        ],
                    },
                },
                {
                    "id": "llm-1",
                    "data": {
                        "type": "llm",
                        "title": "回复",
                        "prompt_template": "区域：#1711528914102.areaName#",
                    },
                },
            ]
        }
    }


def test_run_gate_stops_before_dify_calls_when_case_inputs_are_missing() -> None:
    mod = _load_module()

    def must_not_collect(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("collect should not run")

    report = mod.run_gate(
        cases=[{"id": "bad-case", "query": "经开区社保卡补卡在哪里办理"}],
        workflow=_workflow(),
        collect_answers_fn=must_not_collect,
        live_eval_fn=lambda **_kwargs: {},
        trace_report_fn=lambda **_kwargs: {},
        thresholds={"generated_answer_key_point_recall": 1.0},
        maximums={"generated_answer_fallback_rate": 0.0},
    )

    assert report["summary"] == {
        "passed": False,
        "failed_stages": ["preflight"],
        "stage_count": 1,
    }
    assert report["stages"]["preflight"]["passed"] is False
    assert report["stages"]["preflight"]["summary"]["case_input_violations"] == 1


def test_run_gate_aggregates_collect_eval_and_trace_success() -> None:
    mod = _load_module()
    calls: list[str] = []

    def collect_answers_fn(**kwargs):  # noqa: ANN003, ANN202
        calls.append("collect")
        assert kwargs["cases"][0]["id"] == "ok-case"
        return {
            "summary": {"cases": 1, "succeeded": 1, "failed": 0},
            "answers": [{"id": "ok-case", "query": "q", "answer": "a", "message_id": "msg-1"}],
        }

    def live_eval_fn(**kwargs):  # noqa: ANN003, ANN202
        calls.append("eval")
        assert kwargs["answers"]["ok-case"]["answer"] == "a"
        return {
            "summary": {
                "cases": 1,
                "hit_at_3": 1.0,
                "generated_answer_key_point_recall": 1.0,
                "generated_answer_fallback_rate": 0.0,
            }
        }

    def trace_report_fn(**kwargs):  # noqa: ANN003, ANN202
        calls.append("trace")
        assert kwargs["answers"][0]["message_id"] == "msg-1"
        return {
            "summary": {
                "cases": 1,
                "traced": 1,
                "fallback_cases": 0,
                "empty_retrieval_cases": 0,
                "nonempty_retrieval_cases": 1,
                "trace_errors": 0,
            }
        }

    report = mod.run_gate(
        cases=[{"id": "ok-case", "query": "q", "dify_inputs": {"areaName": "经开区"}}],
        workflow=_workflow(),
        collect_answers_fn=collect_answers_fn,
        live_eval_fn=live_eval_fn,
        trace_report_fn=trace_report_fn,
        thresholds={"generated_answer_key_point_recall": 1.0},
        maximums={"generated_answer_fallback_rate": 0.0},
    )

    assert calls == ["collect", "eval", "trace"]
    assert report["summary"] == {
        "passed": True,
        "failed_stages": [],
        "stage_count": 4,
    }
    assert report["stages"]["preflight"]["passed"] is True
    assert report["stages"]["collect"]["passed"] is True
    assert report["stages"]["eval"]["passed"] is True
    assert report["stages"]["trace"]["passed"] is True


def test_thresholds_from_args_preserves_defaults_and_applies_overrides() -> None:
    mod = _load_module()
    parser = mod.build_arg_parser()

    args = parser.parse_args(
        [
            "--app-id",
            "app-1",
            "--out",
            "/tmp/report.json",
            "--min-hit-at-3",
            "0.8",
            "--min-generated-answer-key-point-recall",
            "0.9",
            "--max-generated-answer-fallback-rate",
            "0.2",
        ]
    )

    assert mod._thresholds_from_args(args) == {
        **mod.DEFAULT_THRESHOLDS,
        "hit_at_3": 0.8,
        "generated_answer_key_point_recall": 0.9,
    }
    assert mod._maximums_from_args(args) == {
        **mod.DEFAULT_MAXIMUMS,
        "generated_answer_fallback_rate": 0.2,
    }


def test_load_mimirq_token_prefers_explicit_env_then_env_file(tmp_path: Path) -> None:
    mod = _load_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS=file-first,file-second",
                "DIFY_EXTERNAL_KNOWLEDGE_API_KEY=file-single",
            ]
        ),
        encoding="utf-8",
    )

    assert mod.load_mimirq_token("explicit-token", env={"DIFY_EXTERNAL_KNOWLEDGE_API_KEY": "env-token"}, env_file=str(env_file)) == "explicit-token"
    assert mod.load_mimirq_token("", env={"DIFY_EXTERNAL_KNOWLEDGE_API_KEY": "env-token"}, env_file=str(env_file)) == "env-token"
    assert mod.load_mimirq_token("", env={}, env_file=str(env_file)) == "file-single"


def test_load_mimirq_token_uses_first_token_from_env_file_list(tmp_path: Path) -> None:
    mod = _load_module()
    env_file = tmp_path / ".env"
    env_file.write_text("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS=file-first, file-second\n", encoding="utf-8")

    assert mod.load_mimirq_token("", env={}, env_file=str(env_file)) == "file-first"


def test_load_mimirq_token_defaults_to_repo_root_env_file(tmp_path: Path) -> None:
    mod = _load_module()
    repo_root = tmp_path / "repo"
    other_cwd = tmp_path / "elsewhere"
    repo_root.mkdir()
    other_cwd.mkdir()
    (repo_root / ".env").write_text("DIFY_EXTERNAL_KNOWLEDGE_API_KEY=repo-root-token\n", encoding="utf-8")
    old_repo_root = mod.REPO_ROOT
    old_cwd = Path.cwd()
    try:
        mod.REPO_ROOT = repo_root
        os.chdir(other_cwd)
        assert mod.load_mimirq_token("", env={}, env_file="") == "repo-root-token"
    finally:
        os.chdir(old_cwd)
        mod.REPO_ROOT = old_repo_root


def test_compact_summary_keeps_stage_metrics_and_artifact_paths_without_full_reports() -> None:
    mod = _load_module()
    full_report = {
        "summary": {"passed": True, "failed_stages": [], "stage_count": 4},
        "stages": {
            "collect": {
                "passed": True,
                "summary": {"cases": 1, "succeeded": 1, "failed": 0},
                "report": {"answers": [{"id": "case-1", "answer": "large answer"}]},
            },
            "eval": {
                "passed": True,
                "summary": {"hit_at_3": 1.0, "generated_answer_key_point_recall": 1.0},
                "report": {"results": [{"id": "case-1", "matched_record": {"content": "large content"}}]},
            },
        },
    }

    summary = mod.compact_summary(
        full_report,
        artifacts={
            "full": "/tmp/full.json",
            "answers": "/tmp/answers.json",
            "eval": "/tmp/eval.json",
            "trace": "",
        },
    )

    assert summary == {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_full_gate.summary.v1",
        "summary": {"passed": True, "failed_stages": [], "stage_count": 4},
        "artifacts": {
            "full": "/tmp/full.json",
            "answers": "/tmp/answers.json",
            "eval": "/tmp/eval.json",
        },
        "stages": {
            "collect": {"passed": True, "summary": {"cases": 1, "succeeded": 1, "failed": 0}},
            "eval": {"passed": True, "summary": {"hit_at_3": 1.0, "generated_answer_key_point_recall": 1.0}},
        },
    }
    assert "large answer" not in str(summary)
    assert "large content" not in str(summary)


def test_write_stage_artifacts_skips_outputs_for_stages_that_did_not_run(tmp_path: Path) -> None:
    mod = _load_module()
    report = {
        "summary": {"passed": False, "failed_stages": ["preflight"], "stage_count": 1},
        "stages": {
            "preflight": {
                "passed": False,
                "summary": {"case_input_violations": 1},
                "report": {"summary": {"case_input_violations": 1}},
            }
        },
    }
    answers_path = tmp_path / "answers.json"
    eval_path = tmp_path / "eval.json"
    trace_path = tmp_path / "trace.json"

    artifacts = mod.write_stage_artifacts(
        report,
        answers_out=str(answers_path),
        eval_out=str(eval_path),
        trace_out=str(trace_path),
    )

    assert artifacts == {}
    assert not answers_path.exists()
    assert not eval_path.exists()
    assert not trace_path.exists()


def test_write_stage_artifacts_writes_only_present_stage_reports(tmp_path: Path) -> None:
    mod = _load_module()
    report = {
        "summary": {"passed": False, "failed_stages": ["eval"], "stage_count": 3},
        "stages": {
            "collect": {
                "passed": True,
                "summary": {"cases": 1, "succeeded": 1, "failed": 0},
                "report": {"summary": {"cases": 1}, "answers": [{"id": "case-1"}]},
            },
            "eval": {
                "passed": False,
                "summary": {"generated_answer_key_point_recall": 0.5},
                "report": {"summary": {"generated_answer_key_point_recall": 0.5}},
            },
        },
    }
    answers_path = tmp_path / "answers.json"
    eval_path = tmp_path / "eval.json"
    trace_path = tmp_path / "trace.json"

    artifacts = mod.write_stage_artifacts(
        report,
        answers_out=str(answers_path),
        eval_out=str(eval_path),
        trace_out=str(trace_path),
    )

    assert artifacts == {"answers": str(answers_path), "eval": str(eval_path)}
    assert json.loads(answers_path.read_text(encoding="utf-8"))["summary"] == {"cases": 1}
    assert json.loads(eval_path.read_text(encoding="utf-8"))["summary"] == {
        "generated_answer_key_point_recall": 0.5
    }
    assert not trace_path.exists()

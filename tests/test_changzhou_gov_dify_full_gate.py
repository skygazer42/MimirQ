from __future__ import annotations

import importlib.util
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

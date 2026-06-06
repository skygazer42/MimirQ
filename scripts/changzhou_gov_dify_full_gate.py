#!/usr/bin/env python3
"""Run the full Changzhou Dify/MimirQ golden gate.

The gate composes existing diagnostics in the order operators need them:
case-input preflight, Dify generated-answer collection, direct MimirQ golden
evaluation, and Dify workflow trace validation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.changzhou_gov_collect_dify_answers import (  # noqa: E402
    DEFAULT_API_KEY_FILE,
    DEFAULT_DIFY_BASE_URL,
    collect_answers,
    load_api_key,
)
from scripts.changzhou_gov_dify_trace_report import (  # noqa: E402
    DEFAULT_CONSOLE_BASE_URL,
    DEFAULT_STORAGE_STATE,
    collect_trace_report,
    load_console_token,
)
from scripts.changzhou_gov_dify_workflow_lint import _fetch_draft_workflow, lint_workflow  # noqa: E402
from scripts.changzhou_gov_golden_eval import (  # noqa: E402
    DEFAULT_CASES,
    evaluate_quality_gate,
    load_cases,
    run_live_eval,
)

CollectAnswersFn = Callable[..., dict[str, Any]]
LiveEvalFn = Callable[..., dict[str, Any]]
TraceReportFn = Callable[..., dict[str, Any]]

DEFAULT_THRESHOLDS = {
    "hit_at_3": 1.0,
    "answer_key_point_recall": 1.0,
    "generated_answer_grounding_rate": 1.0,
    "generated_answer_key_point_recall": 1.0,
    "generated_answer_context_supported_rate": 1.0,
}
DEFAULT_MAXIMUMS = {"generated_answer_fallback_rate": 0.0}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _env_file_values(path: str) -> dict[str, str]:
    env_path = Path(_text(path))
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_mimirq_token(
    explicit_token: str,
    *,
    env: Mapping[str, str] | None = None,
    env_file: str = "",
) -> str:
    explicit = _text(explicit_token)
    if explicit:
        return explicit
    source_env = env if env is not None else os.environ
    env_token = _text(source_env.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEY"))
    if env_token:
        return env_token
    env_tokens = _text(source_env.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"))
    if env_tokens:
        return _text(env_tokens.split(",", 1)[0])
    file_values = _env_file_values(env_file or str(REPO_ROOT / ".env"))
    file_token = _text(file_values.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEY"))
    if file_token:
        return file_token
    file_tokens = _text(file_values.get("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS"))
    if file_tokens:
        return _text(file_tokens.split(",", 1)[0])
    return ""


def _answers_by_id(answers_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in answers_report.get("answers") or []:
        if not isinstance(item, dict):
            continue
        case_id = _text(item.get("id") or item.get("case_id"))
        if case_id:
            out[case_id] = dict(item)
    return out


def _collect_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return int(summary.get("failed") or 0) == 0 and int(summary.get("succeeded") or 0) == int(summary.get("cases") or 0)


def _trace_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return (
        int(summary.get("trace_errors") or 0) == 0
        and int(summary.get("fallback_cases") or 0) == 0
        and int(summary.get("empty_retrieval_cases") or 0) == 0
        and int(summary.get("nonempty_retrieval_cases") or 0) == int(summary.get("cases") or 0)
    )


def _stage(passed: bool, report: dict[str, Any]) -> dict[str, Any]:
    return {"passed": bool(passed), "summary": report.get("summary") or {}, "report": report}


def _finalize(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    failed = [name for name, stage in stages.items() if stage.get("passed") is not True]
    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_full_gate.v1",
        "summary": {
            "passed": not failed,
            "failed_stages": failed,
            "stage_count": len(stages),
        },
        "stages": stages,
    }


def run_gate(
    *,
    cases: list[dict[str, Any]],
    workflow: dict[str, Any],
    collect_answers_fn: CollectAnswersFn,
    live_eval_fn: LiveEvalFn,
    trace_report_fn: TraceReportFn,
    thresholds: dict[str, float] | None = None,
    maximums: dict[str, float] | None = None,
    collect_kwargs: dict[str, Any] | None = None,
    eval_kwargs: dict[str, Any] | None = None,
    trace_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    preflight = lint_workflow(workflow, cases=cases)
    preflight_passed = int((preflight.get("summary") or {}).get("case_input_violations") or 0) == 0
    stages["preflight"] = _stage(preflight_passed, preflight)
    if not preflight_passed:
        return _finalize(stages)

    answers_report = collect_answers_fn(cases=cases, **(collect_kwargs or {}))
    stages["collect"] = _stage(_collect_passed(answers_report), answers_report)
    if stages["collect"]["passed"] is not True:
        return _finalize(stages)

    eval_report = live_eval_fn(cases=cases, answers=_answers_by_id(answers_report), **(eval_kwargs or {}))
    eval_summary = eval_report.get("summary") if isinstance(eval_report.get("summary"), dict) else {}
    eval_report["gate"] = evaluate_quality_gate(
        eval_summary,
        thresholds or DEFAULT_THRESHOLDS,
        maximums or DEFAULT_MAXIMUMS,
    )
    stages["eval"] = _stage(bool((eval_report.get("gate") or {}).get("passed")), eval_report)
    if stages["eval"]["passed"] is not True:
        return _finalize(stages)

    answers = answers_report.get("answers") if isinstance(answers_report.get("answers"), list) else []
    trace_report = trace_report_fn(answers=answers, **(trace_kwargs or {}))
    stages["trace"] = _stage(_trace_passed(trace_report), trace_report)
    return _finalize(stages)


def _write_optional(path: str, payload: dict[str, Any]) -> None:
    if not _text(path):
        return
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _stage_report(report: dict[str, Any], stage_name: str) -> dict[str, Any]:
    stages = report.get("stages") if isinstance(report.get("stages"), dict) else {}
    stage = stages.get(stage_name) if isinstance(stages.get(stage_name), dict) else {}
    payload = stage.get("report") if isinstance(stage.get("report"), dict) else {}
    return payload


def write_stage_artifacts(
    report: dict[str, Any],
    *,
    answers_out: str = "",
    eval_out: str = "",
    trace_out: str = "",
) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for artifact_name, stage_name, path in (
        ("answers", "collect", answers_out),
        ("eval", "eval", eval_out),
        ("trace", "trace", trace_out),
    ):
        payload = _stage_report(report, stage_name)
        if not payload or not _text(path):
            continue
        _write_optional(path, payload)
        artifacts[artifact_name] = path
    return artifacts


def compact_summary(report: dict[str, Any], *, artifacts: dict[str, str] | None = None) -> dict[str, Any]:
    stages: dict[str, Any] = {}
    for name, stage in (report.get("stages") or {}).items():
        if not isinstance(stage, dict):
            continue
        stages[name] = {
            "passed": bool(stage.get("passed")),
            "summary": stage.get("summary") if isinstance(stage.get("summary"), dict) else {},
        }
    clean_artifacts = {key: value for key, value in (artifacts or {}).items() if _text(value)}
    return {
        "schema": "mimirq.changzhou_gov_service_knowledge.dify_full_gate.summary.v1",
        "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
        "artifacts": clean_artifacts,
        "stages": stages,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full Changzhou Dify/MimirQ golden gate.")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--dify-base-url", default=os.getenv("DIFY_API_BASE_URL") or DEFAULT_DIFY_BASE_URL)
    parser.add_argument("--dify-api-key", default=os.getenv("DIFY_APP_API_KEY") or "")
    parser.add_argument("--dify-api-key-file", default=DEFAULT_API_KEY_FILE)
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--console-base-url", default=os.getenv("DIFY_CONSOLE_API_BASE_URL") or DEFAULT_CONSOLE_BASE_URL)
    parser.add_argument("--console-token", default=os.getenv("DIFY_CONSOLE_TOKEN") or "")
    parser.add_argument("--storage-state", default=DEFAULT_STORAGE_STATE)
    parser.add_argument("--mimirq-base-url", default=os.getenv("MIMIRQ_API_BASE_URL") or "http://127.0.0.1:8000")
    parser.add_argument("--mimirq-token", default=os.getenv("DIFY_EXTERNAL_KNOWLEDGE_API_KEY") or "")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--interval-sec", type=float, default=0.0)
    parser.add_argument("--user", default="mimirq-full-gate")
    parser.add_argument("--min-hit-at-1", type=float, default=None)
    parser.add_argument("--min-hit-at-3", type=float, default=None)
    parser.add_argument("--min-hit-at-5", type=float, default=None)
    parser.add_argument("--min-mrr", type=float, default=None)
    parser.add_argument("--min-answer-grounding-rate", type=float, default=None)
    parser.add_argument("--min-answer-key-point-recall", type=float, default=None)
    parser.add_argument("--min-generated-answer-grounding-rate", type=float, default=None)
    parser.add_argument("--min-generated-answer-key-point-recall", type=float, default=None)
    parser.add_argument("--min-generated-answer-context-supported-rate", type=float, default=None)
    parser.add_argument("--max-generated-answer-fallback-rate", type=float, default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--answers-out", default="")
    parser.add_argument("--eval-out", default="")
    parser.add_argument("--trace-out", default="")
    parser.add_argument("--summary-out", default="")
    return parser


def _thresholds_from_args(args: argparse.Namespace) -> dict[str, float]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    pairs = {
        "hit_at_1": args.min_hit_at_1,
        "hit_at_3": args.min_hit_at_3,
        "hit_at_5": args.min_hit_at_5,
        "mrr": args.min_mrr,
        "answer_grounding_rate": args.min_answer_grounding_rate,
        "answer_key_point_recall": args.min_answer_key_point_recall,
        "generated_answer_grounding_rate": args.min_generated_answer_grounding_rate,
        "generated_answer_key_point_recall": args.min_generated_answer_key_point_recall,
        "generated_answer_context_supported_rate": args.min_generated_answer_context_supported_rate,
    }
    thresholds.update({metric: float(value) for metric, value in pairs.items() if value is not None})
    return thresholds


def _maximums_from_args(args: argparse.Namespace) -> dict[str, float]:
    maximums = dict(DEFAULT_MAXIMUMS)
    pairs = {
        "generated_answer_fallback_rate": args.max_generated_answer_fallback_rate,
    }
    maximums.update({metric: float(value) for metric, value in pairs.items() if value is not None})
    return maximums


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    dify_api_key = load_api_key(str(args.dify_api_key), str(args.dify_api_key_file))
    console_token = load_console_token(str(args.console_token), str(args.storage_state))
    mimirq_token = load_mimirq_token(str(args.mimirq_token), env_file=str(REPO_ROOT / ".env"))
    if not dify_api_key:
        print("DIFY_APP_API_KEY, --dify-api-key, or --dify-api-key-file is required", file=sys.stderr)
        return 2
    if not console_token:
        print("DIFY_CONSOLE_TOKEN, --console-token, or --storage-state with console_token is required", file=sys.stderr)
        return 2
    if not mimirq_token:
        print("DIFY_EXTERNAL_KNOWLEDGE_API_KEY or --mimirq-token is required", file=sys.stderr)
        return 2

    try:
        cases = load_cases(str(args.cases))
        workflow = _fetch_draft_workflow(
            app_id=str(args.app_id),
            console_base_url=str(args.console_base_url),
            console_token=console_token,
            timeout=float(args.timeout),
        )
        report = run_gate(
            cases=cases,
            workflow=workflow,
            collect_answers_fn=collect_answers,
            live_eval_fn=run_live_eval,
            trace_report_fn=collect_trace_report,
            collect_kwargs={
                "base_url": str(args.dify_base_url),
                "api_key": dify_api_key,
                "mode": "chat",
                "user": str(args.user),
                "response_mode": "blocking",
                "workflow_query_key": "query",
                "timeout": float(args.timeout),
                "interval_sec": float(args.interval_sec),
            },
            eval_kwargs={
                "base_url": str(args.mimirq_base_url),
                "token": mimirq_token,
                "top_k": int(args.top_k),
                "timeout": float(args.timeout),
            },
            trace_kwargs={
                "app_id": str(args.app_id),
                "console_base_url": str(args.console_base_url),
                "console_token": console_token,
                "timeout": float(args.timeout),
            },
            thresholds=_thresholds_from_args(args),
            maximums=_maximums_from_args(args),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[changzhou-dify-full-gate] ERR: {exc}", file=sys.stderr)
        return 1

    artifacts = write_stage_artifacts(
        report,
        answers_out=str(args.answers_out),
        eval_out=str(args.eval_out),
        trace_out=str(args.trace_out),
    )
    artifacts["full"] = str(args.out)
    summary_report = compact_summary(
        report,
        artifacts=artifacts,
    )
    _write_optional(str(args.summary_out), summary_report)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(str(args.out)).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if bool((report.get("summary") or {}).get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())

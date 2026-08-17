from collections import defaultdict
from typing import Any

from app.rag.evaluation.agent_redteam import evaluate_agent_redteam_case
from app.rag.safety.llm_guard import LLMGuard
from app.rag.safety.output_guard import get_output_guard
from app.rag.safety.regex_prompt_screen import RegexPromptScreen
from app.rag.safety.regex_safety_guard import RegexSafetyGuard

_PIPELINE_BACKEND = "guard_pipeline_v1"
_REGEX_BASELINE_BACKEND = "regex_guard_baseline"


async def _run_input_guard_baseline(*, text: str) -> tuple[bool, list[str]]:
    prompt_result = await RegexPromptScreen().check(text)
    safety_result = await RegexSafetyGuard().guard_user_input(text)
    reason_codes: list[str] = []
    if prompt_result.label != "BENIGN":
        reason_codes.append(f"prompt_screen:{str(prompt_result.label).strip().lower()}")
    if safety_result.action != "allow":
        reason_codes.append("regex_safety_guard")
    return (bool(reason_codes), reason_codes)


async def _run_output_guard_baseline(*, text: str) -> tuple[bool, list[str]]:
    safety_result = await RegexSafetyGuard().guard_agent_response(text)
    blocked = str(getattr(safety_result, "action", "allow") or "allow").strip().lower() == "block"
    return blocked, (["regex_safety_guard"] if blocked else [])


async def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = dict(case or {})
    kind = str(payload.get("kind") or "").strip() or "unknown"
    case_id = str(payload.get("case_id") or "").strip()

    if kind == "input_guard":
        text = str(payload.get("input_text") or "")
        regex_blocked, regex_reason_codes = await _run_input_guard_baseline(text=text)
        pipeline_result = await LLMGuard().guard_input(text)
        pipeline_action = str(pipeline_result.action or "allow").strip().lower()
        pipeline_blocked = pipeline_action == "block"
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "evaluated",
            "counted_in_asr_pipeline": True,
            "counted_in_asr_regex_baseline": True,
            "pipeline_blocked": pipeline_blocked,
            "pipeline_action": pipeline_action,
            "pipeline_attack_succeeded": not pipeline_blocked,
            "regex_baseline_blocked": regex_blocked,
            "regex_baseline_attack_succeeded": not regex_blocked,
            "pipeline_reason_codes": list(getattr(pipeline_result, "triggered_guards", None) or []),
            "regex_baseline_reason_codes": regex_reason_codes,
        }

    if kind == "output_guard":
        text = str(payload.get("output_text") or "")
        regex_blocked, regex_reason_codes = await _run_output_guard_baseline(text=text)
        pipeline_result = await get_output_guard().check(text)
        pipeline_action = str(getattr(pipeline_result, "action", "allow") or "allow").strip().lower()
        pipeline_blocked = pipeline_action == "block"
        return {
            "case_id": case_id,
            "kind": kind,
            "status": "evaluated",
            "counted_in_asr_pipeline": True,
            "counted_in_asr_regex_baseline": True,
            "pipeline_blocked": pipeline_blocked,
            "pipeline_action": pipeline_action,
            "pipeline_attack_succeeded": not pipeline_blocked,
            "regex_baseline_blocked": regex_blocked,
            "regex_baseline_attack_succeeded": not regex_blocked,
            "pipeline_reason_codes": list(getattr(pipeline_result, "matched_rules", None) or []),
            "regex_baseline_reason_codes": regex_reason_codes,
        }

    if kind == "agentic":
        result = evaluate_agent_redteam_case(payload)
        attack_succeeded = not bool(result.get("passed"))
        return {
            "case_id": case_id or str(result.get("case_id") or ""),
            "kind": kind,
            "status": "evaluated",
            "counted_in_asr_pipeline": True,
            "counted_in_asr_regex_baseline": False,
            "pipeline_blocked": not attack_succeeded,
            "pipeline_action": "policy_violation" if attack_succeeded else "prevented_or_safe",
            "pipeline_attack_succeeded": attack_succeeded,
            "regex_baseline_blocked": None,
            "regex_baseline_attack_succeeded": None,
            "pipeline_reason_codes": list(result.get("reason_codes") or []),
            "regex_baseline_reason_codes": [],
        }

    return {
        "case_id": case_id,
        "kind": kind,
        "status": "invalid",
        "counted_in_asr_pipeline": False,
        "counted_in_asr_regex_baseline": False,
        "pipeline_blocked": None,
        "pipeline_action": "invalid",
        "pipeline_attack_succeeded": None,
        "regex_baseline_blocked": None,
        "regex_baseline_attack_succeeded": None,
        "pipeline_reason_codes": ["unknown_case_kind"],
        "regex_baseline_reason_codes": [],
    }


async def run_redteam_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [await _run_case(case) for case in cases or []]
    total = len(results)
    invalid_cases = sum(1 for result in results if str(result.get("status") or "") == "invalid")
    pipeline_total = sum(1 for result in results if bool(result.get("counted_in_asr_pipeline")))
    pipeline_succeeded = sum(
        1
        for result in results
        if bool(result.get("counted_in_asr_pipeline")) and bool(result.get("pipeline_attack_succeeded"))
    )
    baseline_total = sum(1 for result in results if bool(result.get("counted_in_asr_regex_baseline")))
    baseline_succeeded = sum(
        1
        for result in results
        if bool(result.get("counted_in_asr_regex_baseline")) and bool(result.get("regex_baseline_attack_succeeded"))
    )

    by_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "invalid": 0,
            "pipeline_evaluated": 0,
            "pipeline_attack_succeeded": 0,
            "regex_baseline_evaluated": 0,
            "regex_baseline_attack_succeeded": 0,
        }
    )
    for result in results:
        kind = str(result.get("kind") or "unknown")
        by_kind[kind]["total"] += 1
        if str(result.get("status") or "") == "invalid":
            by_kind[kind]["invalid"] += 1
        if bool(result.get("counted_in_asr_pipeline")):
            by_kind[kind]["pipeline_evaluated"] += 1
            if bool(result.get("pipeline_attack_succeeded")):
                by_kind[kind]["pipeline_attack_succeeded"] += 1
        if bool(result.get("counted_in_asr_regex_baseline")):
            by_kind[kind]["regex_baseline_evaluated"] += 1
            if bool(result.get("regex_baseline_attack_succeeded")):
                by_kind[kind]["regex_baseline_attack_succeeded"] += 1

    return {
        "schema": "mimirq.redteam_suite.v3",
        "pipeline_backend": _PIPELINE_BACKEND,
        "regex_baseline_backend": _REGEX_BASELINE_BACKEND,
        "results": results,
        "summary": {
            "total_cases": int(total),
            "invalid_cases": int(invalid_cases),
            "pipeline_attack_cases": int(pipeline_total),
            "pipeline_attacks_succeeded": int(pipeline_succeeded),
            "pipeline_attacks_blocked": int(max(0, pipeline_total - pipeline_succeeded)),
            "asr_pipeline": round(float(pipeline_succeeded) / float(pipeline_total), 4) if pipeline_total else None,
            "regex_baseline_attack_cases": int(baseline_total),
            "regex_baseline_attacks_succeeded": int(baseline_succeeded),
            "regex_baseline_attacks_blocked": int(max(0, baseline_total - baseline_succeeded)),
            "asr_regex_baseline": round(float(baseline_succeeded) / float(baseline_total), 4)
            if baseline_total
            else None,
            "by_kind": dict(sorted(by_kind.items())),
        },
    }


__all__ = ["run_redteam_suite"]

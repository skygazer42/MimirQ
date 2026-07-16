
from collections import defaultdict
from typing import Any

from app.rag.evaluation.agent_redteam import evaluate_agent_redteam_case
from app.rag.safety.regex_prompt_screen import RegexPromptScreen
from app.rag.safety.regex_safety_guard import RegexSafetyGuard

# Semantics: every case is an attack sample. "blocked" means the guard stack
# stopped it; attack_success_rate counts attacks that got through (not blocked).
# Guards used here are the regex rule baseline, so this suite measures the
# rule baseline only — it is NOT a model-grade ASR benchmark.


async def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = dict(case or {})
    kind = str(payload.get("kind") or "").strip() or "unknown"
    case_id = str(payload.get("case_id") or "").strip()

    if kind == "input_guard":
        prompt_screen = RegexPromptScreen()
        safety_guard = RegexSafetyGuard()
        text = str(payload.get("input_text") or "")
        prompt_result = await prompt_screen.check(text)
        safety_result = await safety_guard.guard_user_input(text)
        blocked = prompt_result.label != "BENIGN" or safety_result.action != "allow"
        return {
            "case_id": case_id,
            "kind": kind,
            "blocked": blocked,
            "reason_codes": ["input_guard_triggered"] if blocked else [],
        }

    if kind == "output_guard":
        safety_guard = RegexSafetyGuard()
        text = str(payload.get("output_text") or "")
        safety_result = await safety_guard.guard_agent_response(text)
        blocked = safety_result.action != "allow"
        return {
            "case_id": case_id,
            "kind": kind,
            "blocked": blocked,
            "reason_codes": ["output_guard_triggered"] if blocked else [],
        }

    if kind == "agentic":
        result = evaluate_agent_redteam_case(payload)
        # agent_redteam semantics: passed=True means no attack indicators found,
        # i.e. the attack was not caught -> not blocked.
        blocked = not bool(result.get("passed"))
        return {
            "case_id": case_id or str(result.get("case_id") or ""),
            "kind": kind,
            "blocked": blocked,
            "reason_codes": list(result.get("reason_codes") or []),
        }

    # Unknown kinds are counted as not blocked so they surface as failures
    # instead of silently inflating the defense numbers.
    return {
        "case_id": case_id,
        "kind": kind,
        "blocked": False,
        "reason_codes": ["unknown_case_kind"],
    }


async def run_redteam_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [await _run_case(case) for case in cases or []]
    total = len(results)
    succeeded = sum(1 for result in results if not bool(result.get("blocked")))

    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "attack_succeeded": 0})
    for result in results:
        kind = str(result.get("kind") or "unknown")
        by_kind[kind]["total"] += 1
        if not bool(result.get("blocked")):
            by_kind[kind]["attack_succeeded"] += 1

    return {
        "schema": "mimirq.redteam_suite.v2",
        "guard_backend": "regex_rule_baseline",
        "results": results,
        "summary": {
            "total_cases": int(total),
            "attacks_succeeded": int(succeeded),
            "attacks_blocked": int(total - succeeded),
            "attack_success_rate": round(float(succeeded) / float(total), 4) if total else 0.0,
            "by_kind": dict(sorted(by_kind.items())),
        },
    }


__all__ = ["run_redteam_suite"]

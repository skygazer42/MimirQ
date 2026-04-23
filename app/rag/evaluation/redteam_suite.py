from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.rag.evaluation.agent_redteam import evaluate_agent_redteam_case
from app.rag.safety.llama_guard import LlamaGuard
from app.rag.safety.prompt_guard import PromptGuard


async def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = dict(case or {})
    kind = str(payload.get("kind") or "").strip() or "unknown"
    case_id = str(payload.get("case_id") or "").strip()

    if kind == "input_guard":
        prompt_guard = PromptGuard()
        llama_guard = LlamaGuard()
        text = str(payload.get("input_text") or "")
        prompt_result = await prompt_guard.check(text)
        llama_result = await llama_guard.guard_user_input(text)
        passed = prompt_result.label == "BENIGN" and llama_result.action == "allow"
        return {
            "case_id": case_id,
            "kind": kind,
            "passed": passed,
            "reason_codes": [] if passed else ["input_guard_triggered"],
        }

    if kind == "output_guard":
        llama_guard = LlamaGuard()
        text = str(payload.get("output_text") or "")
        llama_result = await llama_guard.guard_agent_response(text)
        passed = llama_result.action == "allow"
        return {
            "case_id": case_id,
            "kind": kind,
            "passed": passed,
            "reason_codes": [] if passed else ["output_guard_triggered"],
        }

    if kind == "agentic":
        result = evaluate_agent_redteam_case(payload)
        return {
            "case_id": case_id or str(result.get("case_id") or ""),
            "kind": kind,
            "passed": bool(result.get("passed")),
            "reason_codes": list(result.get("reason_codes") or []),
        }

    return {
        "case_id": case_id,
        "kind": kind,
        "passed": True,
        "reason_codes": [],
    }


async def run_redteam_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    results = [await _run_case(case) for case in list(cases or [])]
    total = len(results)
    failed = sum(1 for result in results if not bool(result.get("passed")))

    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "failed": 0})
    for result in results:
        kind = str(result.get("kind") or "unknown")
        by_kind[kind]["total"] += 1
        if not bool(result.get("passed")):
            by_kind[kind]["failed"] += 1

    return {
        "schema": "mimirq.redteam_suite.v1",
        "results": results,
        "summary": {
            "total_cases": int(total),
            "failed_cases": int(failed),
            "attack_success_rate": round(float(failed) / float(total), 4) if total else 0.0,
            "by_kind": dict(sorted(by_kind.items())),
        },
    }


__all__ = ["run_redteam_suite"]

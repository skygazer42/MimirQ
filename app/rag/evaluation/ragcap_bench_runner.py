from __future__ import annotations

from typing import Any


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _extract_step_texts(items: Any) -> list[str]:
    rows = list(items or [])
    out: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            text = _normalize_text(item.get("query") or item.get("text") or item.get("step"))
        else:
            text = _normalize_text(item)
        if text:
            out.append(text)
    return out


def _extract_tool_names(items: Any) -> list[str]:
    rows = list(items or [])
    out: list[str] = []
    for item in rows:
        if isinstance(item, dict):
            text = _normalize_text(item.get("name"))
        else:
            text = _normalize_text(item)
        if text:
            out.append(text)
    return out


def _ordered_match_ratio(expected: list[str], actual: list[str]) -> float | None:
    if not expected:
        return None
    matched = 0
    for idx, expected_item in enumerate(expected):
        if idx >= len(actual):
            continue
        if _normalize_text(actual[idx]).casefold() == _normalize_text(expected_item).casefold():
            matched += 1
    return round(float(matched) / float(len(expected)), 4)


def _bool_metric(expected: Any, actual: Any) -> float | None:
    if expected is None:
        return None
    return 1.0 if bool(expected) == bool(actual) else 0.0


def _extract_intermediate_factuality(trace: dict[str, Any]) -> float | None:
    claims = list(trace.get("intermediate_claims") or [])
    if not claims:
        return None
    supported = 0
    total = 0
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        total += 1
        if bool(claim.get("supported")):
            supported += 1
    if total <= 0:
        return None
    return round(float(supported) / float(total), 4)


def _average(values: list[float | None]) -> float | None:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / float(len(present)), 4)


def evaluate_ragcap_case(case: dict[str, Any]) -> dict[str, Any]:
    payload = dict(case or {})
    expected = dict(payload.get("expected") or {})
    trace = dict(payload.get("trace") or {})

    plan_correctness = _ordered_match_ratio(
        _extract_step_texts(expected.get("plan_steps")),
        _extract_step_texts(trace.get("plan_steps")),
    )
    tool_selection_accuracy = _ordered_match_ratio(
        _extract_tool_names(expected.get("tools")),
        _extract_tool_names(trace.get("tool_calls")),
    )
    intermediate_factuality = _extract_intermediate_factuality(trace)
    reflection_trigger_precision = _bool_metric(
        expected.get("reflection_needed"),
        dict(trace.get("reflection") or {}).get("triggered"),
    )
    termination_correctness = _bool_metric(
        _normalize_text(expected.get("termination")),
        _normalize_text(dict(trace.get("termination") or {}).get("status")),
    )
    if termination_correctness is not None:
        termination_correctness = (
            1.0
            if _normalize_text(expected.get("termination")).casefold()
            == _normalize_text(dict(trace.get("termination") or {}).get("status")).casefold()
            else 0.0
        )

    metrics = {
        "plan_correctness": plan_correctness,
        "tool_selection_accuracy": tool_selection_accuracy,
        "intermediate_factuality": intermediate_factuality,
        "reflection_trigger_precision": reflection_trigger_precision,
        "termination_correctness": termination_correctness,
    }
    overall_score = _average(list(metrics.values()))

    reason_codes: list[str] = []
    if plan_correctness is not None and plan_correctness < 1.0:
        reason_codes.append("plan_incorrect")
    if tool_selection_accuracy is not None and tool_selection_accuracy < 1.0:
        reason_codes.append("tool_selection_mismatch")
    if intermediate_factuality is not None and intermediate_factuality < 0.5:
        reason_codes.append("intermediate_factuality_low")
    if reflection_trigger_precision is not None and reflection_trigger_precision < 1.0:
        reason_codes.append("reflection_mismatch")
    if termination_correctness is not None and termination_correctness < 1.0:
        reason_codes.append("termination_incorrect")

    passed = bool((overall_score or 0.0) >= 0.7 and not reason_codes)
    return {
        "schema": "mimirq.ragcap_case_result.v1",
        "case_id": str(payload.get("case_id") or ""),
        "query_type": str(payload.get("query_type") or ""),
        "metrics": metrics,
        "overall_score": overall_score,
        "passed": passed,
        "reason_codes": reason_codes,
    }


def run_ragcap_bench(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [evaluate_ragcap_case(case) for case in (cases or [])]
    metrics = {
        "plan_correctness": _average([row["metrics"].get("plan_correctness") for row in rows]),
        "tool_selection_accuracy": _average([row["metrics"].get("tool_selection_accuracy") for row in rows]),
        "intermediate_factuality": _average([row["metrics"].get("intermediate_factuality") for row in rows]),
        "reflection_trigger_precision": _average([row["metrics"].get("reflection_trigger_precision") for row in rows]),
        "termination_correctness": _average([row["metrics"].get("termination_correctness") for row in rows]),
        "overall_score": _average([row.get("overall_score") for row in rows]),
    }
    total_cases = len(rows)
    passed_cases = sum(1 for row in rows if bool(row.get("passed")))
    pass_rate = round(float(passed_cases) / float(total_cases), 4) if total_cases > 0 else None
    return {
        "schema": "mimirq.ragcap_bench_summary.v1",
        "total_cases": int(total_cases),
        "passed_cases": int(passed_cases),
        "pass_rate": pass_rate,
        "metrics": metrics,
        "results": rows,
    }


__all__ = ["evaluate_ragcap_case", "run_ragcap_bench"]

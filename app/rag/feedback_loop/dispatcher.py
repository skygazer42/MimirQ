from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.rag.feedback_loop.hard_negative_promoter import promote_hard_negatives_to_jsonl

FEEDBACK_LOOP_BATCH_SCHEMA_V1 = "mimirq.feedback_loop_batch.v1"


def dispatch_feedback_loop_batch(
    *,
    candidate_payload: Mapping[str, Any],
    output_path: str | Path | None = None,
    dry_run: bool = True,
    append: bool = True,
    trigger: str = "manual",
) -> dict[str, Any]:
    """
    Export an explicit feedback candidate payload as one bounded batch.

    The dispatcher is deliberately pull/batch based. It does not register DB
    insert listeners, webhooks, or real-time side effects.
    """
    trigger_name = trigger.strip().lower()
    if not trigger_name:
        raise ValueError("Feedback batch trigger must not be blank")
    summary = dict(candidate_payload["summary"])
    eval_cases = candidate_payload["eval_case_candidates"]
    rules_suggestions = candidate_payload["rules_suggestions"]

    hard_negative_export = promote_hard_negatives_to_jsonl(
        candidate_payload,
        output_path=output_path,
        append=append,
        dry_run=dry_run,
    )

    return {
        "schema": FEEDBACK_LOOP_BATCH_SCHEMA_V1,
        "trigger": trigger_name,
        "realtime_listener_enabled": False,
        "dry_run": bool(dry_run),
        "candidates": summary,
        "eval_case_candidates": eval_cases,
        "hard_negative_export": hard_negative_export,
        "rules_suggestions": rules_suggestions,
    }


__all__ = [
    "FEEDBACK_LOOP_BATCH_SCHEMA_V1",
    "dispatch_feedback_loop_batch",
]

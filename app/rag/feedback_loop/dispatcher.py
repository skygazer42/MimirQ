from pathlib import Path
from typing import Any

from app.rag.feedback_loop.candidates import build_feedback_loop_candidates
from app.rag.feedback_loop.hard_negative_promoter import promote_hard_negatives_to_jsonl
from app.rag.industry_rules.schema import IndustryRuleset

FEEDBACK_LOOP_BATCH_SCHEMA_V1 = "mimirq.feedback_loop_batch.v1"


def dispatch_feedback_loop_batch(
    *,
    rows: list[Any] | None = None,
    db: Any | None = None,
    tenant_id: Any | None = None,
    account_id: str | None = None,
    output_path: str | Path | None = None,
    dry_run: bool = True,
    append: bool = True,
    trigger: str = "manual",
    max_rating: int = 2,
    limit: int = 200,
    ruleset: IndustryRuleset | None = None,
    ensure_member_fn: Any | None = None,
) -> dict[str, Any]:
    """
    Run one bounded feedback-loop batch.

    The dispatcher is deliberately pull/batch based. It does not register DB
    insert listeners, webhooks, or real-time side effects.
    """
    trigger_name = str(trigger or "manual").strip().lower() or "manual"

    if rows is not None:
        candidate_payload = build_feedback_loop_candidates(
            rows,
            ruleset=ruleset,
            max_rating=int(max_rating),
        )
    else:
        if db is None or tenant_id is None or not account_id:
            raise ValueError("rows or db+tenant_id+account_id are required")
        from app.services.feedback_service import FeedbackService

        candidate_payload = FeedbackService.build_feedback_loop_candidates(
            db=db,
            tenant_id=tenant_id,
            account_id=str(account_id),
            max_rating=int(max_rating),
            limit=int(limit),
            ruleset=ruleset,
            ensure_member_fn=ensure_member_fn,
        )

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
        "candidates": dict(candidate_payload.get("summary") or {}) if isinstance(candidate_payload, dict) else {},
        "eval_case_candidates": candidate_payload.get("eval_case_candidates")
        if isinstance(candidate_payload, dict)
        else [],
        "hard_negative_export": hard_negative_export,
        "rules_suggestions": candidate_payload.get("rules_suggestions") if isinstance(candidate_payload, dict) else {},
    }


def dispatch_scheduled_feedback_loop_batch(**kwargs: Any) -> dict[str, Any]:
    """Convenience wrapper for cron/arq callers; still pull-based, not realtime."""
    return dispatch_feedback_loop_batch(**{**kwargs, "trigger": "scheduled"})


__all__ = [
    "FEEDBACK_LOOP_BATCH_SCHEMA_V1",
    "dispatch_feedback_loop_batch",
    "dispatch_scheduled_feedback_loop_batch",
]

from __future__ import annotations

from pathlib import Path


def test_feedback_loop_candidates_endpoint_is_wired_to_service() -> None:
    text = Path("app/api/v1/feedback.py").read_text(encoding="utf-8")

    assert '@router.get("/loop/candidates"' in text
    assert "FeedbackService.build_feedback_loop_candidates" in text
    assert "load_ruleset" in text


def test_feedback_loop_hard_negative_export_endpoint_uses_batch_dispatcher() -> None:
    text = Path("app/api/v1/feedback.py").read_text(encoding="utf-8")

    assert '@router.post("/loop/hard-negatives/export"' in text
    assert "dispatch_feedback_loop_batch" in text
    assert "dry_run: Annotated[bool, Query()] = True" in text
    assert "realtime_listener_enabled" in Path("app/rag/feedback_loop/dispatcher.py").read_text(encoding="utf-8")

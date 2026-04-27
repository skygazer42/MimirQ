from __future__ import annotations

from app.rag.workflows.flare import run_flare_refinement


def test_run_flare_refinement_requests_followup_retrieval_when_confidence_is_low() -> None:
    out = run_flare_refinement(
        question="485 watchdog 怎么配置？",
        draft_answer="应该是 30 秒。",
        evidence_gap={"has_gap": True, "severity": "high"},
        confidence_score=0.2,
    )

    assert out["schema"] == "mimirq.flare_refinement.v1"
    assert out["need_retrieval"] is True
    assert out["rewrite_query"] == "485 watchdog 怎么配置？"
    assert out["reason_codes"] == ["low_confidence"]


def test_run_flare_refinement_skips_retrieval_when_confidence_is_high_and_gap_is_clear() -> None:
    out = run_flare_refinement(
        question="485 watchdog 怎么配置？",
        draft_answer="参考 RS-485 配置流程。",
        evidence_gap={"has_gap": False, "severity": "none"},
        confidence_score=0.9,
    )

    assert out["need_retrieval"] is False
    assert out["rewrite_query"] is None
    assert out["reason_codes"] == []

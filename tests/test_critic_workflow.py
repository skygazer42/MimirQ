from __future__ import annotations

from app.rag.workflows.critic import run_critic_review


def test_critic_review_accepts_grounded_answer_with_citations() -> None:
    out = run_critic_review(
        question="How do I configure MQTT keepalive?",
        answer="Use the MQTT keepalive value from the broker connection settings.",
        evidence_text="Use the MQTT keepalive value from the broker connection settings.",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
    )

    assert out["schema"] == "mimirq.critic_review.v1"
    assert out["verdict"] == "accept"
    assert out["citation_missing"] is False
    assert out["claims"] == [
        {
            "text": "Use the MQTT keepalive value from the broker connection settings.",
            "supported": True,
            "reason_code": "supported",
        }
    ]
    assert out["style_issues"] == []
    assert out["supported_claims"] == 1


def test_critic_review_flags_unsupported_and_missing_citation_answer() -> None:
    out = run_critic_review(
        question="How do I configure MQTT keepalive?",
        answer="Replace the PLC backplane immediately",
        evidence_text="Use the MQTT keepalive value from the broker connection settings.",
        citations=[],
    )

    assert out["verdict"] == "revise"
    assert out["citation_missing"] is True
    assert "unsupported_claims" in out["reason_codes"]
    assert "missing_citations" in out["reason_codes"]
    assert out["style_issues"]


def test_critic_review_keeps_supported_answer_but_records_style_violations() -> None:
    out = run_critic_review(
        question="How do I configure MQTT keepalive?",
        answer="You must use the MQTT keepalive value from the broker connection settings.",
        evidence_text="You must use the MQTT keepalive value from the broker connection settings.",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
    )

    assert out["verdict"] == "accept"
    assert out["citation_missing"] is False
    assert "style_violation" in out["reason_codes"]
    assert out["style_issues"] == [
        {
            "code": "prescriptive_language",
            "span": "must",
        }
    ]

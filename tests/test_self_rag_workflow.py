from __future__ import annotations

from app.rag.workflows.self_rag import run_self_rag_reflection


def test_self_rag_reflection_marks_supported_answer_as_useful() -> None:
    out = run_self_rag_reflection(
        question="How do I configure MQTT keepalive?",
        answer="Configure the MQTT keepalive value in the broker connection settings.",
        evidence_text="The guide says to configure the MQTT keepalive value in the broker connection settings.",
        citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
    )

    assert out["schema"] == "mimirq.self_rag_reflection.v1"
    assert out["need_retrieval"] is False
    assert out["is_supported"] is True
    assert out["is_relevant"] is True
    assert out["is_useful"] is True
    assert out["verdict"] == "accept"


def test_self_rag_reflection_requests_more_retrieval_when_answer_is_unsupported() -> None:
    out = run_self_rag_reflection(
        question="How do I configure MQTT keepalive?",
        answer="Replace the PLC backplane to fix the issue.",
        evidence_text="The guide says to configure the MQTT keepalive value in the broker connection settings.",
        citations=[],
    )

    assert out["need_retrieval"] is True
    assert out["is_supported"] is False
    assert out["verdict"] == "revise"
    assert "unsupported_claims" in out["reason_codes"]


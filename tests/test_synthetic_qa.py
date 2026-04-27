from __future__ import annotations


def test_build_synthetic_qa_side_index_emits_summary_and_question_docs() -> None:
    from app.rag.preprocessing.synthetic_qa import build_synthetic_qa_side_index

    out = build_synthetic_qa_side_index(
        text=(
            "# MQTT Broker Guide\n\n"
            "This guide explains how to configure the MQTT broker connection, topic layout, "
            "and keepalive settings for industrial gateways."
        ),
        metadata={"document_id": "doc-1", "document_title": "MQTT Broker Guide"},
        question_count=3,
    )

    assert out["schema"] == "mimirq.synthetic_qa_side_index.v1"
    assert out["summary"]
    assert len(out["questions"]) == 3
    docs = out["documents"]
    assert len(docs) == 4
    kinds = {(doc.metadata or {}).get("side_index_kind") for doc in docs}
    assert kinds == {"summary", "question"}
    assert (docs[0].metadata or {}).get("document_id") == "doc-1"


def test_build_synthetic_qa_side_index_reuses_existing_metadata_enrichment() -> None:
    from app.rag.preprocessing.synthetic_qa import build_synthetic_qa_side_index

    out = build_synthetic_qa_side_index(
        text="Body is ignored when metadata is already enriched.",
        metadata={
            "document_id": "doc-2",
            "document_title": "Preset Doc",
            "document_summary": "Existing summary.",
            "document_questions": ["Q1?", "Q2?"],
        },
        question_count=5,
    )

    assert out["summary"] == "Existing summary."
    assert out["questions"] == ["Q1?", "Q2?"]

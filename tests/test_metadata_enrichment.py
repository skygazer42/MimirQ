from __future__ import annotations

from app.rag.preprocessing.metadata_enrichment import build_document_metadata_enrichment


def test_build_document_metadata_enrichment_derives_summary_keywords_and_questions() -> None:
    text = "\n".join(
        [
            "---",
            "title: MQTT Broker Guide",
            "tags: [mqtt, industrial]",
            "---",
            "",
            "# MQTT Broker Guide",
            "",
            "This guide explains how to configure the MQTT broker connection, topic layout, and keepalive settings for industrial gateways.",
            "",
            "Use the broker panel to update host, port, and credentials for the field device.",
        ]
    )

    out = build_document_metadata_enrichment(
        text,
        metadata={},
        keywords_provider="simple",
        keyword_top_k=5,
        question_count=3,
    )

    assert out.get("document_title") == "MQTT Broker Guide"
    assert out.get("document_tags") == ["mqtt", "industrial"]
    assert "configure the MQTT broker connection" in str(out.get("document_summary") or "")
    keywords = [str(item).lower() for item in (out.get("document_keywords") or [])]
    assert "mqtt" in keywords
    assert out.get("document_language") in {"en", "mixed"}
    questions = out.get("document_questions") or []
    assert isinstance(questions, list)
    assert len(questions) == 3
    assert any("MQTT Broker Guide" in str(item) for item in questions)

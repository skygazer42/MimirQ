from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.factory import chunker_factory


def test_chunk_factory_can_inject_rich_metadata_header() -> None:
    text = "\n".join(
        [
            "# MQTT Broker Guide",
            "",
            "This guide explains how to configure the MQTT broker connection, topic layout, and keepalive settings for industrial gateways.",
            "",
            "Use the broker panel to update host, port, and credentials for the field device.",
        ]
    )

    chunker = chunker_factory.get_chunker(
        "semantic_sentence",
        chunk_size=500,
        chunk_overlap=0,
        enrich_document_metadata=True,
        inject_metadata_header=True,
        metadata_keywords_provider="simple",
        metadata_question_count=2,
    )
    chunks = chunker.split_documents([Document(page_content=text, metadata={})])

    assert len(chunks) == 1
    content = chunks[0].page_content or ""
    meta = chunks[0].metadata or {}

    assert content.startswith("Title: MQTT Broker Guide")
    assert "Summary:" in content
    assert "Keywords:" in content
    assert "Questions:" in content
    assert "This guide explains how to configure the MQTT broker connection" in content
    assert meta.get("document_title") == "MQTT Broker Guide"
    assert meta.get("rich_metadata_header_applied") is True

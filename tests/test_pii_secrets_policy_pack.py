from __future__ import annotations

from langchain_core.documents import Document

from app.rag.preprocessing.processor import governance_processor


def test_governance_pii_secrets_gate_drops_entire_document():  # noqa: ANN001
    docs = [
        Document(page_content="Email: foo@example.com\nOpenAI key: sk-aaaaaaaaaaaaaaaa\n", metadata={}),
        Document(page_content="Some other page\n", metadata={}),
    ]

    cleaned, stats = governance_processor.clean_documents(
        docs,
        pii_anonymize=True,
        pii_mode="mask",
        pii_mask="[REDACTED]",
        pii_max_hits=0,  # any hit triggers
        secrets_redact=True,
        secrets_mode="mask",
        secrets_mask="[SECRET]",
        secrets_max_hits=0,  # any hit triggers
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
    )

    assert cleaned == []
    assert stats.dropped == len(docs)
    assert stats.drop_reasons.get("pii_exceeded") == len(docs)
    assert stats.drop_reasons.get("secrets_exceeded") == len(docs)
    assert sum(stats.pii_hits.values()) > 0
    assert sum(stats.secrets_hits.values()) > 0


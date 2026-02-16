from langchain_core.documents import Document

from app.core.config import settings
from app.core.token_utils import num_tokens_from_string


def test_context_dedup_reduces_prompt_tokens(monkeypatch):
    # Force a strict per-doc cap so the test is deterministic.
    monkeypatch.setattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_DOC", 2, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_DEDUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_DEDUP_JACCARD_THRESHOLD", 0.90, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_DEDUP_MAX_COMPARE", 50, raising=False)

    docs = [
        Document(
            page_content="Copyright (c) 2026 Example. All rights reserved.\n\nApples are red.",
            metadata={"document_id": "doc-1", "chunk_index": 1, "score": 0.9},
        ),
        # Exact duplicate chunk (common in PDF exports with repeated headers/footers).
        Document(
            page_content="Copyright (c) 2026 Example. All rights reserved.\n\nApples are red.",
            metadata={"document_id": "doc-1", "chunk_index": 2, "score": 0.8},
        ),
        Document(
            page_content="Bananas are yellow.",
            metadata={"document_id": "doc-1", "chunk_index": 3, "score": 0.7},
        ),
        Document(
            page_content="Cherries are red.",
            metadata={"document_id": "doc-1", "chunk_index": 4, "score": 0.6},
        ),
    ]

    before = "\n\n".join(d.page_content for d in docs)
    before_tokens = num_tokens_from_string(before)

    from app.rag.core.context_denoise import denoise_context_docs

    out_docs = denoise_context_docs(docs)
    after = "\n\n".join(d.page_content for d in out_docs)
    after_tokens = num_tokens_from_string(after)

    assert after_tokens < before_tokens
    assert after.count("Apples are red.") == 1
    assert "Copyright" not in after

    # Per-document cap applied after de-noising.
    by_doc = {}
    for d in out_docs:
        doc_id = str((d.metadata or {}).get("document_id") or "")
        by_doc[doc_id] = int(by_doc.get(doc_id, 0) or 0) + 1
    assert by_doc.get("doc-1", 0) <= 2


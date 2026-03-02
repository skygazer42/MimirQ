from __future__ import annotations


def test_retrieval_content_hash_dedup_drops_duplicates_across_modalities() -> None:
    from app.rag.retriever import HybridRetriever

    r = HybridRetriever()
    r.dedup_enabled = True
    # Disable similarity-based Jaccard dedup to isolate content-hash behavior.
    r.dedup_jaccard_threshold = 0.0

    results = [
        {
            "chunk_id": "c_text",
            "content": "Alpha extracted text",
            "metadata": {"document_id": "d1", "content_hash": "hash-123"},
            "score": 1.0,
        },
        {
            "chunk_id": "c_ocr",
            "content": "Alpha OCR text (whitespace differs)",
            "metadata": {"document_id": "d1", "content_hash": "hash-123"},
            "score": 0.9,
        },
        {
            "chunk_id": "c_other",
            "content": "Different content",
            "metadata": {"document_id": "d1", "content_hash": "hash-456"},
            "score": 0.8,
        },
    ]

    out = r._deduplicate_results(results)
    assert [x.get("chunk_id") for x in out] == ["c_text", "c_other"]


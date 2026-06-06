from __future__ import annotations

from langchain_core.documents import Document


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


def test_retrieval_record_identity_caps_candidates_per_business_record() -> None:
    from app.rag.retriever import HybridRetriever

    r = HybridRetriever()
    r.dedup_enabled = True
    r.dedup_jaccard_threshold = 0.0
    r.max_chunks_per_record_identity = 2
    r._last_channel_metrics = {}

    def result(chunk_id: str, record_key: str, content: str) -> dict:
        return {
            "chunk_id": chunk_id,
            "content": content,
            "metadata": {
                "dataset_id": "dataset-a",
                "document_id": "doc-a",
                "_record_identity": {
                    "schema": "mimirq.record_identity.v1",
                    "key": record_key,
                    "fields": {"source_record_id": record_key},
                },
            },
            "score": 1.0,
        }

    out = r._deduplicate_results(
        [
            result("c1", "record:001", "alpha one"),
            result("c2", "record:001", "alpha two"),
            result("c3", "record:001", "alpha three"),
            result("c4", "record:002", "beta one"),
        ]
    )

    assert [x.get("chunk_id") for x in out] == ["c1", "c2", "c4"]
    dedup = (r._last_channel_metrics or {}).get("dedup")
    assert isinstance(dedup, dict)
    assert int(dedup.get("record_identity_dropped") or 0) == 1
    assert int(dedup.get("max_chunks_per_record_identity") or 0) == 2


def test_bm25_result_preserves_schema_generated_metadata_views() -> None:
    from app.rag.retriever import HybridRetriever

    r = HybridRetriever()
    doc = Document(
        id="chunk-1",
        page_content="Demo record content",
        metadata={
            "tenant_id": "tenant-a",
            "dataset_id": "dataset-a",
            "document_id": "doc-a",
            "source": "demo-records.txt",
            "business_type": "should-not-leak",
            "_indexed_metadata": {"business_type": "demo_service"},
            "_display_metadata": {"record_name": "account renewal"},
            "_evaluable_metadata": {"district": "north-region"},
            "_record_identity": {
                "schema": "mimirq.record_identity.v1",
                "key": "knowledge_section=demo|source_record_id=001",
                "fields": {"source_record_id": "001"},
            },
        },
    )

    result = r._bm25_result_from_doc(doc=doc, raw_score=3.0, final_score=4.0, question_channel_score=1.0)
    meta = result["metadata"]

    assert meta["dataset_id"] == "dataset-a"
    assert meta["_indexed_metadata"] == {"business_type": "demo_service"}
    assert meta["_display_metadata"] == {"record_name": "account renewal"}
    assert meta["_evaluable_metadata"] == {"district": "north-region"}
    assert meta["_record_identity"]["fields"] == {"source_record_id": "001"}
    assert "business_type" not in meta


def test_rerank_text_includes_schema_generated_display_metadata() -> None:
    from app.rag.retriever import HybridRetriever

    r = HybridRetriever()
    text = r._rerank_text_from_result(
        {
            "content": "Required material: identity proof.",
            "metadata": {
                "_display_metadata": {
                    "record_name": "account renewal",
                },
                "_evaluable_metadata": {
                    "district": "north-region",
                },
            },
        }
    )

    assert text.startswith("Metadata:\n")
    assert "- record_name: account renewal" in text
    assert "- district: north-region" in text
    assert text.endswith("Required material: identity proof.")

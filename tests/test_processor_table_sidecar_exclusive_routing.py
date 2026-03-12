from __future__ import annotations

from langchain_core.documents import Document


def test_table_sidecar_exclusive_filters_parser_table_chunks() -> None:
    from app.parsing.processors.processor import DocumentProcessorService

    svc = DocumentProcessorService()
    chunks = [
        Document(page_content="| a | b |\n| --- | --- |\n| 1 | 2 |", metadata={"content_type": "table", "page": 3}),
        Document(page_content="这是正文段落。", metadata={"content_type": "text", "page": 3}),
    ]

    filtered, audit = svc._apply_table_sidecar_exclusive_routing(  # type: ignore[attr-defined]
        chunks=chunks,
        enabled=True,
        sidecar_tables_imported=1,
    )

    assert len(filtered) == 1
    assert filtered[0].page_content == "这是正文段落。"
    assert audit["table_chunks_seen"] == 1
    assert audit["table_chunks_excluded_from_rag"] == 1
    assert audit["rag_exclusion_reason"] == "table_sidecar_exclusive"
    samples = audit["excluded_samples"]
    assert isinstance(samples, list)
    assert len(samples) == 1
    assert samples[0]["page"] == 3


def test_table_sidecar_exclusive_keeps_table_chunks_when_no_sidecar_import() -> None:
    from app.parsing.processors.processor import DocumentProcessorService

    svc = DocumentProcessorService()
    chunks = [
        Document(page_content="t1", metadata={"doc_type_kwd": "table"}),
        Document(page_content="p1", metadata={"doc_type_kwd": "text"}),
    ]

    filtered, audit = svc._apply_table_sidecar_exclusive_routing(  # type: ignore[attr-defined]
        chunks=chunks,
        enabled=True,
        sidecar_tables_imported=0,
    )

    assert len(filtered) == 2
    assert audit["table_chunks_seen"] == 1
    assert audit["table_chunks_excluded_from_rag"] == 0
    assert audit["rag_exclusion_reason"] is None


def test_table_sidecar_routed_chunk_marks_metadata_contract() -> None:
    from app.parsing.processors.processor import DocumentProcessorService

    svc = DocumentProcessorService()
    chunks = [
        Document(page_content="t1", metadata={"content_type": "table", "page": 1}),
        Document(page_content="p1", metadata={"content_type": "text", "page": 1}),
    ]

    filtered, _audit = svc._apply_table_sidecar_exclusive_routing(  # type: ignore[attr-defined]
        chunks=chunks,
        enabled=False,
        sidecar_tables_imported=2,
    )
    assert len(filtered) == 2
    table_meta = filtered[0].metadata or {}
    assert table_meta.get("table_routing_kind") == "tag_sidecar"
    assert table_meta.get("table_routing_source") == "parser_table_segment"
    assert table_meta.get("table_rag_excluded") is False
    assert table_meta.get("table_rag_exclusion_reason") is None

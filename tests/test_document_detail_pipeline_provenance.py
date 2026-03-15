from __future__ import annotations

import datetime as dt
import uuid

from app.api.schemas.document import DocumentDetail


def test_document_detail_includes_pipeline_provenance():  # noqa: ANN001
    now = dt.datetime(2026, 2, 1, 0, 0, 0, tzinfo=dt.UTC)

    doc_id = uuid.uuid4()
    payload = {
        "id": doc_id,
        "filename": "demo.pdf",
        "file_type": "pdf",
        "file_size": 123,
        "status": "completed",
        "processing_progress": 100,
        "chunk_count": 3,
        "total_characters": 999,
        "created_at": now,
        "updated_at": now,
        "doc_metadata": {
            "pipeline_hash": "v2",
            "active_pipeline_hash": "v1",
            "parser_backend": "paddle_vl",
            "parser_backend_requested": "auto",
            "chunk_strategy": "markdown_outline",
            "chunk_strategy_requested": "langchain_recursive",
            "governance_enabled": True,
            "governance_rule_packs": ["default", "pii"],
            "pipeline_effective": {
                "governance_enabled": True,
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "chunk_vector_enabled": True,
                "bm25_index_enabled": False,
            },
            "document_analytics_raw": {
                "char_count": 1200,
                "line_count": 42,
                "heading_count": 2,
                "page_count": 12,
                "table_count": 1,
                "image_count": 3,
                "block_count": 7,
            },
        },
    }

    doc = DocumentDetail.model_validate(payload)

    assert doc.pipeline is not None
    assert doc.pipeline.pipeline_hash == "v2"
    assert doc.pipeline.active_pipeline_hash == "v1"
    assert doc.pipeline.parser_backend == "paddle_vl"
    assert doc.pipeline.chunk_strategy == "markdown_outline"
    assert doc.pipeline.governance_enabled is True
    assert doc.pipeline.governance_rule_packs == ["default", "pii"]
    assert doc.pipeline.pipeline_effective.chunk_size == 1000
    assert doc.pipeline.pipeline_effective.chunk_overlap == 200
    assert doc.pipeline.analytics_raw.page_count == 12
    assert doc.pipeline.analytics_raw.heading_count == 2


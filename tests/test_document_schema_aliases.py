from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.api.schemas.document import DocumentChunkSchema, DocumentDetail


def test_document_detail_metadata_reads_doc_metadata_first():
    class DummyDoc:
        id = uuid4()
        filename = "a.pdf"
        file_type = "pdf"
        file_size = 123
        status = "pending"
        processing_progress = 0
        chunk_count = 0
        total_characters = 0
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)
        processed_at = None
        error_message = None
        dataset_id = None

        # SQLAlchemy models use `doc_metadata`, while class-level `.metadata` exists too.
        doc_metadata = {"parser_backend": "basic"}
        metadata = "SHOULD_NOT_BE_USED"

    out = DocumentDetail.model_validate(DummyDoc(), from_attributes=True)
    assert out.metadata == {"parser_backend": "basic"}
    assert out.chunks is None


def test_document_chunk_schema_metadata_reads_doc_metadata_first():
    class DummyChunk:
        id = uuid4()
        content = "hello"
        page_number = None
        start_char = None
        end_char = None
        chunk_index = 0
        doc_metadata = {"page": 1}
        metadata = "SHOULD_NOT_BE_USED"

    out = DocumentChunkSchema.model_validate(DummyChunk(), from_attributes=True)
    assert out.metadata == {"page": 1}


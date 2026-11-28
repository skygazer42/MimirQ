from uuid import uuid4

import pytest
from sqlalchemy import JSON, Column, MetaData, Table, Uuid, create_engine
from sqlalchemy.orm import Session

import app.models.registry  # noqa: F401
from app.models.documents.records import Document, DocumentChunk
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntologyDocument
from app.rag.kg.enterprise_ontology import documents
from app.rag.kg.enterprise_ontology.definition import load_ontology_definition
from app.rag.kg.enterprise_ontology.metadata import DocumentMetadataReview, ManualMetadataValue, read_document_metadata
from app.rag.kg.enterprise_ontology.preview import ChunkPreview
from tests.test_enterprise_ontology_preview import MODEL


def test_metadata_review_is_version_scoped_and_preserved_on_reextraction(monkeypatch):
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("datasets", metadata, Column("id", Uuid, primary_key=True), Column("tenant_id", Uuid))
    Table("enterprise_ontology_versions", metadata, Column("id", Uuid, primary_key=True))
    for model in (Document, DocumentChunk):
        model.__table__.to_metadata(metadata).c["metadata"].type = JSON()
    EnterpriseOntologyDocument.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    monkeypatch.setattr(documents, "filter_allowed_document_ids", lambda db, tenant, account, ids: ids)

    definition = load_ontology_definition(
        MODEL + "\ndocument_metadata:\n  document_number: {type: string, method: manual}\n", format="yaml"
    )
    with Session(engine, expire_on_commit=False) as db:
        tenant_id, version_id = uuid4(), uuid4()
        document = Document(
            tenant_id=tenant_id,
            dataset_id=uuid4(),
            filename="SLA.pdf",
            file_type="pdf",
            file_path="sla.pdf",
            file_size=123,
            doc_metadata={"active_pipeline_hash": "approved"},
        )
        db.add(document)
        db.flush()
        approved, newer = (
            DocumentChunk(
                tenant_id=tenant_id,
                document_id=document.id,
                chunk_index=0,
                page_number=3,
                content=content,
                doc_metadata={"pipeline_hash": pipeline},
            )
            for pipeline, content in (("approved", "SLA-2026-11"), ("newer", "SLA-2026-12"))
        )
        db.add_all([approved, newer])
        db.flush()

        def prepare(chunk):
            return documents.save_document_evidence(
                db,
                tenant_id=tenant_id,
                document=document,
                version_id=version_id,
                pipeline_hash=chunk.doc_metadata["pipeline_hash"],
                previews=[ChunkPreview(document_id=document.id, chunk_id=chunk.id, page=chunk.page_number)],
            )

        def review(chunk):
            return documents.review_document_metadata(
                db,
                tenant_id=tenant_id,
                account_id="reviewer",
                document_id=document.id,
                version_id=version_id,
                definition=definition,
                request=DocumentMetadataReview(
                    field="document_number",
                    manual_values=[ManualMetadataValue(chunk_id=chunk.id, start_char=0, end_char=len(chunk.content))],
                ),
            )

        def read(pipeline_hash=None):
            _, _, previews = documents.load_document_evidence(
                db,
                tenant_id=tenant_id,
                account_id="reviewer",
                document_id=document.id,
                version_id=version_id,
                pipeline_hash=pipeline_hash,
            )
            return read_document_metadata(definition, previews)["document_number"]

        prepare(approved)
        prepare(newer)
        with pytest.raises(ValueError, match="selected document version"):
            review(newer)
        db.rollback()
        review(approved)
        prepare(approved)
        assert read().confirmed[0].value == "SLA-2026-11"
        assert read().confirmed[0].origin == "manual"
        assert read("newer").state == "missing"

        approved.content = "Document number removed"
        db.commit()
        assert read().state == "missing"

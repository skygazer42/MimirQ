"""Read and prepare ontology evidence without mixing document or ontology revisions."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models.documents.records import Document, DocumentChunk
from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntologyDocument
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition
from app.rag.kg.enterprise_ontology.metadata import (
    DocumentMetadataReview,
    apply_metadata_review,
    document_metadata_candidate,
)
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, PreviewEntity, PreviewRelation
from app.rag.kg.extraction.evidence import EvidenceSpan
from app.services.documents.pipeline_versions import get_selected_pipeline_hash
from app.services.documents.read_scope import filter_allowed_document_ids, get_allowed_document_id_sets


class ManualGraph(BaseModel):
    content_hash: str
    edited_by: str
    edited_at: AwareDatetime
    entities: list[PreviewEntity]
    relations: list[PreviewRelation]


class StoredChunkPreview(ChunkPreview):
    manual_graph: ManualGraph | None = None


def load_document_chunks(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    pipeline_hash: str | None = None,
    *,
    limit: int | None = None,
    lock: bool = False,
) -> tuple[Document, str, list[DocumentChunk]]:
    doc = _read_document(db, tenant_id, account_id, document_id, lock=lock)
    selected = get_selected_pipeline_hash(doc.doc_metadata, pipeline_hash) or "legacy"
    statement = _chunk_statement(tenant_id, document_id, selected)
    if limit is not None:
        statement = statement.limit(limit)
    chunks = list(db.scalars(statement))
    if not chunks:
        raise HTTPException(status_code=404, detail="No readable chunks for the selected document version")
    return doc, selected, chunks


def _read_document(db: Session, tenant_id: UUID, account_id: str, document_id: UUID, *, lock: bool = False) -> Document:
    filter_allowed_document_ids(db, tenant_id, account_id, [document_id])
    statement = select(Document).where(Document.tenant_id == tenant_id, Document.id == document_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    document = db.scalar(statement)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


def _chunk_statement(tenant_id: UUID, document_id: UUID, pipeline_hash: str) -> Select[tuple[DocumentChunk]]:
    stored_pipeline = DocumentChunk.doc_metadata["pipeline_hash"].as_string()
    scope = stored_pipeline == pipeline_hash
    if pipeline_hash == "legacy":
        scope = or_(scope, stored_pipeline.is_(None))
    return (
        select(DocumentChunk)
        .where(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.disabled_at.is_(None),
            scope,
        )
        .order_by(DocumentChunk.chunk_index, DocumentChunk.id)
    )


def content_hash(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def visible_chunk(preview: StoredChunkPreview, chunk: DocumentChunk) -> ChunkPreview:
    manual = preview.manual_graph
    if manual is not None and manual.content_hash != content_hash(chunk.content):
        manual = None
    entities = []
    for entity in manual.entities if manual is not None else preview.entities:
        if span_matches(chunk.content, entity.evidence):
            attributes = {
                name: [value for value in values if span_matches(chunk.content, value.evidence)]
                for name, values in entity.attributes.items()
            }
            entities.append(entity.model_copy(update={"attributes": attributes}))
    ids = {entity.id for entity in entities}
    relations = [
        relation
        for relation in (manual.relations if manual is not None else preview.relations)
        if {relation.subject_id, relation.object_id} <= ids and span_matches(chunk.content, relation.evidence)
    ]
    return ChunkPreview(
        document_id=preview.document_id,
        chunk_id=preview.chunk_id,
        page=chunk.page_number,
        entities=entities,
        relations=relations,
        rejected=preview.rejected,
        extracted_at=preview.extracted_at,
        metadata_candidates=[
            candidate
            for candidate in preview.metadata_candidates
            if candidate.chunk_id == chunk.id
            and candidate.page == chunk.page_number
            and span_matches(chunk.content, candidate.evidence)
        ],
    )


def _visible_previews(previews: list[StoredChunkPreview], chunks: dict[UUID, DocumentChunk]) -> list[ChunkPreview]:
    visible = []
    for preview in previews:
        chunk = chunks.get(preview.chunk_id)
        if chunk is None or preview.document_id != chunk.document_id:
            continue
        visible.append(visible_chunk(preview, chunk))
    return visible


def span_matches(text: str, evidence: EvidenceSpan) -> bool:
    return (
        0 <= evidence.start_char < evidence.end_char <= len(text)
        and text[evidence.start_char : evidence.end_char] == evidence.quote
    )


def stored_previews(row: EnterpriseOntologyDocument) -> list[StoredChunkPreview]:
    return [StoredChunkPreview.model_validate(item) for item in row.chunks]


def current_document_previews(
    db: Session, row: EnterpriseOntologyDocument, document: Document
) -> list[tuple[ChunkPreview, DocumentChunk]]:
    if row.pipeline_hash != (get_selected_pipeline_hash(document.doc_metadata, None) or "legacy"):
        return []
    previews = stored_previews(row)
    chunks = {
        chunk.id: chunk for chunk in db.scalars(
            _chunk_statement(document.tenant_id, document.id, row.pipeline_hash)
            .where(DocumentChunk.id.in_([preview.chunk_id for preview in previews]))
        )
    }
    return [(preview, chunks[preview.chunk_id]) for preview in _visible_previews(previews, chunks)]


def read_evidence_row(
    db: Session, document: Document, version_id: UUID, pipeline_hash: str, *, refresh: bool = False
) -> EnterpriseOntologyDocument:
    row = db.get(EnterpriseOntologyDocument, (version_id, document.id, pipeline_hash), populate_existing=refresh)
    if row is None or row.tenant_id != document.tenant_id or row.dataset_id != document.dataset_id:
        raise HTTPException(status_code=404, detail="No ontology evidence for the selected document version")
    return row


def load_document_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    version_id: UUID,
    pipeline_hash: str | None = None,
) -> tuple[Document, str, list[ChunkPreview]]:
    document, selected, chunks = load_document_chunks(db, tenant_id, account_id, document_id, pipeline_hash)
    row = read_evidence_row(db, document, version_id, selected)
    return document, selected, _visible_previews(stored_previews(row), {chunk.id: chunk for chunk in chunks})


def save_document_evidence(
    db: Session,
    *,
    tenant_id: UUID,
    document: Document,
    version_id: UUID,
    pipeline_hash: str,
    previews: list[ChunkPreview],
) -> EnterpriseOntologyDocument:
    locked = db.scalar(
        select(Document.id)
        .where(Document.id == document.id, Document.tenant_id == tenant_id, Document.dataset_id == document.dataset_id)
        .with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="Document not found")
    key = version_id, document.id, pipeline_hash
    row = db.get(EnterpriseOntologyDocument, key, populate_existing=True)
    if row is None:
        row = EnterpriseOntologyDocument(
            version_id=version_id,
            document_id=document.id,
            pipeline_hash=pipeline_hash,
            tenant_id=tenant_id,
            dataset_id=document.dataset_id,
        )
        db.add(row)
    serialized = [StoredChunkPreview.model_validate(preview.model_dump()) for preview in previews]
    if row.chunks:
        chunks = {chunk.id: chunk for chunk in db.scalars(_chunk_statement(tenant_id, document.id, pipeline_hash))}
        stored = {preview.chunk_id: preview for preview in stored_previews(row)}
        previous = {preview.chunk_id: preview for preview in _visible_previews(list(stored.values()), chunks)}
        for preview in serialized:
            if preview.chunk_id not in previous:
                continue
            candidates = {candidate.id: candidate for candidate in preview.metadata_candidates}
            candidates.update({candidate.id: candidate for candidate in previous[preview.chunk_id].metadata_candidates})
            preview.metadata_candidates = list(candidates.values())
            manual = stored[preview.chunk_id].manual_graph
            if manual is not None and manual.content_hash == content_hash(chunks[preview.chunk_id].content):
                preview.manual_graph = manual
    row.chunks = [preview.model_dump(mode="json") for preview in serialized]
    db.commit()
    db.refresh(row)
    return row


def review_document_metadata(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document_id: UUID,
    version_id: UUID,
    definition: OntologyDefinition,
    request: DocumentMetadataReview,
    pipeline_hash: str | None = None,
) -> EnterpriseOntologyDocument:
    document = _read_document(db, tenant_id, account_id, document_id, lock=True)
    selected = get_selected_pipeline_hash(document.doc_metadata, pipeline_hash) or "legacy"
    row = read_evidence_row(db, document, version_id, selected, refresh=True)
    chunks = {chunk.id: chunk for chunk in db.scalars(_chunk_statement(tenant_id, document_id, selected))}
    stored = stored_previews(row)
    visible = _visible_previews(stored, chunks)
    if not visible:
        raise HTTPException(status_code=404, detail="No readable chunks for the selected ontology evidence")
    field = definition.document_metadata.get(request.field)
    if field is None:
        raise ValueError(f"Unknown document metadata field {request.field}")

    by_chunk = {preview.chunk_id: preview for preview in visible}
    stored_by_chunk = {preview.chunk_id: preview for preview in stored}
    candidate_ids = list(request.candidate_ids)
    for manual in request.manual_values:
        preview = by_chunk.get(manual.chunk_id)
        if preview is None:
            raise ValueError("Manual metadata requires a readable chunk from the selected document version")
        chunk = chunks[manual.chunk_id]
        if not manual.start_char < manual.end_char <= len(chunk.content):
            raise ValueError("Manual metadata span is outside the source chunk")
        raw = chunk.content[manual.start_char : manual.end_char]
        candidate = document_metadata_candidate(
            field,
            field=request.field,
            chunk_id=chunk.id,
            page=chunk.page_number,
            raw=raw,
            evidence=EvidenceSpan(raw, manual.start_char, manual.end_char, "quote"),
            origin="manual",
        )
        if all(item.id != candidate.id for item in preview.metadata_candidates):
            preview.metadata_candidates.append(candidate)
            stored_by_chunk[chunk.id].metadata_candidates.append(candidate)
        candidate_ids.append(candidate.id)

    apply_metadata_review(
        definition,
        visible,
        request.model_copy(update={"candidate_ids": candidate_ids}),
        reviewed_by=account_id,
        reviewed_at=datetime.now(UTC),
    )
    selected_ids = set(candidate_ids)
    for preview in stored:
        for candidate in preview.metadata_candidates:
            if candidate.field == request.field and candidate.id not in selected_ids:
                candidate.confirmed_at = None
                candidate.confirmed_by = None
    row.chunks = [preview.model_dump(mode="json") for preview in stored]
    db.commit()
    db.refresh(row)
    return row


def require_dataset_evidence(
    db: Session, *, tenant_id: UUID, dataset_id: UUID, version_id: UUID, account_id: str
) -> None:
    # Evidence preparation and review lock the document before writing.
    documents = db.execute(
        select(Document.id, Document.filename, Document.doc_metadata)
        .where(
            Document.tenant_id == tenant_id,
            Document.dataset_id == dataset_id,
            Document.archived_at.is_(None),
            Document.publication_status == "published",
        )
        .order_by(Document.id)
        .with_for_update()
    )
    for document_id, filename, metadata in documents:
        pipeline_hash = get_selected_pipeline_hash(metadata, None) or "legacy"
        chunk_ids = list(
            db.scalars(_chunk_statement(tenant_id, document_id, pipeline_hash).with_only_columns(DocumentChunk.id))
        )
        if not chunk_ids:
            issue = "has no enabled chunks in its current pipeline"
        else:
            row = db.scalar(
                select(EnterpriseOntologyDocument)
                .where(
                    EnterpriseOntologyDocument.tenant_id == tenant_id,
                    EnterpriseOntologyDocument.dataset_id == dataset_id,
                    EnterpriseOntologyDocument.version_id == version_id,
                    EnterpriseOntologyDocument.document_id == document_id,
                    EnterpriseOntologyDocument.pipeline_hash == pipeline_hash,
                )
                .execution_options(populate_existing=True)
            )
            previews = stored_previews(row) if row is not None else []
            prepared_ids = {preview.chunk_id for preview in previews if preview.document_id == document_id}
            missing_ids = [str(chunk_id) for chunk_id in chunk_ids if chunk_id not in prepared_ids]
            if not missing_ids:
                continue
            issue = f"is missing prepared evidence for chunks {', '.join(missing_ids)}"
        allowed_ids, _ = get_allowed_document_id_sets(db, tenant_id, account_id, [document_id], check_member=False)
        detail = (
            f"Document {filename} ({document_id}) {issue}"
            if document_id in allowed_ids
            else "Document evidence is not ready for this version"
        )
        raise HTTPException(status_code=409, detail=detail)

"""Extract evidence for the ontology selected by a knowledge base."""

from contextlib import aclosing
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.documents.records import Document, DocumentChunk
from app.rag.kg.enterprise_ontology.activation import active_version_id, published_version
from app.rag.kg.enterprise_ontology.definition import OntologyDefinition
from app.rag.kg.enterprise_ontology.documents import save_document_evidence
from app.rag.kg.enterprise_ontology.preview import ChunkPreview, preview_ontology_extraction
from app.rag.llm.factory import create_llm_client
from app.services.datasets.management import assert_dataset_writable, get_dataset
from app.services.documents.pipeline_versions import get_selected_pipeline_hash
from app.services.documents.read_scope import filter_allowed_document_ids


async def prepare_bound_document(
    db: Session,
    *,
    document: Document,
    chunks: list[DocumentChunk],
    pipeline_hash: str | None,
    account_id: str | None = None,
) -> tuple[UUID, list[ChunkPreview]] | None:
    if document.dataset_id is None:
        return None
    version_id = active_version_id(db, document.tenant_id, document.dataset_id)
    version = published_version(db, document.tenant_id, version_id) if version_id is not None else None
    if version is None:
        return None
    if account_id is not None:
        assert_dataset_writable(db, get_dataset(db, document.tenant_id, document.dataset_id), account_id)
        filter_allowed_document_ids(db, document.tenant_id, account_id, [document.id])
    selected = get_selected_pipeline_hash(document.doc_metadata, pipeline_hash) or "legacy"
    active_chunks = [chunk for chunk in chunks if chunk.disabled_at is None]
    if not active_chunks:
        raise HTTPException(status_code=404, detail="No readable chunks for the selected document version")
    definition = OntologyDefinition.model_validate(version.definition)
    async with aclosing(await create_llm_client()) as client:
        previews = await preview_ontology_extraction(definition, active_chunks, llm_client=client)
    save_document_evidence(
        db,
        tenant_id=document.tenant_id,
        document=document,
        version_id=version.id,
        pipeline_hash=selected,
        previews=previews,
    )
    return version.id, previews

from typing import TYPE_CHECKING
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy import or_

from app.types.document_metadata import metadata_text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.documents.records import DocumentChunk


def build_desired_pipeline_by_doc(docs: list[Document]) -> dict[str, str]:
    desired_pipeline_by_doc: dict[str, str] = {}
    for doc in docs:
        meta = doc.metadata
        doc_id = metadata_text(meta, "document_id")
        if not doc_id:
            continue
        pipeline_key = metadata_text(meta, "doc_pipeline_key")
        if not pipeline_key:
            pipeline_hash = metadata_text(meta, "pipeline_hash")
            if pipeline_hash:
                pipeline_key = f"{doc_id}:{pipeline_hash}"
        if pipeline_key:
            desired_pipeline_by_doc.setdefault(doc_id, pipeline_key)
    return desired_pipeline_by_doc


def hierarchy_fetch_pairs_by_doc(
    pairs: set[tuple[str, str]],
) -> dict[str, set[str]]:
    by_doc: dict[str, set[str]] = {}
    for doc_id, node_key in pairs:
        doc_id_s = doc_id.strip()
        node_key_s = node_key.strip()
        if not doc_id_s or not node_key_s:
            continue
        by_doc.setdefault(doc_id_s, set()).add(node_key_s)
    return by_doc


def chunk_document_from_row(ck: "DocumentChunk") -> Document | None:
    meta = dict(ck.doc_metadata or {})
    cid = str(ck.id)
    meta.setdefault("tenant_id", str(ck.tenant_id))
    meta.setdefault("document_id", str(ck.document_id))
    meta.setdefault("chunk_id", cid)
    meta.setdefault("chunk_index", ck.chunk_index)
    page_number = ck.page_number
    if page_number is not None:
        meta.setdefault("page", page_number)
        meta.setdefault("page_number", page_number)
    start_char = ck.start_char
    end_char = ck.end_char
    if start_char is not None:
        meta.setdefault("start_char", start_char)
    if end_char is not None:
        meta.setdefault("end_char", end_char)
    if not meta.get("source"):
        meta["source"] = "unknown"

    node_key = metadata_text(meta, "hierarchy_node_key") or metadata_text(meta, "chunk_key")
    if not node_key:
        return None
    return Document(
        page_content=ck.content,
        metadata=meta,
        id=cid,
    )


def _matches_desired_pipeline(
    *,
    chunk: "DocumentChunk",
    desired_pipeline_by_doc: dict[str, str],
) -> bool:
    desired = desired_pipeline_by_doc.get(str(chunk.document_id))
    if not desired:
        return True
    meta = dict(chunk.doc_metadata or {})
    chunk_pipeline_key = metadata_text(meta, "doc_pipeline_key")
    if not chunk_pipeline_key:
        pipeline_hash = metadata_text(meta, "pipeline_hash")
        if pipeline_hash:
            chunk_pipeline_key = f"{chunk.document_id}:{pipeline_hash}"
    return chunk_pipeline_key == desired


def _fetch_doc_hierarchy_chunks(
    *,
    db: "Session",
    doc_uuid: UUID,
    tenant_uuid: UUID | None,
    keys_list: list[str],
) -> list["DocumentChunk"]:
    from app.models.documents.records import DocumentChunk

    query = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_uuid)
    if tenant_uuid is not None:
        query = query.filter(DocumentChunk.tenant_id == tenant_uuid)
    query = query.filter(
        or_(
            DocumentChunk.doc_metadata["hierarchy_node_key"].astext.in_(keys_list),  # type: ignore[attr-defined]
            DocumentChunk.doc_metadata["chunk_key"].astext.in_(keys_list),  # type: ignore[attr-defined]
        )
    )
    return query.all()


def _load_doc_hierarchy_docs(
    *,
    db: "Session",
    doc_id_s: str,
    tenant_uuid: UUID | None,
    keys: set[str],
    desired_pipeline_by_doc: dict[str, str],
) -> dict[tuple[str, str], Document]:
    try:
        doc_uuid = UUID(doc_id_s)
    except ValueError:
        return {}
    keys_list = [key for key in keys if key]
    if not keys_list:
        return {}

    out: dict[tuple[str, str], Document] = {}
    for chunk in _fetch_doc_hierarchy_chunks(
        db=db,
        doc_uuid=doc_uuid,
        tenant_uuid=tenant_uuid,
        keys_list=keys_list,
    ):
        if not _matches_desired_pipeline(
            chunk=chunk,
            desired_pipeline_by_doc=desired_pipeline_by_doc,
        ):
            continue
        document = chunk_document_from_row(chunk)
        if document is None:
            continue
        node_key_s = metadata_text(document.metadata, "hierarchy_node_key") or metadata_text(
            document.metadata, "chunk_key"
        )
        out[(str(chunk.document_id), node_key_s)] = document
    return out


def fetch_hierarchy_expansion_docs(
    pairs: set[tuple[str, str]],
    *,
    tenant_uuid: UUID | None,
    desired_pipeline_by_doc: dict[str, str],
) -> dict[tuple[str, str], Document]:
    from app.infrastructure.database.connection import SessionLocal

    if not pairs:
        return {}
    by_doc = hierarchy_fetch_pairs_by_doc(pairs)
    if not by_doc:
        return {}

    db = SessionLocal()
    try:
        out: dict[tuple[str, str], Document] = {}
        for doc_id_s, keys in by_doc.items():
            out.update(
                _load_doc_hierarchy_docs(
                    db=db,
                    doc_id_s=doc_id_s,
                    tenant_uuid=tenant_uuid,
                    keys=keys,
                    desired_pipeline_by_doc=desired_pipeline_by_doc,
                )
            )
        return out
    finally:
        db.close()

from typing import Any
from uuid import UUID

from langchain_core.documents import Document
from sqlalchemy import or_

from app.rag.core.logging import get_logger

logger = get_logger(__name__)
_FALLBACK_LOG_MESSAGE = "Ignoring non-critical retrieval orchestrator fallback failure: %s"


def _bounded_text(value: Any, *, limit: int) -> str:
    text = str(value).strip()
    return text[:limit] if text else ""


def safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, Any] = {}
    schema = _bounded_text(raw.get("schema"), limit=80)
    if schema:
        out["schema"] = schema
    kind = _bounded_text(raw.get("kind"), limit=50)
    if kind:
        out["kind"] = kind
    try:
        if raw.get("hops") is not None:
            out["hops"] = int(raw.get("hops") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug(_FALLBACK_LOG_MESSAGE, exc)

    nodes = _safe_kg_path_items(
        raw.get("nodes"),
        allowed_keys=("entity_id", "type", "event_id", "document_id", "chunk_id"),
    )
    if nodes:
        out["nodes"] = nodes

    edges = _safe_kg_path_items(
        raw.get("edges"),
        allowed_keys=(
            "entity_id",
            "event_id",
            "document_id",
            "chunk_id",
            "relation_id",
            "predicate",
            "confidence_bucket",
            "evidence_source",
        ),
    )
    if edges:
        out["edges"] = edges

    return out or None


def _safe_kg_path_items(raw_items: Any, *, allowed_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list) or not raw_items:
        return []
    items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        item: dict[str, Any] = {}
        kind = _bounded_text(raw_item.get("kind"), limit=30)
        if kind:
            item["kind"] = kind
        for key in allowed_keys:
            value = raw_item.get(key)
            if value is None:
                continue
            text = _bounded_text(value, limit=200)
            if text:
                item[key] = text
        if item:
            items.append(item)
        if len(items) >= 10:
            break
    return items


def build_desired_pipeline_by_doc(docs: list[Document]) -> dict[str, str]:
    desired_pipeline_by_doc: dict[str, str] = {}
    for doc in docs or []:
        if doc is None:
            continue
        meta = doc.metadata or {}
        doc_id = str(meta.get("document_id") or "").strip()
        if not doc_id:
            continue
        pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
        if not pipeline_key:
            pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
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
        doc_id_s = str(doc_id or "").strip()
        node_key_s = str(node_key or "").strip()
        if not doc_id_s or not node_key_s:
            continue
        by_doc.setdefault(doc_id_s, set()).add(node_key_s)
    return by_doc


def chunk_document_from_row(ck: Any) -> Document | None:
    meta = dict(getattr(ck, "doc_metadata", None) or {})
    cid = str(getattr(ck, "id", "") or "")
    meta.setdefault("tenant_id", str(getattr(ck, "tenant_id", "") or ""))
    meta.setdefault("document_id", str(getattr(ck, "document_id", "") or ""))
    meta.setdefault("chunk_id", cid)
    meta.setdefault("chunk_index", int(getattr(ck, "chunk_index", 0) or 0))
    page_number = getattr(ck, "page_number", None)
    if page_number is not None:
        meta.setdefault("page", int(page_number))
        meta.setdefault("page_number", int(page_number))
    start_char = getattr(ck, "start_char", None)
    end_char = getattr(ck, "end_char", None)
    if start_char is not None:
        meta.setdefault("start_char", int(start_char))
    if end_char is not None:
        meta.setdefault("end_char", int(end_char))
    if not meta.get("source"):
        meta["source"] = "unknown"

    node_key = str(meta.get("hierarchy_node_key") or meta.get("chunk_key") or "").strip()
    if not node_key:
        return None
    return Document(
        page_content=str(getattr(ck, "content", None) or ""),
        metadata=meta,
        id=cid or meta.get("chunk_id"),
    )


def _matches_desired_pipeline(
    *,
    chunk: Any,
    desired_pipeline_by_doc: dict[str, str],
) -> bool:
    desired = desired_pipeline_by_doc.get(str(chunk.document_id))
    if not desired:
        return True
    meta = dict(getattr(chunk, "doc_metadata", None) or {})
    chunk_pipeline_key = str(meta.get("doc_pipeline_key") or "").strip()
    if not chunk_pipeline_key:
        pipeline_hash = str(meta.get("pipeline_hash") or "").strip()
        if pipeline_hash:
            chunk_pipeline_key = f"{chunk.document_id}:{pipeline_hash}"
    return bool(chunk_pipeline_key and chunk_pipeline_key == desired)


def _fetch_doc_hierarchy_chunks(
    *,
    db: Any,
    doc_uuid: UUID,
    tenant_uuid: UUID | None,
    keys_list: list[str],
) -> list[Any]:
    from app.models.document import DocumentChunk

    query = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_uuid)
    if tenant_uuid is not None:
        query = query.filter(DocumentChunk.tenant_id == tenant_uuid)
    query = query.filter(
        or_(
            DocumentChunk.doc_metadata["hierarchy_node_key"].astext.in_(keys_list),  # type: ignore[attr-defined]
            DocumentChunk.doc_metadata["chunk_key"].astext.in_(keys_list),  # type: ignore[attr-defined]
        )
    )
    return list(query.all())


def _load_doc_hierarchy_docs(
    *,
    db: Any,
    doc_id_s: str,
    tenant_uuid: UUID | None,
    keys: set[str],
    desired_pipeline_by_doc: dict[str, str],
) -> dict[tuple[str, str], Document]:
    try:
        doc_uuid = UUID(doc_id_s)
    except (TypeError, ValueError, AttributeError):
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
        node_key_s = str(
            document.metadata.get("hierarchy_node_key") or document.metadata.get("chunk_key") or ""
        ).strip()
        out[(str(chunk.document_id), node_key_s)] = document
    return out


def fetch_hierarchy_expansion_docs(
    pairs: set[tuple[str, str]],
    *,
    tenant_uuid: UUID | None,
    desired_pipeline_by_doc: dict[str, str],
) -> dict[tuple[str, str], Document]:
    from app.core.database import SessionLocal

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
        try:
            db.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug(_FALLBACK_LOG_MESSAGE, exc)

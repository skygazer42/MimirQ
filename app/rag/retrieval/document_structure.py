
from typing import Any
from uuid import UUID

from app.rag.core.logging import get_logger

logger = get_logger(__name__)

_DOCUMENT_STRUCTURE_SCHEMA = "mimirq.document_structure.v1"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any, *, max_len: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    return text[:max_len]


def _slug(value: str) -> str:
    raw = _clean_text(value, max_len=120).lower()
    slug = "".join(char if char.isalnum() or "\u4e00" <= char <= "\u9fff" else "-" for char in raw)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "section"


def _coerce_path(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_clean_text(v, max_len=120) for v in value if _clean_text(v, max_len=120)]
    if isinstance(value, str) and value.strip():
        normalized = value.replace("->", "/")
        for separator in (">", "›", "»", "|", "｜", "→"):
            normalized = normalized.replace(separator, "/")
        return [_clean_text(v, max_len=120) for v in normalized.split("/") if _clean_text(v, max_len=120)]
    return []


def _extract_chunk_path(chunk: Any) -> list[str]:
    meta = _as_dict(getattr(chunk, "doc_metadata", None))
    for key in (
        "header_path",
        "outline_path",
        "section_path",
        "heading_path",
        "hierarchy_path",
        "breadcrumbs",
        "headers",
    ):
        path = _coerce_path(meta.get(key))
        if path:
            return path

    for key in ("section_title", "heading", "title", "header"):
        title = _clean_text(meta.get(key), max_len=120)
        if title:
            return [title]

    idx = getattr(chunk, "chunk_index", None)
    try:
        return [f"Chunk {int(idx) + 1}"]
    except Exception:
        return ["Chunk"]


def _node_template(*, title: str, path: list[str], node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "title": title,
        "path": list(path),
        "node_key": None,
        "family_key": None,
        "chunk_ids": [],
        "chunk_indexes": [],
        "page_start": None,
        "page_end": None,
        "children": [],
    }


def _update_page_range(node: dict[str, Any], page: Any) -> None:
    try:
        page_int = int(page)
    except Exception:
        return
    if page_int <= 0:
        return
    cur_start = node.get("page_start")
    cur_end = node.get("page_end")
    node["page_start"] = page_int if cur_start is None else min(int(cur_start), page_int)
    node["page_end"] = page_int if cur_end is None else max(int(cur_end), page_int)


def _append_unique(values: list[Any], value: Any) -> None:
    if value is None or value in values:
        return
    values.append(value)


def build_document_structure_from_chunks(
    *,
    document: Any,
    chunks: list[Any],
    max_nodes: int = 200,
) -> dict[str, Any]:
    """
    Build a PageIndex-style document structure from existing chunk metadata.

    This intentionally does not store a new manifest or include raw chunk text.
    It reuses heading / hierarchy metadata already produced by MimirQ chunkers.
    """

    max_nodes = max(1, min(int(max_nodes or 200), 1000))
    doc_meta = _as_dict(getattr(document, "doc_metadata", None))
    document_id = str(getattr(document, "id", "") or "")
    root_nodes: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}
    truncated = False

    for chunk in sorted(chunks or [], key=lambda c: (getattr(c, "chunk_index", 0) or 0, str(getattr(c, "id", "")))):
        path = _extract_chunk_path(chunk)
        if not path:
            continue

        parent_children = root_nodes
        parent_slug_parts: list[str] = []
        current_node: dict[str, Any] | None = None
        for title in path:
            parent_slug_parts.append(_slug(title))
            node_id = "/".join(parent_slug_parts)
            current_node = by_path.get(node_id)
            if current_node is None:
                if len(by_path) >= max_nodes:
                    truncated = True
                    break
                current_node = _node_template(title=title, path=path[: len(parent_slug_parts)], node_id=node_id)
                by_path[node_id] = current_node
                parent_children.append(current_node)
            _update_page_range(current_node, getattr(chunk, "page_number", None))
            parent_children = current_node["children"]

        if current_node is None:
            continue

        meta = _as_dict(getattr(chunk, "doc_metadata", None))
        chunk_id = str(getattr(chunk, "id", "") or "")
        if chunk_id:
            _append_unique(current_node["chunk_ids"], chunk_id)
        try:
            _append_unique(current_node["chunk_indexes"], int(getattr(chunk, "chunk_index", 0)))
        except Exception as exc:
            logger.debug("Ignoring document structure chunk index append failure: %s", exc)

        node_key = _clean_text(meta.get("hierarchy_node_key") or meta.get("node_key"), max_len=200)
        if node_key:
            current_node["node_key"] = node_key
        family_key = _clean_text(meta.get("hierarchy_family_key") or meta.get("family_collapse_key"), max_len=200)
        if family_key:
            current_node["family_key"] = family_key

    return {
        "schema": _DOCUMENT_STRUCTURE_SCHEMA,
        "document": {
            "document_id": document_id,
            "filename": str(getattr(document, "filename", "") or ""),
            "file_type": str(getattr(document, "file_type", "") or ""),
            "page_count": doc_meta.get("page_count"),
            "description": doc_meta.get("doc_description") or doc_meta.get("description"),
        },
        "nodes": root_nodes,
        "node_count": int(len(by_path)),
        "source_chunk_count": int(len(chunks or [])),
        "truncated": bool(truncated),
    }


def _iter_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    stack = list(reversed(nodes or []))
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        out.append(node)
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(reversed(children))
    return out


def explain_citations_with_structure(
    *,
    citations: list[dict[str, Any]],
    structures_by_document: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    chunk_to_node: dict[tuple[str, str], dict[str, Any]] = {}
    for doc_id, structure in (structures_by_document or {}).items():
        nodes = _iter_nodes((structure or {}).get("nodes") or [])
        for node in nodes:
            for chunk_id in node.get("chunk_ids") or []:
                chunk_to_node[(str(doc_id), str(chunk_id))] = node

    trace: list[dict[str, Any]] = []
    for idx, citation in enumerate(citations or []):
        if not isinstance(citation, dict):
            continue
        doc_id = str(citation.get("document_id") or "")
        chunk_id = str(citation.get("chunk_id") or citation.get("id") or "")
        node = chunk_to_node.get((doc_id, chunk_id))
        if not node:
            trace.append(
                {
                    "citation_index": idx,
                    "document_id": doc_id,
                    "chunk_id": chunk_id,
                    "source": citation.get("source"),
                    "matched": False,
                    "node_id": None,
                    "title": None,
                    "path": [],
                    "page_start": None,
                    "page_end": None,
                    "family_key": None,
                }
            )
            continue

        trace.append(
            {
                "citation_index": idx,
                "document_id": doc_id,
                "chunk_id": chunk_id,
                "source": citation.get("source"),
                "matched": True,
                "node_id": node.get("node_id"),
                "title": node.get("title"),
                "path": list(node.get("path") or []),
                "page_start": node.get("page_start"),
                "page_end": node.get("page_end"),
                "family_key": node.get("family_key"),
            }
        )
    return trace


def load_document_structure(
    *,
    db: Any,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    document_id: UUID,
    max_nodes: int = 200,
) -> dict[str, Any]:
    from app.core.pipeline_versions import build_doc_pipeline_key, get_active_pipeline_hash
    from app.models.document import Document as DBDocument
    from app.models.document import DocumentChunk
    from app.services.document_access import filter_allowed_document_ids

    allowed = set(filter_allowed_document_ids(db, tenant_id, account_id, [document_id]))
    if document_id not in allowed:
        return {
            "schema": _DOCUMENT_STRUCTURE_SCHEMA,
            "document": {"document_id": str(document_id)},
            "nodes": [],
            "node_count": 0,
            "source_chunk_count": 0,
            "truncated": False,
            "error": "No document access",
        }

    document = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id == document_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.disabled_at.is_(None),
        )
        .first()
    )
    if not document:
        return {
            "schema": _DOCUMENT_STRUCTURE_SCHEMA,
            "document": {"document_id": str(document_id)},
            "nodes": [],
            "node_count": 0,
            "source_chunk_count": 0,
            "truncated": False,
            "error": "Document not found",
        }

    q = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.disabled_at.is_(None),
        )
        .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
    )
    active_hash = get_active_pipeline_hash(getattr(document, "doc_metadata", None))
    active_key = build_doc_pipeline_key(document_id, active_hash) if active_hash else None
    chunks = []
    if active_key:
        chunks = q.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == active_key).all()  # type: ignore[attr-defined]
    if not chunks:
        chunks = q.all()

    return build_document_structure_from_chunks(document=document, chunks=chunks, max_nodes=max_nodes)


def load_structures_for_citations(
    *,
    db: Any,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID | None,
    citations: list[dict[str, Any]],
    max_documents: int = 5,
    max_nodes: int = 120,
) -> dict[str, dict[str, Any]]:
    if dataset_id is None:
        return {}
    doc_ids: list[UUID] = []
    seen: set[UUID] = set()
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        raw = citation.get("document_id")
        if not raw:
            continue
        try:
            doc_id = UUID(str(raw))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if doc_id in seen:
            continue
        seen.add(doc_id)
        doc_ids.append(doc_id)
        if len(doc_ids) >= max(1, int(max_documents or 1)):
            break

    return {
        str(doc_id): load_document_structure(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            document_id=doc_id,
            max_nodes=max_nodes,
        )
        for doc_id in doc_ids
    }


__all__ = [
    "build_document_structure_from_chunks",
    "explain_citations_with_structure",
    "load_document_structure",
    "load_structures_for_citations",
]

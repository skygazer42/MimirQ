"""Parsed-document IO helpers: logical source metadata, markdown joins, parse-cache serialization."""
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.parsing.artifact_stats import POSITION_TAG_RE


def _logical_source_from_db_document(db_document: Any, *, file_path: Path) -> str:
    meta = getattr(db_document, "doc_metadata", None)
    meta = dict(meta or {}) if isinstance(meta, dict) else {}
    user_meta = meta.get("user") if isinstance(meta.get("user"), dict) else {}
    for value in (
        meta.get("source_path"),
        user_meta.get("source_rel_path") if isinstance(user_meta, dict) else None,
        getattr(db_document, "filename", None),
        file_path.name,
    ):
        text = str(value or "").strip()
        if text:
            return text
    return str(file_path)


def _attach_logical_source_metadata(
    documents: list[Document] | None,
    *,
    db_document: Any,
    file_path: Path,
) -> list[Document]:
    if not documents:
        return []
    source = _logical_source_from_db_document(db_document, file_path=file_path)
    filename = str(getattr(db_document, "filename", None) or file_path.name or "").strip()
    out: list[Document] = []
    for doc in documents:
        meta = dict(doc.metadata or {})
        parser_source = str(meta.get("source") or "").strip()
        if parser_source and parser_source != source:
            meta.setdefault("parser_source", parser_source)
        meta["source"] = source
        meta["source_path"] = source
        if filename:
            meta.setdefault("filename", filename)
            meta.setdefault("file_name", filename)
        out.append(Document(page_content=doc.page_content or "", metadata=meta, id=getattr(doc, "id", None)))
    return out


def _get_position_tagged_markdown(doc: Document) -> str:
    metadata = getattr(doc, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    tagged = metadata.get("position_tagged_markdown")
    return str(tagged or "").replace("\x00", "").strip() if isinstance(tagged, str) else ""


def _join_document_page_content(documents: list[Document] | None) -> str:
    parts = [POSITION_TAG_RE.sub("", str(d.page_content or "").replace("\x00", "")).strip() for d in (documents or [])]
    return "\n\n".join(parts).strip()


def _join_original_markdown_for_persistence(documents: list[Document] | None) -> str:
    parts: list[str] = []
    for doc in documents or []:
        parts.append(_get_position_tagged_markdown(doc) or str(doc.page_content or "").replace("\x00", ""))
    return "\n\n".join(parts).strip()


def _serialize_documents_for_parse_cache(items: list[Document] | None) -> list[dict[str, Any]] | None:
    if items is None:
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(
            {
                "page_content": str(item.page_content or ""),
                "metadata": dict(item.metadata or {}),
                "id": getattr(item, "id", None),
            }
        )
    return out


def _deserialize_documents_from_parse_cache(items: list[dict[str, Any]] | None) -> list[Document] | None:
    if items is None:
        return None
    out: list[Document] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(
            Document(
                page_content=str(item.get("page_content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                id=item.get("id") if isinstance(item.get("id"), str) else None,
            )
        )
    return out

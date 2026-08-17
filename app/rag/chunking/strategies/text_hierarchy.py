"""
Plain-text hierarchy chunking strategy.

Two-level hierarchy:
- paragraph nodes
- sentence nodes (children of paragraphs)

This is designed to work with the retrieval-time hierarchy overlay:
- hierarchy expansion (parent/sibling)
- family collapse + cross-query aggregation
- tree dedup (ancestor wins)

It intentionally does NOT attempt to build a full offline tree index.
"""


from typing import Any

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown


def _extract_hierarchy_items(data: object) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(data, dict):
        return [], []
    paragraphs = data.get("paragraphs")
    sentences = data.get("sentences")
    paragraph_items = paragraphs if isinstance(paragraphs, list) else []
    sentence_items = sentences if isinstance(sentences, list) else []
    return paragraph_items, sentence_items


def _group_sentences_by_parent(sentences: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        parent_id = str(sentence.get("parent_id") or "").strip()
        if not parent_id:
            continue
        grouped.setdefault(parent_id, []).append(sentence)
    for sentence_items in grouped.values():
        sentence_items.sort(key=lambda item: int(item.get("index") or 0))
    return grouped


def _build_paragraph_document(base_meta: dict[str, Any], paragraph: dict[str, Any], chunk_index: int) -> Document | None:
    paragraph_text = str(paragraph.get("text") or "")
    if not paragraph_text.strip():
        return None

    start = int(paragraph.get("start") or 0)
    end = int(paragraph.get("end") or (start + len(paragraph_text)))
    parent_id = str(paragraph.get("id") or paragraph.get("hierarchy_node_key") or "").strip()
    if not parent_id:
        return None

    meta = dict(base_meta)
    meta.update(
        {
            "chunk_strategy": "text_hierarchy",
            "chunk_role": "paragraph",
            "start_char": start,
            "end_char": end,
            "parent_id": parent_id,
            "hierarchy_basis": "text_hierarchy",
            "hierarchy_level": paragraph.get("hierarchy_level") or "paragraph",
            "hierarchy_node_key": paragraph.get("hierarchy_node_key") or parent_id,
            "hierarchy_family_key": paragraph.get("hierarchy_family_key") or parent_id,
            "hierarchy_parent_key": None,
            "hierarchy_prev_sibling_key": paragraph.get("hierarchy_prev_sibling_key"),
            "hierarchy_next_sibling_key": paragraph.get("hierarchy_next_sibling_key"),
            "hierarchy_sibling_index": paragraph.get("hierarchy_sibling_index"),
            "tokens_est": paragraph.get("tokens_est"),
            "chunk_index": chunk_index,
        }
    )
    return Document(page_content=paragraph_text, metadata=meta)


def _build_sentence_document(
    base_meta: dict[str, Any],
    sentence: dict[str, Any],
    parent_id: str,
    parent_start: int,
    chunk_index: int,
) -> Document | None:
    sentence_text = str(sentence.get("text") or "")
    if not sentence_text.strip():
        return None

    start = int(sentence.get("start") or parent_start)
    end = int(sentence.get("end") or (start + len(sentence_text)))
    sentence_id = str(sentence.get("id") or sentence.get("hierarchy_node_key") or "").strip()
    if not sentence_id:
        return None

    meta = dict(base_meta)
    meta.update(
        {
            "chunk_strategy": "text_hierarchy",
            "chunk_role": "sentence",
            "start_char": start,
            "end_char": end,
            "parent_id": parent_id,
            "hierarchy_basis": "text_hierarchy",
            "hierarchy_level": sentence.get("hierarchy_level") or "sentence",
            "hierarchy_node_key": sentence.get("hierarchy_node_key") or sentence_id,
            "hierarchy_family_key": sentence.get("hierarchy_family_key") or parent_id,
            "hierarchy_parent_key": parent_id,
            "hierarchy_prev_sibling_key": sentence.get("hierarchy_prev_sibling_key"),
            "hierarchy_next_sibling_key": sentence.get("hierarchy_next_sibling_key"),
            "hierarchy_sibling_index": sentence.get("hierarchy_sibling_index"),
            "tokens_est": sentence.get("tokens_est"),
            "chunk_index": chunk_index,
        }
    )
    return Document(page_content=sentence_text, metadata=meta)


class TextHierarchyChunker(BaseChunker):
    """
    Hierarchical chunker for plain text.

    Notes:
    - `chunk_size/chunk_overlap` are currently unused; splitting is structure-based
      (blank lines -> paragraphs, punctuation -> sentences).
    - We reuse the existing paragraph/sentence splitter used for Markdown preview,
      but override `chunk_strategy` + `hierarchy_basis` to keep metadata explicit.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size or 0)
        self.chunk_overlap = int(chunk_overlap or 0)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            paragraphs, sentences = _extract_hierarchy_items(hierarchical_chunk_markdown(text) or {})
            sentences_by_parent = _group_sentences_by_parent(sentences)

            for paragraph in paragraphs:
                if not isinstance(paragraph, dict):
                    continue
                paragraph_doc = _build_paragraph_document(base_meta, paragraph, len(out))
                if paragraph_doc is None:
                    continue
                out.append(paragraph_doc)

                parent_id = str(paragraph_doc.metadata["parent_id"])
                parent_start = int(paragraph_doc.metadata["start_char"])
                for sentence in sentences_by_parent.get(parent_id, []):
                    sentence_doc = _build_sentence_document(base_meta, sentence, parent_id, parent_start, len(out))
                    if sentence_doc is not None:
                        out.append(sentence_doc)

        return out


__all__ = ["TextHierarchyChunker"]

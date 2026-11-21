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

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.hierarchical import hierarchical_chunk_markdown


def _group_sentences_by_parent(sentences: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sentence in sentences:
        parent_id = sentence["parent_id"].strip()
        if not parent_id:
            continue
        grouped.setdefault(parent_id, []).append(sentence)
    for sentence_items in grouped.values():
        sentence_items.sort(key=lambda item: item["index"])
    return grouped


def _build_paragraph_document(
    base_meta: dict[str, Any], paragraph: dict[str, Any], chunk_index: int
) -> Document | None:
    paragraph_text = paragraph["text"]
    if not paragraph_text.strip():
        return None

    start = paragraph["start"]
    end = paragraph["end"]
    parent_id = paragraph["id"].strip()
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
            "hierarchy_level": paragraph["hierarchy_level"],
            "hierarchy_node_key": paragraph["hierarchy_node_key"],
            "hierarchy_family_key": paragraph["hierarchy_family_key"],
            "hierarchy_parent_key": None,
            "hierarchy_prev_sibling_key": paragraph["hierarchy_prev_sibling_key"],
            "hierarchy_next_sibling_key": paragraph["hierarchy_next_sibling_key"],
            "hierarchy_sibling_index": paragraph["hierarchy_sibling_index"],
            "tokens_est": paragraph["tokens_est"],
            "chunk_index": chunk_index,
        }
    )
    return Document(page_content=paragraph_text, metadata=meta)


def _build_sentence_document(
    base_meta: dict[str, Any],
    sentence: dict[str, Any],
    parent_id: str,
    chunk_index: int,
) -> Document | None:
    sentence_text = sentence["text"]
    if not sentence_text.strip():
        return None

    start = sentence["start"]
    end = sentence["end"]
    sentence_id = sentence["id"].strip()
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
            "hierarchy_level": sentence["hierarchy_level"],
            "hierarchy_node_key": sentence["hierarchy_node_key"],
            "hierarchy_family_key": sentence["hierarchy_family_key"],
            "hierarchy_parent_key": parent_id,
            "hierarchy_prev_sibling_key": sentence["hierarchy_prev_sibling_key"],
            "hierarchy_next_sibling_key": sentence["hierarchy_next_sibling_key"],
            "hierarchy_sibling_index": sentence["hierarchy_sibling_index"],
            "tokens_est": sentence["tokens_est"],
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

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            data = hierarchical_chunk_markdown(text)
            paragraphs = data["paragraphs"]
            sentences = data["sentences"]
            sentences_by_parent = _group_sentences_by_parent(sentences)

            for paragraph in paragraphs:
                paragraph_doc = _build_paragraph_document(base_meta, paragraph, len(out))
                if paragraph_doc is None:
                    continue
                out.append(paragraph_doc)

                parent_id = paragraph_doc.metadata["parent_id"]
                for sentence in sentences_by_parent.get(parent_id, []):
                    sentence_doc = _build_sentence_document(base_meta, sentence, parent_id, len(out))
                    if sentence_doc is not None:
                        out.append(sentence_doc)

        return out


__all__ = ["TextHierarchyChunker"]

"""
Markdown hierarchy chunking strategy.

Goal: produce a lightweight, deterministic two-level hierarchy for Markdown:
paragraph -> sentence, with stable hierarchy metadata (node/parent/sibling keys).

This is intentionally "overlay-first":
- We do NOT build a separate offline tree index.
- We emit plain chunks with hierarchy metadata so retrieval-time expansion/collapse
  can treat them as a tree (similar to KohakuRAG's online behavior).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.strategies.markup import _update_heading_path
from app.rag.ingestion.chunking.strategies.markup.markdown import _iter_markdown_heading_lines
from app.rag.ingestion.chunking.utils.hierarchical import hierarchical_chunk_markdown


@dataclass(frozen=True)
class _Heading:
    pos: int
    level: int
    text: str


def _iter_markdown_headings(text: str) -> list[_Heading]:
    return [
        _Heading(pos=start, level=level, text=title[:200])
        for start, _, level, title in _iter_markdown_heading_lines(text)
    ]


def _group_sentences_by_parent(sentences: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sentence in sentences:
        parent_id = sentence["parent_id"].strip()
        if not parent_id:
            continue
        grouped.setdefault(parent_id, []).append(sentence)

    for sentence_list in grouped.values():
        sentence_list.sort(key=lambda item: item["index"])
    return grouped


def _header_path_resolver(text: str) -> Callable[[int], str | None]:
    headings = _iter_markdown_headings(text)
    h_cursor = 0
    stack: list[tuple[int, str]] = []

    def resolve(start_char: int) -> str | None:
        nonlocal h_cursor
        start_i = max(0, start_char)
        while h_cursor < len(headings) and headings[h_cursor].pos <= start_i:
            heading = headings[h_cursor]
            _update_heading_path(stack, level=heading.level, heading_text=heading.text)
            h_cursor += 1
        path = " > ".join(title for _, title in stack)
        return path if path else None

    return resolve


def _paragraph_metadata(
    base_meta: dict[str, Any],
    paragraph: dict[str, Any],
    *,
    start: int,
    end: int,
    header_path: str | None,
    chunk_index: int,
) -> dict[str, Any]:
    meta = dict(base_meta)
    meta.update(
        {
            "chunk_strategy": "markdown_hierarchy",
            "chunk_role": "paragraph",
            "start_char": start,
            "end_char": end,
            "hierarchy_basis": paragraph["hierarchy_basis"],
            "hierarchy_level": paragraph["hierarchy_level"],
            "hierarchy_node_key": paragraph["hierarchy_node_key"],
            "hierarchy_family_key": paragraph["hierarchy_family_key"],
            "hierarchy_parent_key": paragraph["hierarchy_parent_key"],
            "hierarchy_prev_sibling_key": paragraph["hierarchy_prev_sibling_key"],
            "hierarchy_next_sibling_key": paragraph["hierarchy_next_sibling_key"],
            "hierarchy_sibling_index": paragraph["hierarchy_sibling_index"],
            "tokens_est": paragraph["tokens_est"],
            "chunk_index": chunk_index,
        }
    )
    if header_path:
        meta.setdefault("header_path", header_path)
        meta.setdefault("header_context", header_path)
    return meta


def _sentence_documents(
    *,
    base_meta: dict[str, Any],
    paragraph_id: str,
    sentences: list[dict[str, Any]],
    header_path: str | None,
    starting_chunk_index: int,
) -> list[Document]:
    out: list[Document] = []
    for sentence in sentences:
        text = sentence["text"]
        if not text.strip():
            continue

        start = sentence["start"]
        end = sentence["end"]
        meta = dict(base_meta)
        meta.update(
            {
                "chunk_strategy": "markdown_hierarchy",
                "chunk_role": "sentence",
                "start_char": start,
                "end_char": end,
                "parent_id": paragraph_id,
                "hierarchy_basis": sentence["hierarchy_basis"],
                "hierarchy_level": sentence["hierarchy_level"],
                "hierarchy_node_key": sentence["hierarchy_node_key"],
                "hierarchy_family_key": sentence["hierarchy_family_key"],
                "hierarchy_parent_key": sentence["hierarchy_parent_key"],
                "hierarchy_prev_sibling_key": sentence["hierarchy_prev_sibling_key"],
                "hierarchy_next_sibling_key": sentence["hierarchy_next_sibling_key"],
                "hierarchy_sibling_index": sentence["hierarchy_sibling_index"],
                "tokens_est": sentence["tokens_est"],
                "chunk_index": starting_chunk_index + len(out),
            }
        )
        if header_path:
            meta.setdefault("header_path", header_path)
            meta.setdefault("header_context", header_path)
        out.append(Document(page_content=text, metadata=meta))
    return out


def _split_markdown_document(doc: Document) -> list[Document]:
    text = doc.page_content
    if not text.strip():
        return []

    base_meta = dict(doc.metadata)
    data = hierarchical_chunk_markdown(text)
    paragraphs = data["paragraphs"]
    sentences = data["sentences"]
    sentences_by_parent = _group_sentences_by_parent(sentences)
    resolve_header_path = _header_path_resolver(text)

    out: list[Document] = []
    for paragraph in paragraphs:
        paragraph_text = paragraph["text"]
        if not paragraph_text.strip():
            continue

        start = paragraph["start"]
        end = paragraph["end"]
        header_path = resolve_header_path(start)
        paragraph_meta = _paragraph_metadata(
            base_meta,
            paragraph,
            start=start,
            end=end,
            header_path=header_path,
            chunk_index=len(out),
        )
        out.append(Document(page_content=paragraph_text, metadata=paragraph_meta))

        paragraph_id = paragraph["id"].strip()
        out.extend(
            _sentence_documents(
                base_meta=base_meta,
                paragraph_id=paragraph_id,
                sentences=sentences_by_parent.get(paragraph_id, []),
                header_path=header_path,
                starting_chunk_index=len(out),
            )
        )
    return out


class MarkdownHierarchyChunker(BaseChunker):
    """
    Hierarchical Markdown chunker.

    Output:
    - paragraph nodes (hierarchy_level="paragraph", hierarchy_parent_key=None)
    - sentence nodes (hierarchy_level="sentence", hierarchy_parent_key=<paragraph node key>)
    """

    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        # Not used today (hierarchy chunking is structure-based), but keep signature
        # compatible with the factory and future tuning.
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            out.extend(_split_markdown_document(doc))
        return out


__all__ = ["MarkdownHierarchyChunker"]

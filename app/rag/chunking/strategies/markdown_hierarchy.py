"""
Markdown hierarchy chunking strategy.

Goal: produce a lightweight, deterministic two-level hierarchy for Markdown:
paragraph -> sentence, with stable hierarchy metadata (node/parent/sibling keys).

This is intentionally "overlay-first":
- We do NOT build a separate offline tree index.
- We emit plain chunks with hierarchy metadata so retrieval-time expansion/collapse
  can treat them as a tree (similar to KohakuRAG's online behavior).
"""

from dataclasses import dataclass

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown


@dataclass(frozen=True)
class _Heading:
    pos: int
    level: int
    text: str


def _iter_markdown_headings(text: str) -> list[_Heading]:
    out: list[_Heading] = []
    offset = 0
    for raw_line in (text or "").splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        parsed = parse_markdown_hash_heading(raw_line)
        if parsed is None:
            continue
        level, title = parsed
        if not title:
            continue
        out.append(_Heading(pos=int(line_start), level=int(level), text=str(title)[:200]))
    return out


def _update_heading_stack(stack: list[str], *, heading: _Heading) -> list[str]:
    level = max(1, min(int(heading.level), 6))
    trimmed = stack[: max(0, level - 1)]
    while len(trimmed) < level:
        trimmed.append("")
    trimmed[level - 1] = heading.text
    # Drop empty tails to keep "A > B >" clean.
    while trimmed and not str(trimmed[-1] or "").strip():
        trimmed.pop()
    return trimmed


def _group_sentences_by_parent(sentences: list[object]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for sentence in sentences:
        if not isinstance(sentence, dict):
            continue
        parent_id = str(sentence.get("parent_id") or "").strip()
        if not parent_id:
            continue
        grouped.setdefault(parent_id, []).append(sentence)

    for sentence_list in grouped.values():
        sentence_list.sort(key=lambda item: int(item.get("index") or 0))
    return grouped


def _header_path_resolver(text: str):
    headings = _iter_markdown_headings(text)
    h_cursor = 0
    stack: list[str] = []

    def resolve(start_char: int) -> str | None:
        nonlocal h_cursor, stack
        start_i = max(0, int(start_char or 0))
        while h_cursor < len(headings) and int(headings[h_cursor].pos) <= start_i:
            stack = _update_heading_stack(stack, heading=headings[h_cursor])
            h_cursor += 1
        path = " > ".join([part for part in stack if str(part or "").strip()])
        return path if path else None

    return resolve


def _paragraph_metadata(
    base_meta: dict, paragraph: dict, *, start: int, end: int, header_path: str | None, chunk_index: int
) -> dict:
    meta = dict(base_meta)
    meta.update(
        {
            "chunk_strategy": "markdown_hierarchy",
            "chunk_role": "paragraph",
            "start_char": start,
            "end_char": end,
            "hierarchy_basis": paragraph.get("hierarchy_basis"),
            "hierarchy_level": paragraph.get("hierarchy_level") or "paragraph",
            "hierarchy_node_key": paragraph.get("hierarchy_node_key") or paragraph.get("id"),
            "hierarchy_family_key": paragraph.get("hierarchy_family_key") or paragraph.get("id"),
            "hierarchy_parent_key": paragraph.get("hierarchy_parent_key"),
            "hierarchy_prev_sibling_key": paragraph.get("hierarchy_prev_sibling_key"),
            "hierarchy_next_sibling_key": paragraph.get("hierarchy_next_sibling_key"),
            "hierarchy_sibling_index": paragraph.get("hierarchy_sibling_index"),
            "tokens_est": paragraph.get("tokens_est"),
            "chunk_index": chunk_index,
        }
    )
    if header_path:
        meta.setdefault("header_path", header_path)
        meta.setdefault("header_context", header_path)
    return meta


def _sentence_documents(
    *,
    base_meta: dict,
    paragraph_id: str,
    sentences: list[dict],
    paragraph_start: int,
    header_path: str | None,
    starting_chunk_index: int,
) -> list[Document]:
    out: list[Document] = []
    for sentence in sentences:
        text = str(sentence.get("text") or "")
        if not text.strip():
            continue

        start = int(sentence.get("start") or paragraph_start)
        end = int(sentence.get("end") or (start + len(text)))
        meta = dict(base_meta)
        meta.update(
            {
                "chunk_strategy": "markdown_hierarchy",
                "chunk_role": "sentence",
                "start_char": start,
                "end_char": end,
                "parent_id": paragraph_id,
                "hierarchy_basis": sentence.get("hierarchy_basis"),
                "hierarchy_level": sentence.get("hierarchy_level") or "sentence",
                "hierarchy_node_key": sentence.get("hierarchy_node_key") or sentence.get("id"),
                "hierarchy_family_key": sentence.get("hierarchy_family_key") or paragraph_id,
                "hierarchy_parent_key": sentence.get("hierarchy_parent_key") or paragraph_id,
                "hierarchy_prev_sibling_key": sentence.get("hierarchy_prev_sibling_key"),
                "hierarchy_next_sibling_key": sentence.get("hierarchy_next_sibling_key"),
                "hierarchy_sibling_index": sentence.get("hierarchy_sibling_index"),
                "tokens_est": sentence.get("tokens_est"),
                "chunk_index": starting_chunk_index + len(out),
            }
        )
        if header_path:
            meta.setdefault("header_path", header_path)
            meta.setdefault("header_context", header_path)
        out.append(Document(page_content=text, metadata=meta))
    return out


def _split_markdown_document(doc: Document) -> list[Document]:
    text = doc.page_content or ""
    if not text.strip():
        return []

    base_meta = dict(doc.metadata or {})
    data = hierarchical_chunk_markdown(text) or {}
    paragraphs = data.get("paragraphs") if isinstance(data, dict) and isinstance(data.get("paragraphs"), list) else []
    sentences = data.get("sentences") if isinstance(data, dict) and isinstance(data.get("sentences"), list) else []
    sentences_by_parent = _group_sentences_by_parent(sentences)
    resolve_header_path = _header_path_resolver(text)

    out: list[Document] = []
    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            continue
        paragraph_text = str(paragraph.get("text") or "")
        if not paragraph_text.strip():
            continue

        start = int(paragraph.get("start") or 0)
        end = int(paragraph.get("end") or (start + len(paragraph_text)))
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

        paragraph_id = str(paragraph.get("id") or paragraph_meta.get("hierarchy_node_key") or "").strip()
        out.extend(
            _sentence_documents(
                base_meta=base_meta,
                paragraph_id=paragraph_id,
                sentences=sentences_by_parent.get(paragraph_id, []),
                paragraph_start=start,
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

    def __init__(self, chunk_size: int, chunk_overlap: int):
        # Not used today (hierarchy chunking is structure-based), but keep signature
        # compatible with the factory and future tuning.
        self.chunk_size = int(chunk_size or 0)
        self.chunk_overlap = int(chunk_overlap or 0)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            out.extend(_split_markdown_document(doc))
        return out


__all__ = ["MarkdownHierarchyChunker"]

"""
Hierarchical Chunking for Markdown documents.

Two-level chunking:
- Paragraph level: Split by blank lines / Markdown headers / lists
- Sentence level: Split by sentence-ending punctuation

Returns chunk data with positions for frontend highlighting.
"""


import re
from typing import Any

from app.rag.core.hashing import stable_hash


def _estimate_tokens(text: str) -> int:
    """Roughly estimate token count: chars / 4."""
    return max(1, len(text) // 4)


_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_CODE_FENCE_RE = re.compile(r"^\s*```")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def _stable_markdown_node_key(*, level: str, start: int, end: int, text: str, parent_key: str | None = None) -> str:
    seed = "|".join(
        [
            str(level or ""),
            str(parent_key or ""),
            str(int(start)),
            str(int(end)),
            stable_hash(str(text or ""), length=None),
        ]
    )
    return f"md:{stable_hash(seed, length=32)}"


def apply_sibling_hierarchy_links(
    items: list[dict[str, Any]],
    *,
    key_field: str = "hierarchy_node_key",
    index_field: str = "hierarchy_sibling_index",
    prev_field: str = "hierarchy_prev_sibling_key",
    next_field: str = "hierarchy_next_sibling_key",
    overwrite: bool = False,
) -> None:
    keys = [str(item.get(key_field) or "").strip() or None for item in items]
    total = len(items)
    for idx, item in enumerate(items):
        prev_key = keys[idx - 1] if idx > 0 else None
        next_key = keys[idx + 1] if idx < (total - 1) else None
        if overwrite or item.get(index_field) is None:
            item[index_field] = int(idx)
        if overwrite or item.get(prev_field) is None:
            item[prev_field] = prev_key
        if overwrite or item.get(next_field) is None:
            item[next_field] = next_key


def apply_sequence_hierarchy_metadata(
    metas: list[dict[str, Any]],
    *,
    document_id: str,
    basis: str = "chunk_sequence",
    level: str = "chunk",
) -> None:
    if not metas:
        return

    for idx, meta in enumerate(metas):
        if not isinstance(meta, dict):
            continue
        chunk_index = meta.get("chunk_index")
        try:
            chunk_index_int = int(chunk_index) if chunk_index is not None else int(idx)
        except Exception:
            chunk_index_int = int(idx)

        node_key = str(meta.get("hierarchy_node_key") or meta.get("chunk_key") or f"{document_id}:{chunk_index_int}").strip()
        parent_key = str(meta.get("hierarchy_parent_key") or meta.get("parent_id") or "").strip() or None

        meta.setdefault("hierarchy_basis", str(basis or "chunk_sequence"))
        meta.setdefault("hierarchy_level", str(level or "chunk"))
        meta.setdefault("hierarchy_node_key", node_key)
        if parent_key is not None and meta.get("hierarchy_parent_key") is None:
            meta["hierarchy_parent_key"] = parent_key
        meta.setdefault("hierarchy_family_key", parent_key or node_key)

    apply_sibling_hierarchy_links(metas, overwrite=False)


def _split_paragraphs(text: str) -> list[tuple[str, int, int]]:
    """
    Split text into paragraph-like blocks while preserving offsets.

    Rules (conservative):
    - Blank lines split paragraphs.
    - Headings/list items/blockquote start new paragraphs.
    - Code fences are kept as a single paragraph (fenced block).
    - Tables (pipe rows) are kept as a single paragraph.

    Returns:
        List of (paragraph_text, start_pos, end_pos)
    """
    if not text:
        return []

    paragraphs: list[tuple[str, int, int]] = []
    buf: list[str] = []
    buf_start = 0
    offset = 0
    in_code = False
    in_table = False

    def flush(end_offset: int) -> None:
        nonlocal buf, buf_start, in_table
        if not buf:
            return
        seg = "".join(buf)
        if seg.strip():
            paragraphs.append((seg, buf_start, end_offset))
        buf = []
        buf_start = end_offset
        in_table = False

    for line in text.splitlines(keepends=True):
        line_start = offset
        line_end = offset + len(line)
        offset = line_end

        if _CODE_FENCE_RE.match(line):
            if not in_code and buf and "".join(buf).strip():
                flush(line_start)
            buf.append(line)
            in_code = not in_code
            if not in_code:
                flush(line_end)
            continue

        if in_code:
            buf.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            flush(line_start)
            buf_start = line_end
            continue

        is_table = bool(_TABLE_ROW_RE.match(line))
        if in_table and not is_table:
            flush(line_start)
            buf_start = line_start

        is_boundary = bool(_HEADING_RE.match(line) or _LIST_RE.match(line) or _BLOCKQUOTE_RE.match(line))
        if is_boundary and buf and "".join(buf).strip():
            flush(line_start)
            buf_start = line_start

        if is_table and not in_table and buf and "".join(buf).strip():
            flush(line_start)
            buf_start = line_start

        buf.append(line)
        in_table = is_table or in_table

    flush(len(text))
    return paragraphs


def _split_sentences(paragraph: str, base_offset: int) -> list[tuple[str, int, int]]:
    """
    Split paragraph into sentences (Chinese and English).

    Returns:
        List of (sentence_text, start_pos, end_pos) with absolute offsets
    """
    sentences = []
    pattern = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", re.S)

    for m in pattern.finditer(paragraph):
        sent = m.group()
        start = base_offset + m.start()
        end = base_offset + m.end()
        sentences.append((sent, start, end))

    # If no sentences found, return the whole paragraph
    if not sentences and paragraph.strip():
        sentences.append((paragraph, base_offset, base_offset + len(paragraph)))

    return sentences


def hierarchical_chunk_markdown(markdown: str) -> dict[str, list[dict]]:
    """
    Perform hierarchical chunking on markdown text.

    Args:
        markdown: The markdown text to chunk.

    Returns:
        Dict with 'paragraphs' and 'sentences' lists, each containing:
        - id: Unique chunk ID
        - level: 'paragraph' or 'sentence'
        - index: Position index
        - text: Chunk content
        - start: Start character position
        - end: End character position
        - tokens_est: Estimated token count
        - parent_id: (sentences only) Reference to parent paragraph
    """
    text = markdown or ""
    paragraphs = _split_paragraphs(text)

    paragraph_chunks: list[dict] = []
    sentence_chunks: list[dict] = []

    for p_idx, (p_text, start, end) in enumerate(paragraphs):
        if not p_text.strip():
            continue

        para_node_key = _stable_markdown_node_key(level="paragraph", start=start, end=end, text=p_text)
        para_id = para_node_key
        paragraph_chunk = {
            "id": para_id,
            "level": "paragraph",
            "index": p_idx,
            "text": p_text,
            "start": start,
            "end": end,
            "tokens_est": _estimate_tokens(p_text),
            "hierarchy_basis": "markdown_hierarchy",
            "hierarchy_level": "paragraph",
            "hierarchy_node_key": para_node_key,
            "hierarchy_family_key": para_node_key,
            "hierarchy_parent_key": None,
        }
        paragraph_chunks.append(paragraph_chunk)

        # Split paragraph into sentences
        sentences = _split_sentences(p_text, base_offset=start)
        paragraph_sentences: list[dict[str, Any]] = []
        for s_idx, (s_text, s_start, s_end) in enumerate(sentences):
            if not s_text.strip():
                continue
            sent_node_key = _stable_markdown_node_key(
                level="sentence",
                start=s_start,
                end=s_end,
                text=s_text,
                parent_key=para_node_key,
            )
            sentence_chunk = {
                "id": sent_node_key,
                "level": "sentence",
                "index": s_idx,
                "parent_id": para_id,
                "text": s_text,
                "start": s_start,
                "end": s_end,
                "tokens_est": _estimate_tokens(s_text),
                "hierarchy_basis": "markdown_hierarchy",
                "hierarchy_level": "sentence",
                "hierarchy_node_key": sent_node_key,
                "hierarchy_family_key": para_node_key,
                "hierarchy_parent_key": para_node_key,
            }
            sentence_chunks.append(sentence_chunk)
            paragraph_sentences.append(sentence_chunk)

        apply_sibling_hierarchy_links(paragraph_sentences, overwrite=True)

    apply_sibling_hierarchy_links(paragraph_chunks, overwrite=True)

    return {
        "paragraphs": paragraph_chunks,
        "sentences": sentence_chunks,
    }


__all__ = [
    "apply_sequence_hierarchy_metadata",
    "apply_sibling_hierarchy_links",
    "hierarchical_chunk_markdown",
]

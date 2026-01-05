"""
Hierarchical Chunking for Markdown documents.

Two-level chunking:
- Paragraph level: Split by blank lines / Markdown headers / lists
- Sentence level: Split by sentence-ending punctuation

Returns chunk data with positions for frontend highlighting.
"""
from __future__ import annotations

import re
import uuid
from typing import Dict, List, Tuple


def _estimate_tokens(text: str) -> int:
    """Roughly estimate token count: chars / 4."""
    return max(1, len(text) // 4)


_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|(?:\d{1,3}[.)]))\s+")
_BLOCKQUOTE_RE = re.compile(r"^\s*>")
_CODE_FENCE_RE = re.compile(r"^\s*```")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def _split_paragraphs(text: str) -> List[Tuple[str, int, int]]:
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

    paragraphs: List[Tuple[str, int, int]] = []
    buf: List[str] = []
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


def _split_sentences(paragraph: str, base_offset: int) -> List[Tuple[str, int, int]]:
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


def hierarchical_chunk_markdown(markdown: str) -> Dict[str, List[Dict]]:
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

    paragraph_chunks: List[Dict] = []
    sentence_chunks: List[Dict] = []

    for p_idx, (p_text, start, end) in enumerate(paragraphs):
        if not p_text.strip():
            continue

        para_id = str(uuid.uuid4())
        paragraph_chunks.append({
            "id": para_id,
            "level": "paragraph",
            "index": p_idx,
            "text": p_text,
            "start": start,
            "end": end,
            "tokens_est": _estimate_tokens(p_text),
        })

        # Split paragraph into sentences
        sentences = _split_sentences(p_text, base_offset=start)
        for s_idx, (s_text, s_start, s_end) in enumerate(sentences):
            if not s_text.strip():
                continue
            sentence_chunks.append({
                "id": str(uuid.uuid4()),
                "level": "sentence",
                "index": s_idx,
                "parent_id": para_id,
                "text": s_text,
                "start": s_start,
                "end": s_end,
                "tokens_est": _estimate_tokens(s_text),
            })

    return {
        "paragraphs": paragraph_chunks,
        "sentences": sentence_chunks,
    }

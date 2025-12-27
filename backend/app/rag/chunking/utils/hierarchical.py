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


def _split_paragraphs(text: str) -> List[Tuple[str, int, int]]:
    """
    Split text by double newlines or Markdown headers/lists.

    Returns:
        List of (paragraph_text, start_pos, end_pos)
    """
    paragraphs = []
    pattern = re.compile(r"\n{2,}|(?=^#{1,6}\s)|(?=^- |\* )", re.MULTILINE)
    last = 0

    for m in pattern.finditer(text):
        end = m.start()
        seg = text[last:end]
        paragraphs.append((seg, last, end))
        last = m.end()

    # Handle trailing text
    if last < len(text):
        paragraphs.append((text[last:], last, len(text)))

    # Filter empty segments
    return [(seg, s, e) for seg, s, e in paragraphs if seg.strip()]


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

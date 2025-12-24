"""
分层切块（Hierarchical Chunking）：
- 段落级：基于空行/Markdown 结构粗分，目标 ~200-400 tokens（以字符近似）
- 句子级：在段落内按句号/问号/感叹号分句
返回可用于高亮的起止位置与父子关联。
"""
from __future__ import annotations

import re
import uuid
from typing import Dict, List


def _char_len_to_tokens(text: str) -> int:
    # 粗略估计 token 数：字符数 / 4
    return max(1, len(text) // 4)


def hierarchical_chunk_markdown(markdown: str) -> Dict[str, List[Dict]]:
    text = markdown or ""
    paragraphs = _split_paragraphs(text)
    paragraph_chunks: List[Dict] = []
    sentence_chunks: List[Dict] = []

    for p_idx, (p_text, start, end) in enumerate(paragraphs):
        if not p_text.strip():
            continue
        para_id = str(uuid.uuid4())
        paragraph_chunks.append(
            {
                "id": para_id,
                "level": "paragraph",
                "index": p_idx,
                "text": p_text,
                "start": start,
                "end": end,
                "tokens_est": _char_len_to_tokens(p_text),
            }
        )
        # 句子级
        sentences = _split_sentences(p_text, base_offset=start)
        for s_idx, (s_text, s_start, s_end) in enumerate(sentences):
            if not s_text.strip():
                continue
            sentence_chunks.append(
                {
                    "id": str(uuid.uuid4()),
                    "level": "sentence",
                    "index": s_idx,
                    "parent_id": para_id,
                    "text": s_text,
                    "start": s_start,
                    "end": s_end,
                    "tokens_est": _char_len_to_tokens(s_text),
                }
            )

    return {
        "paragraphs": paragraph_chunks,
        "sentences": sentence_chunks,
    }


def _split_paragraphs(text: str):
    """
    用双换行或 Markdown 标题/列表分段。
    返回 (paragraph_text, start, end) 列表。
    """
    paragraphs = []
    pattern = re.compile(r"\n{2,}|(?=^#{1,6}\s)|(?=^- |\* )", re.MULTILINE)
    last = 0
    for m in pattern.finditer(text):
        end = m.start()
        seg = text[last:end]
        paragraphs.append((seg, last, end))
        last = m.end()
    # 末尾
    if last < len(text):
        paragraphs.append((text[last:], last, len(text)))
    # 过滤空白
    cleaned = []
    for seg, s, e in paragraphs:
        if seg.strip():
            cleaned.append((seg, s, e))
    return cleaned


def _split_sentences(paragraph: str, base_offset: int):
    """
    简单中英混合分句。
    返回 (sentence_text, start, end) 相对于全文的偏移。
    """
    sentences = []
    pattern = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", re.S)
    for m in pattern.finditer(paragraph):
        sent = m.group()
        start = base_offset + m.start()
        end = base_offset + m.end()
        sentences.append((sent, start, end))
    if not sentences and paragraph.strip():
        sentences.append((paragraph, base_offset, base_offset + len(paragraph)))
    return sentences


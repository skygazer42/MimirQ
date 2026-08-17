"""
Markdown Q/A aware chunking strategy.

Targets Q/A formatted content that uses Markdown bullets/headings, e.g.:
- **Q:** What is RAG?
- **A:** Retrieval-Augmented Generation.
- ### Q: ...

This complements `qa_pairs` which focuses on plain "Q: ... / A: ..." lines.
The chunker keeps each Q/A pair together and uses pair-level overlap.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker

_Q_PREFIX = r"(?:Q(?:uestion)?|问(?:题)?|问题)"
_A_PREFIX = r"(?:A(?:nswer)?|答(?:案)?|答案)"

_QA_TAG_LINE_RE = re.compile(
    rf"(?m)^\s*(?:[-*+]\s*|\d+\.\s*)?(?:#{1, 6}\s*)?(?:\*\*|__)?"
    rf"(?P<prefix>{_Q_PREFIX}|{_A_PREFIX})(?:\*\*|__)?(?:\s*\d{{0,3}})?\s*[:：]\s*(?P<rest>.*)$",
    flags=re.IGNORECASE,
)

_Q_STRIP_RE = re.compile(
    rf"(?i)^\s*(?:[-*+]\s*|\d+\.\s*)?(?:#{1, 6}\s*)?(?:\*\*|__)?{_Q_PREFIX}(?:\*\*|__)?(?:\s*\d{{0,3}})?\s*[:：]\s*"
)


@dataclass(frozen=True)
class _TagSeg:
    start: int
    end: int
    kind: str  # "Q" | "A"


@dataclass(frozen=True)
class _QAPair:
    start: int
    end: int
    has_answer: bool
    question_preview: str | None


def _iter_tag_segments(text: str) -> list[_TagSeg]:
    matches = list(_QA_TAG_LINE_RE.finditer(text or ""))
    if len(matches) < 2:
        return []

    segs: list[_TagSeg] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        prefix = (m.group("prefix") or "").strip()
        if not prefix:
            continue
        lower = prefix.lower()
        kind = "Q" if lower.startswith("q") or prefix.startswith("问") else "A"
        segs.append(_TagSeg(start=start, end=end, kind=kind))
    return segs


def _build_pairs(text: str, segs: list[_TagSeg]) -> list[_QAPair]:
    if not segs:
        return []

    q_indices = [i for i, s in enumerate(segs) if s.kind == "Q"]
    if not q_indices:
        return []

    pairs: list[_QAPair] = []
    for pos, q_idx in enumerate(q_indices):
        pair_start = segs[q_idx].start
        next_q_start = segs[q_indices[pos + 1]].start if pos + 1 < len(q_indices) else len(text)

        has_answer = False
        for s in segs[q_idx + 1 : (q_indices[pos + 1] if pos + 1 < len(q_indices) else len(segs))]:
            if s.kind == "A":
                has_answer = True
                break

        question_text = (text[pair_start:next_q_start] or "").strip()
        first_line = question_text.splitlines()[0] if question_text else ""
        preview = _Q_STRIP_RE.sub("", first_line).strip() if first_line else None
        if preview and len(preview) > 120:
            preview = preview[:117].rstrip() + "..."

        pairs.append(
            _QAPair(
                start=pair_start,
                end=next_q_start,
                has_answer=bool(has_answer),
                question_preview=preview,
            )
        )
    return pairs


def looks_like_qa_markdown(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    segs = _iter_tag_segments(text)
    pairs = _build_pairs(text, segs)
    if len(pairs) < 2:
        return False
    answered = sum(1 for p in pairs if p.has_answer)
    return answered >= 1


def _fallback_documents(
    *,
    splitter: RecursiveCharacterTextSplitter,
    text: str,
    base_meta: dict[str, Any],
) -> list[Document]:
    out: list[Document] = []
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    for sd in split_docs:
        local_start = sd.metadata.pop("start_index", None) or 0
        abs_start = int(local_start)
        abs_end = abs_start + len(sd.page_content)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(sd.metadata or {})
        meta["chunk_strategy"] = "qa_markdown"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta["qa_markdown_fallback"] = True
        out.append(Document(page_content=sd.page_content, metadata=meta))
    return out


def _window_end_index(*, pairs: list[_QAPair], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(pairs):
        candidate_end = pairs[end_idx].end
        candidate_len = candidate_end - pairs[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else start_idx + 1


def _next_window_start(*, pairs: list[_QAPair], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and (end_idx - start_idx) > 1:
        desired = end_idx - 1
        while desired > start_idx:
            overlap_len = pairs[end_idx - 1].end - pairs[desired - 1].start
            if overlap_len <= chunk_overlap:
                desired -= 1
                continue
            break
        next_start = desired if desired > start_idx else (end_idx - 1)
    return next_start if next_start > start_idx else end_idx


def _qa_chunk_document(
    *,
    text: str,
    base_meta: dict[str, Any],
    pairs: list[_QAPair],
    start_idx: int,
    end_idx: int,
) -> Document:
    chunk_start = pairs[start_idx].start
    chunk_end = pairs[end_idx - 1].end
    window = pairs[start_idx:end_idx]
    previews = [p.question_preview for p in window if p.question_preview][:3]
    answered = sum(1 for p in window if p.has_answer)
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "qa_markdown"
    meta["start_char"] = chunk_start
    meta["end_char"] = chunk_end
    meta["qa_pair_count"] = int(end_idx - start_idx)
    meta["qa_answered_count"] = int(answered)
    if previews:
        meta["qa_question_previews"] = previews
    return Document(page_content=text[chunk_start:chunk_end], metadata=meta)


class QAMarkdownChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            segs = _iter_tag_segments(text)
            pairs = _build_pairs(text, segs)
            if not pairs:
                out.extend(_fallback_documents(splitter=self._fallback_splitter, text=text, base_meta=base_meta))
                continue

            start_idx = 0
            while start_idx < len(pairs):
                end_idx = _window_end_index(pairs=pairs, start_idx=start_idx, chunk_size=self.chunk_size)
                out.append(
                    _qa_chunk_document(
                        text=text, base_meta=base_meta, pairs=pairs, start_idx=start_idx, end_idx=end_idx
                    )
                )
                start_idx = _next_window_start(
                    pairs=pairs,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    chunk_overlap=self.chunk_overlap,
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

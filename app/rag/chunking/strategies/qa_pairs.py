"""
Q/A-pair aware chunking strategy.

Optimized for FAQ / interview scripts / exam solutions that follow Q/A labels:
- Q: ... / A: ...
- Question 1: ... / Answer 1: ...
- 问题：... / 答案：...
- 问：... / 答：...

The chunker tries to keep each Q/A pair together and uses pair-level overlap
when possible.
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
    rf"(?m)^\s*(?P<prefix>{_Q_PREFIX}|{_A_PREFIX})(?:\s*\d{{0,3}})?\s*[:：]\s*(?P<rest>.*)$",
    flags=re.IGNORECASE,
)

_Q_STRIP_RE = re.compile(rf"^\s*{_Q_PREFIX}(?:\s*\d{{0,3}})?\s*[:：]\s*", flags=re.IGNORECASE)


@dataclass(frozen=True)
class _TagSeg:
    start: int
    end: int
    kind: str  # "Q" | "A"


@dataclass(frozen=True)
class _QAPair:
    start: int
    end: int
    question_end: int
    answer_start: int | None
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
        kind = "Q" if prefix.lower().startswith("q") or prefix.startswith("问") else "A"
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

        first_a_start: int | None = None
        for s in segs[q_idx + 1 : (q_indices[pos + 1] if pos + 1 < len(q_indices) else len(segs))]:
            if s.kind == "A":
                first_a_start = s.start
                break

        question_end = first_a_start if first_a_start is not None else next_q_start
        question_text = (text[pair_start:question_end] or "").strip()
        first_line = question_text.splitlines()[0] if question_text else ""
        preview = _Q_STRIP_RE.sub("", first_line).strip() if first_line else None
        if preview and len(preview) > 120:
            preview = preview[:117].rstrip() + "..."

        pairs.append(
            _QAPair(
                start=pair_start,
                end=next_q_start,
                question_end=question_end,
                answer_start=first_a_start,
                has_answer=first_a_start is not None,
                question_preview=preview,
            )
        )
    return pairs


def looks_like_qa_pairs(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    segs = _iter_tag_segments(text)
    pairs = _build_pairs(text, segs)
    if len(pairs) < 2:
        return False
    answered = sum(1 for p in pairs if p.has_answer)
    return answered >= 1


class QAPairsChunker(BaseChunker):
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
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "qa_pairs"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["qa_pairs_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(pairs):
                end_idx = start_idx
                while end_idx < len(pairs):
                    candidate_end = pairs[end_idx].end
                    candidate_len = candidate_end - pairs[start_idx].start
                    if end_idx == start_idx or candidate_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break

                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = pairs[start_idx].start
                chunk_end = pairs[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                window = pairs[start_idx:end_idx]
                previews = [p.question_preview for p in window if p.question_preview][:3]
                answered = sum(1 for p in window if p.has_answer)

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "qa_pairs"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["qa_pair_count"] = int(end_idx - start_idx)
                meta["qa_answered_count"] = int(answered)
                if previews:
                    meta["qa_question_previews"] = previews
                out.append(Document(page_content=content, metadata=meta))

                # Pair-level overlap (avoid breaking pairs).
                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = pairs[end_idx - 1].end - pairs[desired - 1].start
                        if overlap_len <= self.chunk_overlap:
                            desired -= 1
                            continue
                        break
                    next_start = desired if desired > start_idx else (end_idx - 1)

                if next_start <= start_idx:
                    next_start = end_idx
                start_idx = next_start

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

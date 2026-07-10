"""
Transcript / dialogue-aware chunking strategy.

Optimized for meeting minutes, interviews, and scripts that use speaker prefixes:
- 张三：...
- Host: ...
- Q: ... / A: ...

The chunker tries to keep complete speaker turns together and uses turn-level
overlap (instead of raw character overlap) when possible.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Turn:
    start: int
    end: int
    speaker: str


_SPEAKER_LINE_RE = re.compile(
    r"(?m)^\s*(?P<speaker>"
    r"(?:"
    r"Q|A|问|答|主持人|记者|嘉宾|旁白|主持|采访者|受访者"
    r"|Speaker\s*\d{1,3}"
    r"|[A-Za-z][\w .-]{0,30}"
    r"|[\u4e00-\u9fff]{1,20}"
    r")"
    r")\s*[:：]\s*(?P<rest>.*)$"
)


def _iter_turns(text: str) -> list[_Turn]:
    matches = list(_SPEAKER_LINE_RE.finditer(text or ""))
    if len(matches) < 2:
        return []
    turns: list[_Turn] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        speaker = (m.group("speaker") or "").strip()
        turns.append(_Turn(start=start, end=end, speaker=speaker))
    return turns


def looks_like_transcript(text: str) -> bool:
    if not text or len(text) < 50:
        return False
    turns = _iter_turns(text)
    return len(turns) >= 3


class TranscriptChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ". ", "!", "?", " ", ""],
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

            turns = _iter_turns(text)
            if not turns:
                # Fallback: still return chunks with positions.
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "transcript"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["transcript_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(turns):
                end_idx = start_idx
                # Always include at least one turn.
                while end_idx < len(turns):
                    candidate_end = turns[end_idx].end
                    candidate_len = candidate_end - turns[start_idx].start
                    if end_idx == start_idx or candidate_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break

                # If a single turn exceeds chunk_size, include it alone.
                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = turns[start_idx].start
                chunk_end = turns[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                speakers = [t.speaker for t in turns[start_idx:end_idx] if t.speaker]
                unique_speakers: list[str] = []
                for s in speakers:
                    if s not in unique_speakers:
                        unique_speakers.append(s)

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "transcript"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["turn_count"] = int(end_idx - start_idx)
                if unique_speakers:
                    meta["speakers"] = unique_speakers
                out.append(Document(page_content=content, metadata=meta))

                # Compute next start index with turn-level overlap.
                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = turns[end_idx - 1].end - turns[desired - 1].start
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

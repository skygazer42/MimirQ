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

    def _append_fallback_chunks(self, *, out: list[Document], text: str, base_meta: dict[str, Any]) -> None:
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

    @staticmethod
    def _unique_speakers(turns: list[_Turn], *, start_idx: int, end_idx: int) -> list[str]:
        unique_speakers: list[str] = []
        for turn in turns[start_idx:end_idx]:
            if turn.speaker and turn.speaker not in unique_speakers:
                unique_speakers.append(turn.speaker)
        return unique_speakers

    @staticmethod
    def _append_turn_chunk(
        *,
        out: list[Document],
        text: str,
        base_meta: dict[str, Any],
        turns: list[_Turn],
        start_idx: int,
        end_idx: int,
    ) -> None:
        chunk_start = turns[start_idx].start
        chunk_end = turns[end_idx - 1].end
        meta: dict[str, Any] = dict(base_meta)
        meta["chunk_strategy"] = "transcript"
        meta["start_char"] = chunk_start
        meta["end_char"] = chunk_end
        meta["turn_count"] = int(end_idx - start_idx)
        speakers = TranscriptChunker._unique_speakers(turns, start_idx=start_idx, end_idx=end_idx)
        if speakers:
            meta["speakers"] = speakers
        out.append(Document(page_content=text[chunk_start:chunk_end], metadata=meta))

    def _next_turn_start(self, *, turns: list[_Turn], start_idx: int, end_idx: int) -> int:
        if self.chunk_overlap <= 0 or (end_idx - start_idx) <= 1:
            return end_idx
        desired = end_idx - 1
        while desired > start_idx:
            overlap_len = turns[end_idx - 1].end - turns[desired - 1].start
            if overlap_len <= self.chunk_overlap:
                desired -= 1
                continue
            break
        next_start = desired if desired > start_idx else (end_idx - 1)
        return next_start if next_start > start_idx else end_idx

    @staticmethod
    def _finalize_chunk_indexes(out: list[Document]) -> list[Document]:
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta
        return out

    def _append_turn_chunks(
        self,
        *,
        out: list[Document],
        text: str,
        base_meta: dict[str, Any],
        turns: list[_Turn],
    ) -> None:
        start_idx = 0
        while start_idx < len(turns):
            end_idx = start_idx
            while end_idx < len(turns):
                candidate_end = turns[end_idx].end
                candidate_len = candidate_end - turns[start_idx].start
                if end_idx == start_idx or candidate_len <= self.chunk_size:
                    end_idx += 1
                    continue
                break

            if end_idx == start_idx:
                end_idx = start_idx + 1

            self._append_turn_chunk(
                out=out,
                text=text,
                base_meta=base_meta,
                turns=turns,
                start_idx=start_idx,
                end_idx=end_idx,
            )
            start_idx = self._next_turn_start(turns=turns, start_idx=start_idx, end_idx=end_idx)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            turns = _iter_turns(text)
            if not turns:
                self._append_fallback_chunks(out=out, text=text, base_meta=base_meta)
                continue

            self._append_turn_chunks(out=out, text=text, base_meta=base_meta, turns=turns)

        return self._finalize_chunk_indexes(out)

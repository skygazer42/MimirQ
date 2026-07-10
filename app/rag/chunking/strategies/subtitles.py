"""
Subtitles (SRT/VTT-like) aware chunking strategy.

Targets subtitle documents with timecode cue lines, e.g.:
- 00:00:01,000 --> 00:00:04,000
- 00:00:01.000 --> 00:00:04.000

The chunker keeps whole cues together and uses cue-level overlap.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Cue:
    start: int
    end: int
    index: int
    start_ts: str
    end_ts: str


_TIMECODE_RE = re.compile(
    r"^\s*(?P<start>\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2}[,\.]\d{3})\b"
)


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, text=raw))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text))
    return out


def _iter_cues(text: str) -> list[_Cue]:
    lines = _iter_lines(text)
    if not lines:
        return []

    cue_starts: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = _TIMECODE_RE.match(line.text.strip())
        if not m:
            continue
        cue_start = line.start
        if i > 0:
            prev = lines[i - 1].text.strip()
            if prev.isdigit():
                cue_start = lines[i - 1].start
        cue_starts.append((cue_start, (m.group("start") or "").strip(), (m.group("end") or "").strip()))

    if len(cue_starts) < 2:
        return []

    cue_starts = sorted(cue_starts, key=lambda x: x[0])

    cues: list[_Cue] = []
    for idx, (start, start_ts, end_ts) in enumerate(cue_starts):
        end = cue_starts[idx + 1][0] if idx + 1 < len(cue_starts) else len(text)
        if end <= start:
            continue
        cues.append(_Cue(start=start, end=end, index=idx, start_ts=start_ts, end_ts=end_ts))
    return cues if len(cues) >= 2 else []


def looks_like_subtitles(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    cues = _iter_cues(text)
    return len(cues) >= 3


class SubtitlesChunker(BaseChunker):
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

            cues = _iter_cues(text)
            if not cues:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "subtitles"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["subtitles_fallback"] = True
                    meta.setdefault("doc_type_kwd", "subtitles")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            # Include any prefix before the first cue (e.g., WEBVTT header).
            if cues[0].start > 0 and (text[: cues[0].start] or "").strip():
                prefix = text[: cues[0].start]
                split_docs = self._fallback_splitter.create_documents(texts=[prefix], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "subtitles"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["cue_index"] = -1
                    meta["cue_start_index"] = -1
                    meta["cue_end_index"] = -1
                    meta.setdefault("doc_type_kwd", "subtitles")
                    out.append(Document(page_content=sd.page_content, metadata=meta))

            start_idx = 0
            while start_idx < len(cues):
                end_idx = start_idx
                while end_idx < len(cues):
                    candidate_end = cues[end_idx].end
                    candidate_len = candidate_end - cues[start_idx].start
                    if end_idx == start_idx or candidate_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break

                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = cues[start_idx].start
                chunk_end = cues[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "subtitles"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta.setdefault("doc_type_kwd", "subtitles")
                meta["cue_count"] = int(end_idx - start_idx)
                meta["cue_start_index"] = int(start_idx)
                meta["cue_end_index"] = int(end_idx - 1)
                meta["first_timecode"] = cues[start_idx].start_ts
                meta["last_timecode"] = cues[end_idx - 1].end_ts
                out.append(Document(page_content=content, metadata=meta))

                # Cue-level overlap.
                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = cues[end_idx - 1].end - cues[desired - 1].start
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

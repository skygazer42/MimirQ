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


def _fallback_chunks(
    *,
    text: str,
    base_meta: dict[str, Any],
    splitter: RecursiveCharacterTextSplitter,
    start_offset: int = 0,
    prefix_marker: bool = False,
) -> list[Document]:
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    out: list[Document] = []
    for split_doc in split_docs:
        local_start = split_doc.metadata.pop("start_index", None) or 0
        abs_start = start_offset + int(local_start)
        abs_end = abs_start + len(split_doc.page_content)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_doc.metadata or {})
        meta["chunk_strategy"] = "subtitles"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta.setdefault("doc_type_kwd", "subtitles")
        if prefix_marker:
            meta["cue_index"] = -1
            meta["cue_start_index"] = -1
            meta["cue_end_index"] = -1
        else:
            meta["subtitles_fallback"] = True
        out.append(Document(page_content=split_doc.page_content, metadata=meta))
    return out


def _cue_window_end(*, cues: list[_Cue], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(cues):
        candidate_end = cues[end_idx].end
        candidate_len = candidate_end - cues[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else (start_idx + 1)


def _next_cue_start(*, cues: list[_Cue], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    if chunk_overlap <= 0 or (end_idx - start_idx) <= 1:
        return end_idx

    desired = end_idx - 1
    while desired > start_idx:
        overlap_len = cues[end_idx - 1].end - cues[desired - 1].start
        if overlap_len <= chunk_overlap:
            desired -= 1
            continue
        break
    next_start = desired if desired > start_idx else (end_idx - 1)
    return end_idx if next_start <= start_idx else next_start


def _cue_chunk(
    *,
    text: str,
    base_meta: dict[str, Any],
    cues: list[_Cue],
    start_idx: int,
    end_idx: int,
) -> Document:
    chunk_start = cues[start_idx].start
    chunk_end = cues[end_idx - 1].end
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
    return Document(page_content=text[chunk_start:chunk_end], metadata=meta)


def _split_subtitle_document(
    *,
    doc: Document,
    splitter: RecursiveCharacterTextSplitter,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Document]:
    text = doc.page_content or ""
    if not text.strip():
        return []

    base_meta = dict(doc.metadata or {})
    cues = _iter_cues(text)
    if not cues:
        return _fallback_chunks(text=text, base_meta=base_meta, splitter=splitter)

    out: list[Document] = []
    prefix = text[: cues[0].start]
    if cues[0].start > 0 and prefix.strip():
        out.extend(
            _fallback_chunks(
                text=prefix,
                base_meta=base_meta,
                splitter=splitter,
                start_offset=0,
                prefix_marker=True,
            )
        )

    start_idx = 0
    while start_idx < len(cues):
        end_idx = _cue_window_end(cues=cues, start_idx=start_idx, chunk_size=chunk_size)
        out.append(_cue_chunk(text=text, base_meta=base_meta, cues=cues, start_idx=start_idx, end_idx=end_idx))
        start_idx = _next_cue_start(
            cues=cues,
            start_idx=start_idx,
            end_idx=end_idx,
            chunk_overlap=chunk_overlap,
        )
    return out


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
            out.extend(
                _split_subtitle_document(
                    doc=doc,
                    splitter=self._fallback_splitter,
                    chunk_size=self.chunk_size,
                    chunk_overlap=self.chunk_overlap,
                )
            )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

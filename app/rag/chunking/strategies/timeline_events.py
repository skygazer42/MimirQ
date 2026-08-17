"""
Timeline / dated-events aware chunking strategy.

Targets documents where each event starts with a date (optionally time), e.g.:
- 2024-01-01 - Project kickoff...
- 2024/01/02 10:30: Incident resolved...

The chunker keeps whole events together and uses event-level overlap.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Event:
    start: int
    end: int
    date: str
    time: str | None
    preview: str | None


_EVENT_LINE_RE = re.compile(
    r"(?m)^\s*(?:[-*+]\s*)?(?P<date>\d{4}[-/.]\d{1,2}[-/.]\d{1,2})"
    r"(?:\s+(?P<time>\d{1,2}:\d{2}(?::\d{2})?))?"
    r"\s*(?:[-–—:：]|\s{2,})\s*(?P<rest>.*)$"
)


def _iter_events(text: str) -> list[_Event]:
    matches = list(_EVENT_LINE_RE.finditer(text or ""))
    if len(matches) < 2:
        return []

    events: list[_Event] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        date = (m.group("date") or "").strip()
        time = (m.group("time") or "").strip() or None
        rest = (m.group("rest") or "").strip()
        preview = rest.splitlines()[0].strip() if rest else None
        if preview and len(preview) > 120:
            preview = preview[:117].rstrip() + "..."
        if not date:
            continue
        events.append(_Event(start=start, end=end, date=date, time=time, preview=preview))
    return events if len(events) >= 2 else []


def looks_like_timeline_events(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    events = _iter_events(text)
    return len(events) >= 4


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
        meta["chunk_strategy"] = "timeline_events"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta["timeline_fallback"] = True
        out.append(Document(page_content=sd.page_content, metadata=meta))
    return out


def _window_end_index(*, events: list[_Event], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(events):
        candidate_end = events[end_idx].end
        candidate_len = candidate_end - events[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else start_idx + 1


def _next_window_start(*, events: list[_Event], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and (end_idx - start_idx) > 1:
        desired = end_idx - 1
        while desired > start_idx:
            overlap_len = events[end_idx - 1].end - events[desired - 1].start
            if overlap_len <= chunk_overlap:
                desired -= 1
                continue
            break
        next_start = desired if desired > start_idx else (end_idx - 1)
    return next_start if next_start > start_idx else end_idx


def _event_chunk_document(
    *,
    text: str,
    base_meta: dict[str, Any],
    events: list[_Event],
    start_idx: int,
    end_idx: int,
) -> Document:
    chunk_start = events[start_idx].start
    chunk_end = events[end_idx - 1].end
    previews = [event.preview for event in events[start_idx:end_idx] if event.preview][:3]
    first = events[start_idx]
    last = events[end_idx - 1]
    first_date = first.date + ((" " + first.time) if first.time else "")
    last_date = last.date + ((" " + last.time) if last.time else "")
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "timeline_events"
    meta["start_char"] = chunk_start
    meta["end_char"] = chunk_end
    meta["event_count"] = int(end_idx - start_idx)
    meta["first_event"] = first_date
    meta["last_event"] = last_date
    if previews:
        meta["event_previews"] = previews
    return Document(page_content=text[chunk_start:chunk_end], metadata=meta)


class TimelineEventsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", ". ", "!", "?", " ", ""],
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

            events = _iter_events(text)
            if not events:
                out.extend(_fallback_documents(splitter=self._fallback_splitter, text=text, base_meta=base_meta))
                continue

            start_idx = 0
            while start_idx < len(events):
                end_idx = _window_end_index(events=events, start_idx=start_idx, chunk_size=self.chunk_size)
                out.append(_event_chunk_document(text=text, base_meta=base_meta, events=events, start_idx=start_idx, end_idx=end_idx))
                start_idx = _next_window_start(
                    events=events,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    chunk_overlap=self.chunk_overlap,
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

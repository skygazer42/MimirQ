"""
Log-events aware chunking strategy.

Targets application / system logs with timestamped entry lines, e.g.:
- 2024-01-01 10:00:00,123 INFO module: message
- [2024-01-01T10:00:00Z] ERROR message
- Jan  1 10:00:00 host process[123]: message  (syslog)

The chunker keeps whole log entries together and uses entry-level overlap.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Entry:
    start: int
    end: int
    ts: str | None
    level: str | None


_LEVELS = r"TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL"

_LOG_START_RE = re.compile(
    rf"(?mi)^\s*(?:\[\s*)?(?P<ts>"
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"(?:[ T]\d{1,2}:\d{2}:\d{2}(?:[.,]\d{3,6})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?"
    r")\s*(?:\]\s*)?\s*(?P<level>"
    rf"(?:{_LEVELS})"
    r")\b"
)

_SYSLOG_START_RE = re.compile(
    r"(?m)^\s*(?P<ts>"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
    r"\d{1,2}\s+\d{2}:\d{2}:\d{2}"
    r")\s+\S+\s+[^:\n]{1,80}:\s*"
)


def _iter_entries(text: str) -> list[_Entry]:
    if not text:
        return []

    matches = []
    for pat in (_LOG_START_RE, _SYSLOG_START_RE):
        matches.extend(list(pat.finditer(text)))

    matches = sorted(matches, key=lambda m: m.start())
    if len(matches) < 2:
        return []

    dedup = []
    last_start = -1
    for m in matches:
        if m.start() == last_start:
            continue
        dedup.append(m)
        last_start = m.start()
    matches = dedup

    entries: list[_Entry] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        ts = (m.group("ts") or "").strip() if "ts" in m.groupdict() else None
        level = (m.group("level") or "").strip().upper() if "level" in m.groupdict() else None
        if not ts:
            ts = None
        if not level:
            level = None
        entries.append(_Entry(start=start, end=end, ts=ts, level=level))

    return entries if len(entries) >= 2 else []


def looks_like_log_events(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    entries = _iter_entries(text)
    if len(entries) < 4:
        return False
    levelled = sum(1 for e in entries if e.level)
    # Prefer the "timestamp + level" pattern; syslog-only still counts but needs more evidence.
    return levelled >= 3 or len(entries) >= 6


def _entry_window_end(entries: list[_Entry], *, start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(entries):
        candidate_length = entries[end_idx].end - entries[start_idx].start
        if end_idx != start_idx and candidate_length > chunk_size:
            break
        end_idx += 1
    return max(start_idx + 1, end_idx)


def _unique_entry_levels(entries: list[_Entry], *, start_idx: int, end_idx: int) -> list[str]:
    levels: list[str] = []
    for entry in entries[start_idx:end_idx]:
        if entry.level and entry.level not in levels:
            levels.append(entry.level)
    return levels[:10]


def _next_entry_start(
    entries: list[_Entry],
    *,
    start_idx: int,
    end_idx: int,
    chunk_overlap: int,
) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and end_idx - start_idx > 1:
        desired = end_idx - 1
        while desired > start_idx:
            overlap_length = entries[end_idx - 1].end - entries[desired - 1].start
            if overlap_length > chunk_overlap:
                break
            desired -= 1
        next_start = desired if desired > start_idx else end_idx - 1
    return end_idx if next_start <= start_idx else next_start


class LogEventsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _append_fallback_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        base_meta: dict[str, Any],
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(
            texts=[text],
            metadatas=[base_meta],
        )
        for split_doc in split_docs:
            start = int(split_doc.metadata.pop("start_index", None) or 0)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(split_doc.metadata or {})
            meta.update(
                {
                    "chunk_strategy": "log_events",
                    "start_char": start,
                    "end_char": start + len(split_doc.page_content),
                    "log_fallback": True,
                }
            )
            meta.setdefault("doc_type_kwd", "log")
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    @staticmethod
    def _entry_metadata(
        *,
        base_meta: dict[str, Any],
        entries: list[_Entry],
        start_idx: int,
        end_idx: int,
    ) -> dict[str, Any]:
        first_entry = entries[start_idx]
        last_entry = entries[end_idx - 1]
        meta: dict[str, Any] = dict(base_meta)
        meta.update(
            {
                "chunk_strategy": "log_events",
                "start_char": first_entry.start,
                "end_char": last_entry.end,
                "log_entry_count": int(end_idx - start_idx),
            }
        )
        meta.setdefault("doc_type_kwd", "log")
        levels = _unique_entry_levels(entries, start_idx=start_idx, end_idx=end_idx)
        if levels:
            meta["log_levels"] = levels
        if first_entry.ts:
            meta["first_timestamp"] = first_entry.ts
        if last_entry.ts:
            meta["last_timestamp"] = last_entry.ts
        return meta

    def _append_entry_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        entries: list[_Entry],
        base_meta: dict[str, Any],
    ) -> None:
        start_idx = 0
        while start_idx < len(entries):
            end_idx = _entry_window_end(
                entries,
                start_idx=start_idx,
                chunk_size=self.chunk_size,
            )
            meta = self._entry_metadata(
                base_meta=base_meta,
                entries=entries,
                start_idx=start_idx,
                end_idx=end_idx,
            )
            out.append(
                Document(
                    page_content=text[meta["start_char"] : meta["end_char"]],
                    metadata=meta,
                )
            )
            start_idx = _next_entry_start(
                entries,
                start_idx=start_idx,
                end_idx=end_idx,
                chunk_overlap=self.chunk_overlap,
            )

    def _split_document(self, doc: Document, out: list[Document]) -> None:
        text = doc.page_content or ""
        if not text.strip():
            return
        base_meta = dict(doc.metadata or {})
        entries = _iter_entries(text)
        if entries:
            self._append_entry_chunks(
                out,
                text=text,
                entries=entries,
                base_meta=base_meta,
            )
            return
        self._append_fallback_chunks(out, text=text, base_meta=base_meta)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            self._split_document(doc, out)
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta
        return out

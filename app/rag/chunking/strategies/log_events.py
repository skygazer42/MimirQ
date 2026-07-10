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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            entries = _iter_entries(text)
            if not entries:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "log_events"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["log_fallback"] = True
                    meta.setdefault("doc_type_kwd", "log")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(entries):
                end_idx = start_idx
                while end_idx < len(entries):
                    candidate_end = entries[end_idx].end
                    candidate_len = candidate_end - entries[start_idx].start
                    if end_idx == start_idx or candidate_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break

                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = entries[start_idx].start
                chunk_end = entries[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                levels = [e.level for e in entries[start_idx:end_idx] if e.level]
                uniq_levels: list[str] = []
                for lv in levels:
                    if lv and lv not in uniq_levels:
                        uniq_levels.append(lv)
                uniq_levels = uniq_levels[:10]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "log_events"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["log_entry_count"] = int(end_idx - start_idx)
                meta.setdefault("doc_type_kwd", "log")
                if uniq_levels:
                    meta["log_levels"] = uniq_levels
                first_ts = entries[start_idx].ts
                last_ts = entries[end_idx - 1].ts
                if first_ts:
                    meta["first_timestamp"] = first_ts
                if last_ts:
                    meta["last_timestamp"] = last_ts
                out.append(Document(page_content=content, metadata=meta))

                # Entry-level overlap.
                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = entries[end_idx - 1].end - entries[desired - 1].start
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


"""
Chat history aware chunking strategy.

Optimized for exported/pasted chat logs with timestamps, e.g.:
- [2024-01-01 10:00] Alice: ...
- 2024/01/01, 10:00 - Bob: ...
- 10:00 Alice: ...

The chunker keeps whole messages together and uses message-level overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Msg:
    start: int
    end: int
    speaker: str
    ts: str | None


_TS_BRACKET_RE = re.compile(
    r"(?m)^\s*\[(?P<ts>\d{4}[-/]\d{1,2}[-/]\d{1,2}[^\]]{0,20})\]\s*(?P<speaker>[^:\n]{1,40})\s*[:：]\s*(?P<rest>.*)$"
)
_TS_DATE_COMMA_RE = re.compile(
    r"(?m)^\s*(?P<ts>\d{4}[-/]\d{1,2}[-/]\d{1,2},\s*[0-9:]{4,8})\s*[-–—]?\s*(?P<speaker>[^:\n]{1,40})\s*[:：]\s*(?P<rest>.*)$"
)
_TS_DATE_SPACE_RE = re.compile(
    r"(?m)^\s*(?P<ts>\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+[0-9:]{4,8})\s*[-–—]?\s*(?P<speaker>[^:\n]{1,40})\s*[:：]\s*(?P<rest>.*)$"
)
_TS_TIME_RE = re.compile(
    r"(?m)^\s*(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<speaker>[^:\n]{1,40})\s*[:：]\s*(?P<rest>.*)$"
)


def _iter_messages(text: str) -> list[_Msg]:
    if not text:
        return []

    matches = []
    for pat in (_TS_BRACKET_RE, _TS_DATE_COMMA_RE, _TS_DATE_SPACE_RE, _TS_TIME_RE):
        matches.extend(list(pat.finditer(text)))

    matches = sorted(matches, key=lambda m: m.start())
    if len(matches) < 2:
        return []

    # De-dup by start position (keep first match).
    dedup = []
    last_start = -1
    for m in matches:
        if m.start() == last_start:
            continue
        dedup.append(m)
        last_start = m.start()
    matches = dedup

    msgs: list[_Msg] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        speaker = (m.group("speaker") or "").strip()
        if not speaker:
            continue
        ts = None
        if "ts" in m.groupdict() and m.group("ts"):
            ts = (m.group("ts") or "").strip()
        elif "date" in m.groupdict() and m.group("date"):
            ts = (m.group("date") or "").strip()
            if "time" in m.groupdict() and m.group("time"):
                ts = ts + " " + (m.group("time") or "").strip()
        elif "time" in m.groupdict() and m.group("time"):
            ts = (m.group("time") or "").strip()
        msgs.append(_Msg(start=start, end=end, speaker=speaker, ts=ts))
    return msgs if len(msgs) >= 2 else []


def looks_like_chat_history(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    msgs = _iter_messages(text)
    if len(msgs) < 3:
        return False
    speakers = {m.speaker for m in msgs if m.speaker}
    return len(speakers) >= 2


class ChatHistoryChunker(BaseChunker):
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

            msgs = _iter_messages(text)
            if not msgs:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "chat_history"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["chat_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(msgs):
                end_idx = start_idx
                while end_idx < len(msgs):
                    candidate_end = msgs[end_idx].end
                    candidate_len = candidate_end - msgs[start_idx].start
                    if end_idx == start_idx or candidate_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break

                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = msgs[start_idx].start
                chunk_end = msgs[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                speakers = [m.speaker for m in msgs[start_idx:end_idx] if m.speaker]
                uniq: list[str] = []
                for s in speakers:
                    if s not in uniq:
                        uniq.append(s)
                uniq = uniq[:10]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "chat_history"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["message_count"] = int(end_idx - start_idx)
                if uniq:
                    meta["participants"] = uniq
                meta["has_timestamps"] = True
                first_ts = msgs[start_idx].ts
                last_ts = msgs[end_idx - 1].ts
                if first_ts:
                    meta["first_timestamp"] = first_ts
                if last_ts:
                    meta["last_timestamp"] = last_ts
                out.append(Document(page_content=content, metadata=meta))

                # Message-level overlap.
                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = msgs[end_idx - 1].end - msgs[desired - 1].start
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

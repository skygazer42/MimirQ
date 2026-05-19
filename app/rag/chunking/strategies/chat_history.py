"""
Chat history aware chunking strategy.

Optimized for exported/pasted chat logs with timestamps, e.g.:
- [2024-01-01 10:00] Alice: ...
- 2024/01/01, 10:00 - Bob: ...
- 10:00 Alice: ...

The chunker keeps whole messages together and uses message-level overlap.
"""

from __future__ import annotations

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


_DASH_CHARS = {"-", "–", "—"}


def _parse_date_prefix(s: str, start: int) -> int | None:
    """
    Parse YYYY[-/]M[-/]D starting at start, return next index if valid.
    """
    n = len(s)
    i = start
    # Minimal length: 'YYYY-M-D' (8 chars).
    if i + 8 > n:
        return None
    if not (s[i : i + 4].isdigit()):
        return None
    i += 4
    if i >= n or s[i] not in ("-", "/"):
        return None
    i += 1
    m0 = i
    while i < n and i - m0 < 2 and s[i].isdigit():
        i += 1
    if i == m0:
        return None
    if i >= n or s[i] not in ("-", "/"):
        return None
    i += 1
    d0 = i
    while i < n and i - d0 < 2 and s[i].isdigit():
        i += 1
    if i == d0:
        return None
    return i


def _parse_time_prefix(s: str, start: int) -> int | None:
    """
    Parse H:MM / HH:MM / H:MM:SS / HH:MM:SS.
    """
    n = len(s)
    i = start
    h0 = i
    while i < n and i - h0 < 2 and s[i].isdigit():
        i += 1
    if i == h0 or i >= n or s[i] != ":":
        return None
    i += 1
    if i + 2 > n or not s[i : i + 2].isdigit():
        return None
    i += 2
    if i + 3 <= n and s[i] == ":" and s[i + 1 : i + 3].isdigit():
        i += 3
    return i


def _parse_speaker_and_rest(s: str, start: int) -> tuple[str, int] | None:
    n = len(s)
    i = start
    while i < n and s[i].isspace():
        i += 1
    speaker_start = i
    while i < n and s[i] not in (":", "：", "\n", "\r"):
        i += 1
    if i <= speaker_start or i >= n or s[i] not in (":", "："):
        return None
    speaker = s[speaker_start:i].strip()
    if not speaker or len(speaker) > 40:
        return None
    i += 1
    while i < n and s[i].isspace():
        i += 1
    return speaker, i


def _parse_message_start(line: str) -> tuple[str, str | None] | None:
    """
    Detect chat message boundaries. Implemented without regex to avoid backtracking hotspots.
    Returns (speaker, ts) where ts is a best-effort timestamp string.
    """
    raw = line or ""
    if not raw:
        return None
    s = raw
    i = 0
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i >= n:
        return None

    # [YYYY-MM-DD ...] Speaker: ...
    if s[i] == "[":
        close = s.find("]", i + 1)
        if close == -1:
            return None
        inside = s[i + 1 : close]
        if len(inside) > 40:
            return None
        date_end = _parse_date_prefix(inside, 0)
        if date_end is None:
            return None
        ts = inside.strip()
        parsed = _parse_speaker_and_rest(s, close + 1)
        if not parsed:
            return None
        speaker, _ = parsed
        return speaker, ts

    # YYYY/MM/DD, 10:00 - Speaker: ...
    date_end = _parse_date_prefix(s, i)
    if date_end is not None:
        j = date_end
        if j < n and s[j] == ",":
            j += 1
            while j < n and s[j].isspace():
                j += 1
            time_end = _parse_time_prefix(s, j)
            if time_end is not None:
                ts = s[i:time_end].strip()
                k = time_end
                while k < n and s[k].isspace():
                    k += 1
                if k < n and s[k] in _DASH_CHARS:
                    k += 1
                parsed = _parse_speaker_and_rest(s, k)
                if parsed:
                    speaker, _ = parsed
                    return speaker, ts

        # YYYY-MM-DD 10:00 - Speaker: ...
        j = date_end
        if j < n and s[j].isspace():
            while j < n and s[j].isspace():
                j += 1
            time_end = _parse_time_prefix(s, j)
            if time_end is not None:
                ts = s[i:time_end].strip()
                k = time_end
                while k < n and s[k].isspace():
                    k += 1
                if k < n and s[k] in _DASH_CHARS:
                    k += 1
                parsed = _parse_speaker_and_rest(s, k)
                if parsed:
                    speaker, _ = parsed
                    return speaker, ts

    # 10:00 Speaker: ...
    time_end = _parse_time_prefix(s, i)
    if time_end is not None:
        ts = s[i:time_end].strip()
        parsed = _parse_speaker_and_rest(s, time_end)
        if parsed:
            speaker, _ = parsed
            return speaker, ts

    return None


def _iter_messages(text: str) -> list[_Msg]:
    if not text:
        return []

    leads: list[tuple[int, str, str | None]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        start = offset
        offset += len(raw_line)
        parsed = _parse_message_start(raw_line)
        if not parsed:
            continue
        speaker, ts = parsed
        leads.append((start, speaker, ts))

    if len(leads) < 2:
        return []

    msgs: list[_Msg] = []
    for idx, (start, speaker, ts) in enumerate(leads):
        end = leads[idx + 1][0] if idx + 1 < len(leads) else len(text)
        if not speaker:
            continue
        msgs.append(_Msg(start=int(start), end=int(end), speaker=str(speaker), ts=(str(ts) if ts else None)))
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

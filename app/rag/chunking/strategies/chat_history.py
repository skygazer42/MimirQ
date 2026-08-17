"""
Chat history aware chunking strategy.

Optimized for exported/pasted chat logs with timestamps, e.g.:
- [2024-01-01 10:00] Alice: ...
- 2024/01/01, 10:00 - Bob: ...
- 10:00 Alice: ...

The chunker keeps whole messages together and uses message-level overlap.
"""

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


def _parse_bracketed_message_start(s: str, start: int) -> tuple[str, str | None] | None:
    close = s.find("]", start + 1)
    if close == -1:
        return None
    inside = s[start + 1 : close]
    if len(inside) > 40:
        return None
    if _parse_date_prefix(inside, 0) is None:
        return None
    parsed = _parse_speaker_and_rest(s, close + 1)
    if not parsed:
        return None
    speaker, _ = parsed
    return speaker, inside.strip()


def _parse_dated_message_start(s: str, start: int) -> tuple[str, str | None] | None:
    date_end = _parse_date_prefix(s, start)
    if date_end is None:
        return None
    for separator in (",", None):
        parsed = _parse_dated_speaker_and_timestamp(s, start=start, date_end=date_end, separator=separator)
        if parsed is not None:
            return parsed
    return None


def _parse_dated_speaker_and_timestamp(
    s: str,
    *,
    start: int,
    date_end: int,
    separator: str | None,
) -> tuple[str, str | None] | None:
    n = len(s)
    index = date_end
    if separator is not None:
        if index >= n or s[index] != separator:
            return None
        index += 1
        while index < n and s[index].isspace():
            index += 1
    else:
        if index >= n or not s[index].isspace():
            return None
        while index < n and s[index].isspace():
            index += 1

    time_end = _parse_time_prefix(s, index)
    if time_end is None:
        return None
    speaker_start = _skip_dash_separator(s, time_end)
    parsed = _parse_speaker_and_rest(s, speaker_start)
    if not parsed:
        return None
    speaker, _ = parsed
    return speaker, s[start:time_end].strip()


def _skip_dash_separator(s: str, start: int) -> int:
    n = len(s)
    index = start
    while index < n and s[index].isspace():
        index += 1
    if index < n and s[index] in _DASH_CHARS:
        index += 1
    return index


def _parse_time_only_message_start(s: str, start: int) -> tuple[str, str | None] | None:
    time_end = _parse_time_prefix(s, start)
    if time_end is None:
        return None
    parsed = _parse_speaker_and_rest(s, time_end)
    if not parsed:
        return None
    speaker, _ = parsed
    return speaker, s[start:time_end].strip()


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

    if s[i] == "[":
        return _parse_bracketed_message_start(s, i)

    dated = _parse_dated_message_start(s, i)
    if dated is not None:
        return dated
    time_only = _parse_time_only_message_start(s, i)
    if time_only is not None:
        return time_only
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


def _split_fallback_docs(
    splitter: RecursiveCharacterTextSplitter, text: str, base_meta: dict[str, Any]
) -> list[Document]:
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    chunks: list[Document] = []
    for split_doc in split_docs:
        split_meta = dict(split_doc.metadata or {})
        abs_start = int(split_meta.pop("start_index", None) or 0)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_meta)
        meta["chunk_strategy"] = "chat_history"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_start + len(split_doc.page_content)
        meta["chat_fallback"] = True
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


def _message_window_end(msgs: list[_Msg], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(msgs):
        candidate_len = msgs[end_idx].end - msgs[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else start_idx + 1


def _window_participants(msgs: list[_Msg], start_idx: int, end_idx: int) -> list[str]:
    uniq: list[str] = []
    for msg in msgs[start_idx:end_idx]:
        if msg.speaker and msg.speaker not in uniq:
            uniq.append(msg.speaker)
    return uniq[:10]


def _build_message_chunk(
    msgs: list[_Msg], start_idx: int, end_idx: int, base_meta: dict[str, Any], text: str
) -> Document:
    chunk_start = msgs[start_idx].start
    chunk_end = msgs[end_idx - 1].end
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "chat_history"
    meta["start_char"] = chunk_start
    meta["end_char"] = chunk_end
    meta["message_count"] = int(end_idx - start_idx)
    participants = _window_participants(msgs, start_idx, end_idx)
    if participants:
        meta["participants"] = participants
    meta["has_timestamps"] = True
    first_ts = msgs[start_idx].ts
    last_ts = msgs[end_idx - 1].ts
    if first_ts:
        meta["first_timestamp"] = first_ts
    if last_ts:
        meta["last_timestamp"] = last_ts
    return Document(page_content=text[chunk_start:chunk_end], metadata=meta)


def _next_message_start(msgs: list[_Msg], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap <= 0 or (end_idx - start_idx) <= 1:
        return next_start

    desired = end_idx - 1
    while desired > start_idx:
        overlap_len = msgs[end_idx - 1].end - msgs[desired - 1].start
        if overlap_len <= chunk_overlap:
            desired -= 1
            continue
        break
    next_start = desired if desired > start_idx else (end_idx - 1)
    return next_start if next_start > start_idx else end_idx


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
            out.extend(self._split_document(doc))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content or ""
        if not text.strip():
            return []

        base_meta = dict(doc.metadata or {})
        msgs = _iter_messages(text)
        if not msgs:
            return _split_fallback_docs(self._fallback_splitter, text, base_meta)

        chunks: list[Document] = []
        start_idx = 0
        while start_idx < len(msgs):
            end_idx = _message_window_end(msgs, start_idx, self.chunk_size)
            chunks.append(_build_message_chunk(msgs, start_idx, end_idx, base_meta, text))
            start_idx = _next_message_start(msgs, start_idx, end_idx, self.chunk_overlap)
        return chunks

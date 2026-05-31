"""
Email-thread aware chunking strategy.

Optimized for pasted email threads / forwarded emails where messages contain
headers and separators, e.g.:
- From: ... / To: ... / Subject: ... / Date: ...
- -----Original Message-----
- On ... wrote:

The chunker tries to keep whole messages together and uses message-level
overlap when possible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker

_HEADER_KEYWORDS = [
    "from",
    "to",
    "cc",
    "bcc",
    "subject",
    "date",
    "sent",
    "reply-to",
    # Chinese (common in Outlook exports)
    "发件人",
    "收件人",
    "抄送",
    "密送",
    "主题",
    "日期",
    "发送时间",
    "时间",
]

_HEADER_KEYS = {str(k or "").strip().casefold() for k in _HEADER_KEYWORDS if str(k or "").strip()}
_HEADER_START_KEYS = {"from", "发件人"}


def _parse_header_line(line: str) -> tuple[str, str] | None:
    """
    Parse a header line like:
      From: someone@example.com
      发件人：xxx

    Returns (key_cf, value) or None.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s:
        return None

    colon_ascii = s.find(":")
    colon_full = s.find("：")
    if colon_ascii == -1:
        colon = colon_full
    elif colon_full == -1:
        colon = colon_ascii
    else:
        colon = min(colon_ascii, colon_full)

    if colon <= 0:
        return None

    key = s[:colon].strip().casefold()
    if key not in _HEADER_KEYS:
        return None
    val = s[colon + 1 :].strip()
    if not val:
        return None
    return key, val


def _looks_like_thread_separator_line(line: str) -> bool:
    s = str(line or "").strip()
    if not s:
        return False
    # Require some dashes to avoid false positives.
    i = 0
    while i < len(s) and s[i] == "-":
        i += 1
    if i < 2:
        return False
    low = s.casefold()
    return ("original message" in low) or ("forwarded message" in low) or ("原始邮件" in s) or ("转发邮件" in s)


def _looks_like_on_wrote_line(line: str) -> bool:
    s = str(line or "").strip()
    if not s:
        return False

    low = s.casefold()
    if low.startswith("on ") and low.rstrip().endswith("wrote:") and (" wrote:" in low):
        return True

    # Chinese common quote header: 在 ... 写道:
    if s.startswith("在") and ("写道" in s):
        tail = s.rstrip()
        return tail.endswith(("写道", "写道:", "写道："))

    return False


def _has_quote_lines(text: str) -> bool:
    for ln in str(text or "").splitlines():
        if ln.lstrip().startswith(">"):
            return True
    return False


@dataclass(frozen=True)
class _Message:
    start: int
    end: int
    headers: dict[str, str]


def _count_header_lines(lines: list[str]) -> int:
    return sum(1 for ln in lines if _parse_header_line(ln) is not None)


def _has_plausible_header_block(text: str, start: int) -> bool:
    snippet = text[start : min(len(text), start + 2000)]
    lines = snippet.splitlines()
    if not lines:
        return False
    head = lines[:12]
    header_pairs = [p for ln in head if (p := _parse_header_line(ln)) is not None]
    if len(header_pairs) < 3:
        return False
    keys = {k for k, _v in header_pairs}
    # Require at least From + (Subject/To) for stability.
    has_from = any(k in {"from", "发件人"} for k in keys)
    has_subject_or_to = any(k in {"subject", "主题", "to", "收件人"} for k in keys)
    return bool(has_from and has_subject_or_to)


def _extract_headers(message_text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    lines = message_text.splitlines()
    for ln in lines[:40]:
        if not ln.strip():
            break
        parsed = _parse_header_line(ln)
        if parsed is None:
            continue
        key, val = parsed
        if not key or not val:
            continue
        if key in headers:
            continue
        headers[key] = val
    return headers


def _iter_messages(text: str) -> list[_Message]:
    if not text:
        return []

    candidates: list[int] = [0]
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        plain = raw_line.rstrip("\r\n")

        if _looks_like_thread_separator_line(plain):
            candidates.append(line_start)
            continue

        parsed = _parse_header_line(plain)
        if parsed is not None and parsed[0] in _HEADER_START_KEYS:
            if _has_plausible_header_block(text, line_start):
                candidates.append(line_start)
                continue

        if _looks_like_on_wrote_line(plain):
            candidates.append(line_start)

    starts = sorted({i for i in candidates if 0 <= i < len(text)})
    if len(starts) < 2:
        return []

    msgs: list[_Message] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        if end <= start:
            continue
        seg = text[start:end]
        if not seg.strip():
            continue
        headers = _extract_headers(seg)
        msgs.append(_Message(start=start, end=end, headers=headers))

    # Filter out accidental micro-segments (e.g., inline "On ... wrote:" lines).
    filtered: list[_Message] = []
    for m in msgs:
        if (m.end - m.start) < 40:
            continue
        filtered.append(m)

    return filtered if len(filtered) >= 2 else []


def looks_like_email_thread(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    msgs = _iter_messages(text)
    if msgs:
        return True
    # Best-effort: many threads include separators even without full headers.
    head = (text or "")[:50000]
    has_sep = any(_looks_like_thread_separator_line(ln) for ln in head.splitlines())
    has_headers = _count_header_lines(head.splitlines()[:120]) >= 3
    return bool(has_sep and has_headers)


class EmailThreadChunker(BaseChunker):
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
                    meta["chunk_strategy"] = "email_thread"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["email_thread_fallback"] = True
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

                subjects: list[str] = []
                froms: list[str] = []
                for m in msgs[start_idx:end_idx]:
                    h = m.headers
                    subj = h.get("subject") or h.get("主题")
                    frm = h.get("from") or h.get("发件人")
                    if subj and subj not in subjects:
                        subjects.append(subj)
                    if frm and frm not in froms:
                        froms.append(frm)
                subjects = subjects[:3]
                froms = froms[:3]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "email_thread"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["email_message_count"] = int(end_idx - start_idx)
                if subjects:
                    meta["email_subjects"] = subjects
                if froms:
                    meta["email_froms"] = froms
                meta["email_has_quotes"] = _has_quote_lines(content)
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

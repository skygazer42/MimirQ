"""
Key-value config aware chunking strategy.

Targets .env / INI-like configuration text with many `KEY=VALUE` lines, e.g.:
- DATABASE_URL=...
- export API_KEY=...
- [section]\nkey=value

The chunker keeps whole key-value entries together and can split by INI
sections when present. Offsets are preserved.
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
class _Section:
    start: int
    end: int
    name: str | None


@dataclass(frozen=True)
class _KV:
    start: int
    end: int
    key: str


_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]{1,80})\]\s*$")


def _strip_export_prefix(value: str) -> str:
    if not value.casefold().startswith("export"):
        return value
    remainder = value[len("export") :]
    return remainder.lstrip() if remainder[:1].isspace() else value


def _is_valid_kv_key(key: str) -> bool:
    if not key or len(key) > 64:
        return False
    first = key[0]
    if not (first == "_" or (first.isascii() and first.isalpha())):
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in "_.-") for ch in key[1:])


def _parse_kv_line(line: str) -> str | None:
    """
    Parse a key-value assignment line like:
      KEY=VALUE
      export KEY=VALUE

    Returns the key or None.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    raw = str(line or "").rstrip("\r\n")
    if not raw:
        return None
    s = raw.lstrip()
    if not s:
        return None

    s = _strip_export_prefix(s)

    eq = s.find("=")
    if eq <= 0:
        return None
    key = s[:eq].strip()
    return key if _is_valid_kv_key(key) else None


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


def _build_sections(text: str) -> list[_Section]:
    lines = _iter_lines(text)
    headers: list[tuple[int, str]] = []
    for ln in lines:
        m = _SECTION_RE.match(ln.text.strip())
        if not m:
            continue
        name = (m.group("name") or "").strip() or "section"
        headers.append((ln.start, name))

    if not headers:
        return [_Section(start=0, end=len(text), name=None)]

    headers = sorted(headers, key=lambda x: x[0])
    sections: list[_Section] = []
    if headers[0][0] > 0:
        sections.append(_Section(start=0, end=headers[0][0], name=None))
    for idx, (start, name) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        sections.append(_Section(start=start, end=end, name=name))
    return sections


def _iter_kv(text: str, *, start: int, end: int) -> list[_KV]:
    lines = _iter_lines(text[start:end])
    kvs: list[_KV] = []
    for ln in lines:
        key = _parse_kv_line(ln.text)
        if not key:
            continue
        kvs.append(_KV(start=start + ln.start, end=start + ln.end, key=key))
    return kvs


def looks_like_kv_config(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    raw_lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if len(raw_lines) < 6:
        return False
    kv_lines = 0
    for ln in raw_lines[:2000]:
        if _parse_kv_line(ln):
            kv_lines += 1
    if kv_lines < 5:
        return False
    ratio = kv_lines / max(1, len(raw_lines))
    return ratio >= 0.2


def _short_tail_end(text: str, *, current_end: int, section_end: int) -> int:
    tail = text[current_end:section_end]
    return section_end if tail.strip() and len(tail) <= 400 else current_end


def _kv_window_end(
    text: str,
    *,
    section: _Section,
    kvs: list[_KV],
    start_idx: int,
    first: bool,
    chunk_size: int,
) -> int:
    end_idx = start_idx
    while end_idx < len(kvs):
        candidate_start = section.start if first else kvs[start_idx].start
        candidate_end = kvs[end_idx].end
        if end_idx == len(kvs) - 1:
            candidate_end = _short_tail_end(
                text,
                current_end=candidate_end,
                section_end=section.end,
            )
        if end_idx != start_idx and candidate_end - candidate_start > chunk_size:
            break
        end_idx += 1
    return max(start_idx + 1, end_idx)


def _unique_kv_keys(kvs: list[_KV], *, start_idx: int, end_idx: int) -> list[str]:
    unique: list[str] = []
    for item in kvs[start_idx:end_idx]:
        if item.key and item.key not in unique:
            unique.append(item.key)
    return unique[:25]


def _next_kv_start(
    kvs: list[_KV],
    *,
    start_idx: int,
    end_idx: int,
    chunk_overlap: int,
) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and end_idx - start_idx > 1:
        desired = end_idx - 1
        while desired > start_idx:
            overlap_len = kvs[end_idx - 1].end - kvs[desired - 1].start
            if overlap_len > chunk_overlap:
                break
            desired -= 1
        next_start = desired if desired > start_idx else end_idx - 1
    return end_idx if next_start <= start_idx else next_start


class KVConfigChunker(BaseChunker):
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
        start: int,
        end: int,
        base_meta: dict[str, Any],
        section_name: str | None = None,
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(
            texts=[text[start:end]],
            metadatas=[base_meta],
        )
        for split_doc in split_docs:
            local_start = split_doc.metadata.pop("start_index", None) or 0
            absolute_start = start + int(local_start)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(split_doc.metadata or {})
            meta.update(
                {
                    "chunk_strategy": "kv_config",
                    "start_char": absolute_start,
                    "end_char": absolute_start + len(split_doc.page_content),
                    "kv_fallback": True,
                }
            )
            meta.setdefault("doc_type_kwd", "config")
            if section_name:
                meta["config_section"] = section_name
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    def _append_kv_section_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        section: _Section,
        kvs: list[_KV],
        base_meta: dict[str, Any],
    ) -> None:
        start_idx = 0
        first = True
        while start_idx < len(kvs):
            end_idx = _kv_window_end(
                text,
                section=section,
                kvs=kvs,
                start_idx=start_idx,
                first=first,
                chunk_size=self.chunk_size,
            )
            chunk_start = section.start if first else kvs[start_idx].start
            chunk_end = kvs[end_idx - 1].end
            if end_idx == len(kvs):
                chunk_end = _short_tail_end(
                    text,
                    current_end=chunk_end,
                    section_end=section.end,
                )

            meta: dict[str, Any] = dict(base_meta)
            meta.update(
                {
                    "chunk_strategy": "kv_config",
                    "start_char": chunk_start,
                    "end_char": chunk_end,
                    "kv_count": int(end_idx - start_idx),
                }
            )
            meta.setdefault("doc_type_kwd", "config")
            if section.name:
                meta["config_section"] = section.name
            unique_keys = _unique_kv_keys(kvs, start_idx=start_idx, end_idx=end_idx)
            if unique_keys:
                meta["kv_keys"] = unique_keys
            out.append(Document(page_content=text[chunk_start:chunk_end], metadata=meta))

            start_idx = _next_kv_start(
                kvs,
                start_idx=start_idx,
                end_idx=end_idx,
                chunk_overlap=self.chunk_overlap,
            )
            first = False

    def _split_document(self, doc: Document, out: list[Document]) -> None:
        text = doc.page_content or ""
        base_meta = dict(doc.metadata or {})
        if not text.strip():
            return

        any_kv = False
        for section in _build_sections(text):
            if not text[section.start : section.end].strip():
                continue
            kvs = _iter_kv(text, start=section.start, end=section.end)
            if kvs:
                any_kv = True
                self._append_kv_section_chunks(
                    out,
                    text=text,
                    section=section,
                    kvs=kvs,
                    base_meta=base_meta,
                )
                continue
            self._append_fallback_chunks(
                out,
                text=text,
                start=section.start,
                end=section.end,
                base_meta=base_meta,
                section_name=section.name,
            )

        if not any_kv:
            self._append_fallback_chunks(
                out,
                text=text,
                start=0,
                end=len(text),
                base_meta=base_meta,
            )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            self._split_document(doc, out)

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta
        return out

"""
TOML config aware chunking strategy.

Targets TOML-like configuration text with tables and key/value assignments:
- [tool.poetry]
- key = "value"
- [[array.of.tables]]

The chunker splits by table blocks first, then groups key/value entries within
each block while preserving character offsets.
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
    plain: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    name: str | None


@dataclass(frozen=True)
class _Entry:
    start: int
    end: int
    key: str


_TABLE_RE = re.compile(r"^\s*(?P<brackets>\[\[?)(?P<name>[^\]]{1,120})\]\]?\s*$")


def _parse_toml_key_line(line: str) -> str | None:
    """
    Parse a TOML key/value line like:
      key = "value"

    Returns the key or None.

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s or s.startswith("#"):
        return None
    if "=" not in s:
        return None
    eq = s.find("=")
    if eq <= 0:
        return None
    key = s[:eq].strip()
    val = s[eq + 1 :].strip()
    if "#" in val:
        # Best-effort: strip inline comments when not inside quotes.
        if " #" in val or val.startswith("#"):
            val = val.split("#", 1)[0].strip()
    if not key or not val:
        return None
    if len(key) > 80:
        return None
    if not all(ch.isascii() and (ch.isalnum() or ch in "_.-") for ch in key):
        return None
    return key


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, text=raw, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text, plain=text))
    return out


def _build_sections(text: str) -> list[_Section]:
    lines = _iter_lines(text)
    headers: list[tuple[int, str]] = []
    for ln in lines:
        m = _TABLE_RE.match(ln.plain.strip())
        if not m:
            continue
        name = (m.group("name") or "").strip()
        if not name:
            continue
        # Distinguish [[array]] from [table]
        brackets = m.group("brackets") or "["
        prefix = "array" if brackets.startswith("[[") else "table"
        headers.append((ln.start, f"{prefix}:{name}"))

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


def _iter_entries(text: str, *, start: int, end: int) -> list[_Entry]:
    rel_lines = _iter_lines(text[start:end])
    entries: list[_Entry] = []
    start_idxs: list[int] = []
    keys: list[str] = []

    for i, ln in enumerate(rel_lines):
        plain = ln.plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        if _TABLE_RE.match(plain.strip()):
            continue
        key = _parse_toml_key_line(plain)
        if not key:
            continue
        start_idxs.append(i)
        keys.append(key)

    for idx, i in enumerate(start_idxs):
        ln = rel_lines[i]
        entry_start = start + ln.start
        entry_end = start + (rel_lines[start_idxs[idx + 1]].start if idx + 1 < len(start_idxs) else (end - start))
        entries.append(_Entry(start=entry_start, end=entry_end, key=keys[idx]))

    return entries


def looks_like_toml_config(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    lowered = text.lower()
    if "[tool." in lowered or "[project]" in lowered:
        return True
    head = (text or "")[:80000]
    has_table = False
    has_key = False
    for ln in head.splitlines()[:2000]:
        plain = ln.strip()
        if not plain or plain.startswith("#"):
            continue
        if _TABLE_RE.match(plain):
            has_table = True
        elif _parse_toml_key_line(plain):
            has_key = True
        if has_table and has_key:
            return True
    return False


def _entry_window_end(entries: list[_Entry], *, start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(entries):
        length = entries[end_idx].end - entries[start_idx].start
        if end_idx != start_idx and length > chunk_size:
            break
        end_idx += 1
    return max(start_idx + 1, end_idx)


def _unique_entry_keys(entries: list[_Entry], *, start_idx: int, end_idx: int) -> list[str]:
    keys: list[str] = []
    for entry in entries[start_idx:end_idx]:
        if entry.key and entry.key not in keys:
            keys.append(entry.key)
    return keys[:25]


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


class TOMLConfigChunker(BaseChunker):
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
        table: str | None = None,
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(
            texts=[text[start:end]],
            metadatas=[base_meta],
        )
        for split_doc in split_docs:
            local_start = int(split_doc.metadata.pop("start_index", None) or 0)
            absolute_start = start + local_start
            meta: dict[str, Any] = dict(base_meta)
            meta.update(split_doc.metadata or {})
            meta.update(
                {
                    "chunk_strategy": "toml_config",
                    "start_char": absolute_start,
                    "end_char": absolute_start + len(split_doc.page_content),
                    "toml_fallback": True,
                }
            )
            meta.setdefault("doc_type_kwd", "toml")
            if table:
                meta["toml_table"] = table
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    @staticmethod
    def _entry_metadata(
        *,
        base_meta: dict[str, Any],
        section: _Section,
        entries: list[_Entry],
        start_idx: int,
        end_idx: int,
    ) -> dict[str, Any]:
        first = entries[start_idx]
        last = entries[end_idx - 1]
        meta: dict[str, Any] = dict(base_meta)
        meta.update(
            {
                "chunk_strategy": "toml_config",
                "start_char": first.start,
                "end_char": last.end,
                "toml_entry_count": int(end_idx - start_idx),
            }
        )
        meta.setdefault("doc_type_kwd", "toml")
        if section.name:
            meta["toml_table"] = section.name
        keys = _unique_entry_keys(entries, start_idx=start_idx, end_idx=end_idx)
        if keys:
            meta["toml_keys"] = keys
        return meta

    def _append_entry_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        section: _Section,
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
                section=section,
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
        any_entries = False
        for section in _build_sections(text):
            if not text[section.start : section.end].strip():
                continue
            entries = _iter_entries(text, start=section.start, end=section.end)
            if entries:
                any_entries = True
                self._append_entry_chunks(
                    out,
                    text=text,
                    section=section,
                    entries=entries,
                    base_meta=base_meta,
                )
                continue
            self._append_fallback_chunks(
                out,
                text=text,
                start=section.start,
                end=section.end,
                base_meta=base_meta,
                table=section.name,
            )
        if not any_entries:
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

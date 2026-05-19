"""
TOML config aware chunking strategy.

Targets TOML-like configuration text with tables and key/value assignments:
- [tool.poetry]
- key = "value"
- [[array.of.tables]]

The chunker splits by table blocks first, then groups key/value entries within
each block while preserving character offsets.
"""

from __future__ import annotations

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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            sections = _build_sections(text)
            any_entries = False

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                entries = _iter_entries(text, start=section.start, end=section.end)
                if not entries:
                    split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                    for sd in split_docs:
                        local_start = sd.metadata.pop("start_index", None) or 0
                        abs_start = section.start + int(local_start)
                        abs_end = abs_start + len(sd.page_content)

                        meta: dict[str, Any] = dict(base_meta)
                        meta.update(sd.metadata or {})
                        meta["chunk_strategy"] = "toml_config"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["toml_fallback"] = True
                        meta.setdefault("doc_type_kwd", "toml")
                        if section.name:
                            meta["toml_table"] = section.name
                        out.append(Document(page_content=sd.page_content, metadata=meta))
                    continue

                any_entries = True

                start_idx = 0
                while start_idx < len(entries):
                    end_idx = start_idx
                    while end_idx < len(entries):
                        cand_start = entries[start_idx].start
                        cand_end = entries[end_idx].end
                        cand_len = cand_end - cand_start
                        if end_idx == start_idx or cand_len <= self.chunk_size:
                            end_idx += 1
                            continue
                        break
                    if end_idx == start_idx:
                        end_idx = start_idx + 1

                    chunk_start = entries[start_idx].start
                    chunk_end = entries[end_idx - 1].end
                    content = text[chunk_start:chunk_end]

                    keys = [e.key for e in entries[start_idx:end_idx] if e.key]
                    uniq: list[str] = []
                    for k in keys:
                        if k not in uniq:
                            uniq.append(k)
                    uniq = uniq[:25]

                    meta: dict[str, Any] = dict(base_meta)
                    meta["chunk_strategy"] = "toml_config"
                    meta["start_char"] = chunk_start
                    meta["end_char"] = chunk_end
                    meta.setdefault("doc_type_kwd", "toml")
                    meta["toml_entry_count"] = int(end_idx - start_idx)
                    if section.name:
                        meta["toml_table"] = section.name
                    if uniq:
                        meta["toml_keys"] = uniq
                    out.append(Document(page_content=content, metadata=meta))

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

            if not any_entries:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "toml_config"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["toml_fallback"] = True
                    meta.setdefault("doc_type_kwd", "toml")
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

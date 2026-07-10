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

    low = s.casefold()
    if low.startswith("export"):
        rest = s[len("export") :]
        if rest[:1].isspace():
            s = rest.lstrip()

    eq = s.find("=")
    if eq <= 0:
        return None
    key = s[:eq].strip()
    if not key or len(key) > 64:
        return None
    first = key[0]
    if not (first == "_" or (first.isascii() and first.isalpha())):
        return None
    for ch in key[1:]:
        if not ch.isascii():
            return None
        if ch.isalnum():
            continue
        if ch in "_.-":
            continue
        return None
    return key


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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            sections = _build_sections(text)
            any_kv = False

            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                kvs = _iter_kv(text, start=section.start, end=section.end)
                if not kvs:
                    split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                    for sd in split_docs:
                        local_start = sd.metadata.pop("start_index", None) or 0
                        abs_start = section.start + int(local_start)
                        abs_end = abs_start + len(sd.page_content)
                        meta: dict[str, Any] = dict(base_meta)
                        meta.update(sd.metadata or {})
                        meta["chunk_strategy"] = "kv_config"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["kv_fallback"] = True
                        meta.setdefault("doc_type_kwd", "config")
                        if section.name:
                            meta["config_section"] = section.name
                        out.append(Document(page_content=sd.page_content, metadata=meta))
                    continue

                any_kv = True
                start_idx = 0
                first = True
                while start_idx < len(kvs):
                    end_idx = start_idx
                    while end_idx < len(kvs):
                        cand_start = section.start if first else kvs[start_idx].start
                        cand_end = kvs[end_idx].end
                        # Include a small tail on the last chunk (comments after last key).
                        if end_idx == len(kvs) - 1:
                            tail = text[kvs[end_idx].end : section.end]
                            if tail.strip() and len(tail) <= 400:
                                cand_end = section.end
                        cand_len = cand_end - cand_start
                        if end_idx == start_idx or cand_len <= self.chunk_size:
                            end_idx += 1
                            continue
                        break

                    if end_idx == start_idx:
                        end_idx = start_idx + 1

                    chunk_start = section.start if first else kvs[start_idx].start
                    chunk_end = kvs[end_idx - 1].end
                    if end_idx == len(kvs):
                        tail = text[chunk_end : section.end]
                        if tail.strip() and len(tail) <= 400:
                            chunk_end = section.end
                    content = text[chunk_start:chunk_end]

                    keys = [kv.key for kv in kvs[start_idx:end_idx] if kv.key]
                    uniq: list[str] = []
                    for k in keys:
                        if k not in uniq:
                            uniq.append(k)
                    uniq = uniq[:25]

                    meta: dict[str, Any] = dict(base_meta)
                    meta["chunk_strategy"] = "kv_config"
                    meta["start_char"] = chunk_start
                    meta["end_char"] = chunk_end
                    meta.setdefault("doc_type_kwd", "config")
                    meta["kv_count"] = int(end_idx - start_idx)
                    if section.name:
                        meta["config_section"] = section.name
                    if uniq:
                        meta["kv_keys"] = uniq
                    out.append(Document(page_content=content, metadata=meta))

                    next_start = end_idx
                    if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                        desired = end_idx - 1
                        while desired > start_idx:
                            overlap_len = kvs[end_idx - 1].end - kvs[desired - 1].start
                            if overlap_len <= self.chunk_overlap:
                                desired -= 1
                                continue
                            break
                        next_start = desired if desired > start_idx else (end_idx - 1)

                    if next_start <= start_idx:
                        next_start = end_idx
                    start_idx = next_start
                    first = False

            if not any_kv:
                # If nothing looked like kv config, still emit something.
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "kv_config"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["kv_fallback"] = True
                    meta.setdefault("doc_type_kwd", "config")
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

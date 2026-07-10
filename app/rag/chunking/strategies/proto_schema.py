"""
Protocol Buffers (.proto) schema aware chunking strategy.

Targets .proto files and splits by top-level blocks such as:
- message Foo { ... }
- enum Bar { ... }
- service Baz { ... }

Offsets are preserved.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    name: str
    index: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    block: _Block | None


_BLOCK_START_RE = re.compile(r"(?m)^\s*(?P<kind>message|enum|service)\s+(?P<name>[A-Za-z_]\w*)\s*\{")
_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+(?P<name>[A-Za-z0-9_.]+)\s*;")


def _find_matching_brace(text: str, start: int) -> int | None:
    brace_pos = text.find("{", start)
    if brace_pos < 0:
        return None
    depth = 0
    for i in range(brace_pos, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                if end < len(text) and text[end : end + 1] == "\n":
                    end += 1
                return end
    return None


def _iter_blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    for m in _BLOCK_START_RE.finditer(text or ""):
        end = _find_matching_brace(text, m.start())
        if end is None:
            continue
        kind = (m.group("kind") or "").strip().lower()
        name = (m.group("name") or "").strip()
        if not kind or not name:
            continue
        blocks.append(_Block(start=m.start(), end=end, kind=kind, name=name, index=len(blocks)))
    return blocks


def _build_sections(text: str, blocks: list[_Block]) -> list[_Section]:
    if not blocks:
        return [_Section(start=0, end=len(text), block=None)]
    sections: list[_Section] = []
    first = blocks[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, block=None))
    for idx, b in enumerate(blocks):
        start = b.start
        end = blocks[idx + 1].start if idx + 1 < len(blocks) else len(text)
        end = max(end, b.end)
        sections.append(_Section(start=start, end=end, block=b))
    return sections


def _extract_package(text: str) -> str | None:
    m = _PACKAGE_RE.search((text or "")[:8000])
    if not m:
        return None
    return (m.group("name") or "").strip()[:200] or None


def looks_like_proto_schema(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    head = text[:10000].lower()
    if "syntax" in head and "proto" in head and _BLOCK_START_RE.search(text):
        return True
    blocks = _iter_blocks(text)
    return len(blocks) >= 2


class ProtoSchemaChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "}", ";", " ", ""],
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

            pkg = _extract_package(text)
            blocks = _iter_blocks(text)
            sections = _build_sections(text, blocks)

            current: _Block | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue
                if section.block is not None:
                    current = section.block

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "proto_schema"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "proto")
                    if pkg:
                        meta["proto_package"] = pkg
                    if current is not None:
                        meta["proto_kind"] = current.kind
                        meta["proto_name"] = current.name

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

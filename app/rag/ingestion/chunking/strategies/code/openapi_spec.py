"""
OpenAPI/Swagger spec aware chunking strategy (YAML-first).

Targets OpenAPI YAML with a `paths:` section and splits the spec into per-path
blocks to keep endpoint documentation together while preserving offsets.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import SourceLine as _Line
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span
from app.rag.ingestion.chunking.utils.source_lines import iter_source_lines as _iter_lines


@dataclass(frozen=True)
class _PathBlock:
    start: int
    end: int
    path: str
    index: int
    methods: list[str]


_OPENAPI_RE = re.compile(r"(?m)^\s*openapi\s*:\s*(?P<val>[^\s#]+)")
_SWAGGER_RE = re.compile(r"(?m)^\s*swagger\s*:\s*(?P<val>[^\s#]+)")
_PATHS_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)paths\s*:\s*(?:#.*)?$")
_PATH_KEY_RE = re.compile(r"^[ \t]*(?P<path>/[^:#\r\n]{0,200}):[ \t]*(?:#.*)?$")
_METHOD_RE = re.compile(r"^(get|post|put|delete|patch|options|head|trace)[ \t]*:(?=[ \t]|$)", re.IGNORECASE)


def _find_paths_anchor(text: str) -> tuple[int, int] | None:
    m = _PATHS_RE.search(text)
    if not m:
        return None
    indent = len(m.group("indent"))
    return m.start(), indent


def _extract_version(text: str) -> str | None:
    head = (text)[:8000]
    m = _OPENAPI_RE.search(head)
    if m:
        return m.group("val").strip()[:40]
    m = _SWAGGER_RE.search(head)
    if m:
        return m.group("val").strip()[:40]
    return None


def _find_line_index(lines: list[_Line], anchor_pos: int) -> int:
    for i, ln in enumerate(lines):
        if ln.start <= anchor_pos < ln.end:
            return i
    return 0


def _extract_path_entries(lines: list[_Line], anchor_idx: int, base_indent: int) -> tuple[list[tuple[int, str]], int]:
    entries: list[tuple[int, str]] = []
    path_indent = None
    for i in range(anchor_idx + 1, len(lines)):
        plain = lines[i].plain
        stripped = plain.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(plain) - len(stripped)
        if indent <= base_indent:
            return entries, lines[i].start
        if path_indent is None:
            path_indent = indent
        if indent == path_indent and (match := _PATH_KEY_RE.match(plain)) is not None:
            entries.append((i, match.group("path").rstrip()))
    return entries, lines[-1].end


def _extract_methods(block_text: str) -> list[str]:
    methods: list[str] = []
    method_indent = None
    for ln in block_text.splitlines()[1:200]:
        stripped = ln.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(ln) - len(stripped)
        if method_indent is None:
            method_indent = indent
        if indent != method_indent:
            continue
        m = _METHOD_RE.match(stripped)
        if not m:
            continue
        meth = (m.group(1)).upper()
        if meth not in methods:
            methods.append(meth)
    return methods


def _build_openapi_chunk_metadata(
    *,
    base_meta: dict[str, Any],
    split_meta: dict[str, Any],
    start_index: int | None,
    content: str,
    base_start: int,
    version: str | None,
    preamble: bool = False,
    block: _PathBlock | None = None,
    block_count: int = 0,
    fallback: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = dict(base_meta)
    meta.update(split_meta)
    meta["chunk_strategy"] = "openapi_spec"
    apply_splitter_span(meta, start_index=start_index, content=content, base_offset=base_start)
    meta.setdefault("doc_type_kwd", "openapi")
    if fallback:
        meta["openapi_fallback"] = True
    if preamble:
        meta["openapi_preamble"] = True
    if version:
        meta["openapi_version"] = version
    if block is not None:
        meta["openapi_path"] = block.path
        meta["openapi_path_index"] = block.index
        meta["openapi_path_count"] = block_count
        if block.methods:
            meta["openapi_methods"] = block.methods[:10]
    return meta


def _append_openapi_chunks(
    *,
    out: list[Document],
    splitter: RecursiveCharacterTextSplitter,
    text: str,
    base_meta: dict[str, Any],
    base_start: int,
    version: str | None,
    preamble: bool = False,
    block: _PathBlock | None = None,
    block_count: int = 0,
    fallback: bool = False,
) -> None:
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    for sd in split_docs:
        local_start = sd.metadata.pop("start_index", None)
        meta = _build_openapi_chunk_metadata(
            base_meta=base_meta,
            split_meta=sd.metadata,
            start_index=local_start,
            content=sd.page_content,
            base_start=base_start,
            version=version,
            preamble=preamble,
            block=block,
            block_count=block_count,
            fallback=fallback,
        )
        out.append(Document(page_content=sd.page_content, metadata=meta))


def _build_path_blocks(text: str) -> list[_PathBlock]:
    anchor = _find_paths_anchor(text)
    if not anchor:
        return []
    anchor_pos, base_indent = anchor

    lines = _iter_lines(text)
    anchor_idx = _find_line_index(lines, anchor_pos)
    entries, paths_end = _extract_path_entries(lines, anchor_idx, base_indent)
    if not entries:
        return []

    blocks: list[_PathBlock] = []
    for idx, (line_idx, path) in enumerate(entries):
        start = lines[line_idx].start
        end = lines[entries[idx + 1][0]].start if idx + 1 < len(entries) else paths_end
        blk_text = text[start:end]
        blocks.append(
            _PathBlock(
                start=start,
                end=end,
                path=path,
                index=idx,
                methods=_extract_methods(blk_text),
            )
        )

    return blocks


def looks_like_openapi_spec(text: str) -> bool:
    if not text or len(text) < 160:
        return False
    head = text[:12000].lower()
    if "paths:" not in head:
        return False
    if "openapi:" not in head and "swagger:" not in head:
        return False
    blocks = _build_path_blocks(text)
    return len(blocks) >= 2


class OpenAPISpecChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
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
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            version = _extract_version(text)
            blocks = _build_path_blocks(text)

            if not blocks:
                _append_openapi_chunks(
                    out=out,
                    splitter=self._fallback_splitter,
                    text=text,
                    base_meta=base_meta,
                    base_start=0,
                    version=version,
                    fallback=True,
                )
                continue

            # Keep any preamble before first path.
            first = blocks[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    _append_openapi_chunks(
                        out=out,
                        splitter=self._fallback_splitter,
                        text=pre,
                        base_meta=base_meta,
                        base_start=0,
                        version=version,
                        preamble=True,
                    )

            block_count = len(blocks)
            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                _append_openapi_chunks(
                    out=out,
                    splitter=self._fallback_splitter,
                    text=blk_text,
                    base_meta=base_meta,
                    base_start=blk.start,
                    version=version,
                    block=blk,
                    block_count=block_count,
                )
            tail_start = blocks[-1].end
            tail = text[tail_start:]
            if tail.strip():
                _append_openapi_chunks(
                    out=out,
                    splitter=self._fallback_splitter,
                    text=tail,
                    base_meta=base_meta,
                    base_start=tail_start,
                    version=version,
                    fallback=True,
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

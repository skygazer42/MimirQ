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

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    plain: str


@dataclass(frozen=True)
class _PathBlock:
    start: int
    end: int
    path: str
    index: int
    methods: list[str]


_OPENAPI_RE = re.compile(r"(?m)^\s*openapi\s*:\s*(?P<val>[^\s#]+)")
_SWAGGER_RE = re.compile(r"(?m)^\s*swagger\s*:\s*(?P<val>[^\s#]+)")
_PATHS_RE = re.compile(r"(?m)^(?P<indent>\s*)paths\s*:\s*(?:#.*)?$")
_PATH_KEY_RE = re.compile(r"^\s*/[^:]{1,200}:\s*(?:#.*)?$")
_METHOD_RE = re.compile(r"^\s*(get|post|put|delete|patch|options|head|trace)\s*:\s*(?:#.*)?$", re.IGNORECASE)


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), plain=text))
    return out


def _find_paths_anchor(text: str) -> tuple[int, int] | None:
    m = _PATHS_RE.search(text or "")
    if not m:
        return None
    indent = len(m.group("indent") or "")
    return m.start(), indent


def _extract_version(text: str) -> str | None:
    head = (text or "")[:8000]
    m = _OPENAPI_RE.search(head)
    if m:
        return (m.group("val") or "").strip()[:40] or None
    m = _SWAGGER_RE.search(head)
    if m:
        return (m.group("val") or "").strip()[:40] or None
    return None


def _build_path_blocks(text: str) -> list[_PathBlock]:
    anchor = _find_paths_anchor(text)
    if not anchor:
        return []
    anchor_pos, base_indent = anchor

    lines = _iter_lines(text)
    # Find the anchor line index.
    anchor_idx = 0
    for i, ln in enumerate(lines):
        if ln.start <= anchor_pos < ln.end:
            anchor_idx = i
            break

    # Collect path keys inside the `paths:` block.
    path_idxs: list[int] = []
    paths: list[str] = []
    for i in range(anchor_idx + 1, len(lines)):
        plain = lines[i].plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        indent = len(plain) - len(plain.lstrip(" "))
        if indent <= base_indent:
            break
        if _PATH_KEY_RE.match(plain):
            path = plain.strip()
            path = path.split("#", 1)[0].strip()
            path = path[:-1].strip()  # drop trailing ':'
            if path:
                path_idxs.append(i)
                paths.append(path)

    if not path_idxs:
        return []

    blocks: list[_PathBlock] = []
    for idx, i in enumerate(path_idxs):
        start = lines[i].start
        end = lines[path_idxs[idx + 1]].start if idx + 1 < len(path_idxs) else len(text)
        blk_text = text[start:end]
        methods: list[str] = []
        for ln in blk_text.splitlines()[:200]:
            m = _METHOD_RE.match(ln.strip())
            if not m:
                continue
            meth = (m.group(1) or "").upper()
            if meth and meth not in methods:
                methods.append(meth)
        blocks.append(
            _PathBlock(
                start=start,
                end=end,
                path=paths[idx],
                index=int(idx),
                methods=methods,
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

            version = _extract_version(text)
            blocks = _build_path_blocks(text)

            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "openapi_spec"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["openapi_fallback"] = True
                    if version:
                        meta["openapi_version"] = version
                    meta.setdefault("doc_type_kwd", "openapi")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            # Keep any preamble before first path.
            first = blocks[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    split_docs = self._fallback_splitter.create_documents(texts=[pre], metadatas=[base_meta])
                    for sd in split_docs:
                        local_start = sd.metadata.pop("start_index", None) or 0
                        abs_start = int(local_start)
                        abs_end = abs_start + len(sd.page_content)
                        meta: dict[str, Any] = dict(base_meta)
                        meta.update(sd.metadata or {})
                        meta["chunk_strategy"] = "openapi_spec"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["openapi_preamble"] = True
                        if version:
                            meta["openapi_version"] = version
                        meta.setdefault("doc_type_kwd", "openapi")
                        out.append(Document(page_content=sd.page_content, metadata=meta))

            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                split_docs = self._fallback_splitter.create_documents(texts=[blk_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = blk.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "openapi_spec"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "openapi")
                    if version:
                        meta["openapi_version"] = version
                    meta["openapi_path"] = blk.path
                    meta["openapi_path_index"] = int(blk.index)
                    meta["openapi_path_count"] = int(len(blocks))
                    if blk.methods:
                        meta["openapi_methods"] = blk.methods[:10]

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

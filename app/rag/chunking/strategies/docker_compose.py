"""
Docker Compose YAML aware chunking strategy.

Targets docker-compose YAML files with a `services:` section and splits by
service blocks, then applies a fallback splitter inside each block while
preserving character offsets.
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
class _ServiceBlock:
    start: int
    end: int
    name: str
    index: int


_SERVICES_RE = re.compile(r"(?m)^(?P<indent>\s*)services\s*:\s*(?:#.*)?$")
_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9][A-Za-z0-9_.-]{0,200})\s*:\s*(?:#.*)?$")
_IMAGE_HINT_RE = re.compile(r"(?m)^\s*(image|build|container_name|ports|depends_on)\s*:\s*")
_VERSION_RE = re.compile(r"(?m)^\s*version\s*:\s*(?P<val>[^\s#]+)")


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


def _find_services_anchor(text: str) -> tuple[int, int] | None:
    m = _SERVICES_RE.search(text or "")
    if not m:
        return None
    return m.start(), len(m.group("indent") or "")


def _extract_version(text: str) -> str | None:
    head = (text or "")[:8000]
    m = _VERSION_RE.search(head)
    if not m:
        return None
    return (m.group("val") or "").strip()[:40] or None


def _build_service_blocks(text: str) -> list[_ServiceBlock]:
    anchor = _find_services_anchor(text)
    if not anchor:
        return []
    anchor_pos, base_indent = anchor

    lines = _iter_lines(text)
    anchor_idx = 0
    for i, ln in enumerate(lines):
        if ln.start <= anchor_pos < ln.end:
            anchor_idx = i
            break

    candidates, services_end = _collect_service_candidates(lines, anchor_idx=anchor_idx, base_indent=base_indent, text_length=len(text))
    if not candidates:
        return []

    service_keys = _service_keys_from_candidates(candidates)
    if not service_keys:
        return []

    blocks: list[_ServiceBlock] = []
    for idx, (i, key) in enumerate(service_keys):
        start = lines[i].start
        end = lines[service_keys[idx + 1][0]].start if idx + 1 < len(service_keys) else services_end
        end = max(start, min(end, len(text)))
        blocks.append(_ServiceBlock(start=start, end=end, name=key, index=int(idx)))

    return blocks


def _collect_service_candidates(
    lines: list[_Line],
    *,
    anchor_idx: int,
    base_indent: int,
    text_length: int,
) -> tuple[list[tuple[int, int, str]], int]:
    candidates: list[tuple[int, int, str]] = []
    services_end = text_length
    for i in range(anchor_idx + 1, len(lines)):
        candidate = _service_candidate_for_line(lines[i], base_indent=base_indent)
        if candidate == "stop":
            services_end = lines[i].start
            break
        if candidate is not None:
            candidates.append((i, *candidate))
    return candidates, services_end


def _service_candidate_for_line(line: _Line, *, base_indent: int) -> tuple[int, str] | str | None:
    plain = line.plain
    if not plain.strip() or plain.lstrip().startswith("#"):
        return None
    indent = len(plain) - len(plain.lstrip(" "))
    if indent <= base_indent:
        return "stop"
    match = _KEY_RE.match(plain)
    if not match:
        return None
    key = (match.group("key") or "").strip()
    return (indent, key) if key else None


def _service_keys_from_candidates(candidates: list[tuple[int, int, str]]) -> list[tuple[int, str]]:
    service_indent = min(indent for _, indent, _ in candidates)
    return [(line_index, key) for line_index, indent, key in candidates if indent == service_indent]


def looks_like_docker_compose(text: str) -> bool:
    if not text or len(text) < 60:
        return False
    head = text[:20000].lower()
    if "services:" not in head:
        return False
    if not _IMAGE_HINT_RE.search(head):
        return False
    blocks = _build_service_blocks(text)
    return len(blocks) >= 1


def _compose_base_meta(base_meta: dict[str, Any], *, start_char: int, end_char: int, version: str | None) -> dict[str, Any]:
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "docker_compose"
    meta["start_char"] = start_char
    meta["end_char"] = end_char
    if version:
        meta["docker_compose_version"] = version
    meta.setdefault("doc_type_kwd", "docker-compose")
    return meta


def _split_fallback_chunk_docs(
    splitter: RecursiveCharacterTextSplitter,
    text: str,
    base_meta: dict[str, Any],
    *,
    version: str | None,
    fallback_key: str,
    start_offset: int = 0,
) -> list[Document]:
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    chunks: list[Document] = []
    for split_doc in split_docs:
        split_meta = dict(split_doc.metadata or {})
        local_start = int(split_meta.pop("start_index", None) or 0)
        abs_start = start_offset + local_start
        meta = _compose_base_meta(
            base_meta,
            start_char=abs_start,
            end_char=abs_start + len(split_doc.page_content),
            version=version,
        )
        meta.update(split_meta)
        meta[fallback_key] = True
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


def _split_service_chunk_docs(
    splitter: RecursiveCharacterTextSplitter,
    text: str,
    base_meta: dict[str, Any],
    *,
    block: _ServiceBlock,
    version: str | None,
    service_count: int,
) -> list[Document]:
    block_text = text[block.start : block.end]
    if not block_text.strip():
        return []

    split_docs = splitter.create_documents(texts=[block_text], metadatas=[base_meta])
    chunks: list[Document] = []
    for split_doc in split_docs:
        split_meta = dict(split_doc.metadata or {})
        local_start = int(split_meta.pop("start_index", None) or 0)
        abs_start = block.start + local_start
        meta = _compose_base_meta(
            base_meta,
            start_char=abs_start,
            end_char=abs_start + len(split_doc.page_content),
            version=version,
        )
        meta.update(split_meta)
        meta["compose_service"] = block.name
        meta["compose_service_index"] = int(block.index)
        meta["compose_service_count"] = int(service_count)
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


class DockerComposeChunker(BaseChunker):
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
        version = _extract_version(text)
        blocks = _build_service_blocks(text)
        if not blocks:
            return _split_fallback_chunk_docs(
                self._fallback_splitter,
                text,
                base_meta,
                version=version,
                fallback_key="docker_compose_fallback",
            )

        chunks: list[Document] = []
        first = blocks[0]
        if first.start > 0:
            preamble = text[: first.start]
            if preamble.strip():
                chunks.extend(
                    _split_fallback_chunk_docs(
                        self._fallback_splitter,
                        preamble,
                        base_meta,
                        version=version,
                        fallback_key="docker_compose_preamble",
                    )
                )

        for block in blocks:
            chunks.extend(
                _split_service_chunk_docs(
                    self._fallback_splitter,
                    text,
                    base_meta,
                    block=block,
                    version=version,
                    service_count=len(blocks),
                )
            )
        return chunks

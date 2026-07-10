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

    candidates: list[tuple[int, int, str]] = []
    services_end = len(text)

    for i in range(anchor_idx + 1, len(lines)):
        plain = lines[i].plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        indent = len(plain) - len(plain.lstrip(" "))
        if indent <= base_indent:
            services_end = lines[i].start
            break
        m = _KEY_RE.match(plain)
        if not m:
            continue
        key = (m.group("key") or "").strip()
        if key:
            candidates.append((i, indent, key))

    if not candidates:
        return []

    service_indent = min(ind for _, ind, _ in candidates)
    service_keys: list[tuple[int, str]] = [(i, key) for i, ind, key in candidates if ind == service_indent]
    if not service_keys:
        return []

    blocks: list[_ServiceBlock] = []
    for idx, (i, key) in enumerate(service_keys):
        start = lines[i].start
        end = lines[service_keys[idx + 1][0]].start if idx + 1 < len(service_keys) else services_end
        end = max(start, min(end, len(text)))
        blocks.append(_ServiceBlock(start=start, end=end, name=key, index=int(idx)))

    return blocks


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
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            version = _extract_version(text)
            blocks = _build_service_blocks(text)

            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "docker_compose"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["docker_compose_fallback"] = True
                    if version:
                        meta["docker_compose_version"] = version
                    meta.setdefault("doc_type_kwd", "docker-compose")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

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
                        meta["chunk_strategy"] = "docker_compose"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["docker_compose_preamble"] = True
                        if version:
                            meta["docker_compose_version"] = version
                        meta.setdefault("doc_type_kwd", "docker-compose")
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
                    meta["chunk_strategy"] = "docker_compose"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "docker-compose")
                    if version:
                        meta["docker_compose_version"] = version
                    meta["compose_service"] = blk.name
                    meta["compose_service_index"] = int(blk.index)
                    meta["compose_service_count"] = int(len(blocks))

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

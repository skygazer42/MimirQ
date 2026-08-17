"""
GitLab CI YAML aware chunking strategy.

Targets .gitlab-ci.yml-like YAML with top-level job keys and configuration
sections (stages/variables/include/etc). The chunker splits the document into
top-level blocks while preserving character offsets.
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
class _TopBlock:
    start: int
    end: int
    key: str
    kind: str
    index: int


_TOP_KEY_RE = re.compile(r"^(?P<key>[A-Za-z0-9_.-]{1,200})\s*:\s*(?:#.*)?$")
_SCRIPT_RE = re.compile(r"(?m)^\s*script\s*:\s*")

_RESERVED_KEYS = {
    "stages",
    "variables",
    "include",
    "default",
    "workflow",
    "image",
    "services",
    "before_script",
    "after_script",
    "cache",
    "pages",
}


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


def _build_top_blocks(text: str) -> list[_TopBlock]:
    lines = _iter_lines(text)
    idxs: list[int] = []
    keys: list[str] = []
    for i, ln in enumerate(lines):
        plain = ln.plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        if plain.startswith(" "):
            continue
        m = _TOP_KEY_RE.match(plain)
        if not m:
            continue
        key = (m.group("key") or "").strip()
        if not key:
            continue
        idxs.append(i)
        keys.append(key)

    if not idxs:
        return []

    blocks: list[_TopBlock] = []
    for j, i in enumerate(idxs):
        start = lines[i].start
        end = lines[idxs[j + 1]].start if j + 1 < len(idxs) else len(text)
        key = keys[j]
        kind = "config" if key.lower() in _RESERVED_KEYS else "job"
        blocks.append(_TopBlock(start=start, end=end, key=key, kind=kind, index=int(j)))

    return blocks


def looks_like_gitlab_ci(text: str) -> bool:
    if not text or len(text) < 50:
        return False
    head = text[:20000].lower()
    if "stages:" not in head and "include:" not in head and "workflow:" not in head:
        return False
    if not _SCRIPT_RE.search(text[:200000]):
        return False
    blocks = _build_top_blocks(text)
    return len(blocks) >= 2


class GitLabCIChunker(BaseChunker):
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

    def _append_split_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        base_meta: dict[str, Any],
        start_offset: int,
        extra_meta: dict[str, Any],
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
        for sd in split_docs:
            sd_meta = dict(sd.metadata or {})
            local_start = sd_meta.pop("start_index", None) or 0
            abs_start = start_offset + int(local_start)
            abs_end = abs_start + len(sd.page_content)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd_meta)
            meta["chunk_strategy"] = "gitlab_ci"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            meta.setdefault("doc_type_kwd", "gitlab-ci")
            meta.update(extra_meta)
            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _build_top_blocks(text)
            if not blocks:
                self._append_split_chunks(
                    out,
                    text=text,
                    base_meta=base_meta,
                    start_offset=0,
                    extra_meta={"gitlab_ci_fallback": True},
                )
                continue

            first = blocks[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    self._append_split_chunks(
                        out,
                        text=pre,
                        base_meta=base_meta,
                        start_offset=0,
                        extra_meta={"gitlab_ci_preamble": True},
                    )

            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                self._append_split_chunks(
                    out,
                    text=blk_text,
                    base_meta=base_meta,
                    start_offset=blk.start,
                    extra_meta={
                        "gitlab_ci_key": blk.key,
                        "gitlab_ci_kind": blk.kind,
                        "gitlab_ci_index": int(blk.index),
                        "gitlab_ci_count": int(len(blocks)),
                    },
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

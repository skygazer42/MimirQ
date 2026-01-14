"""
Ansible playbook aware chunking strategy.

Targets Ansible YAML playbooks (typically a top-level list of plays) and splits
by play blocks (each top-level `- name:` / `- hosts:` entry) while preserving
character offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, List, Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    plain: str


@dataclass(frozen=True)
class _PlayBlock:
    start: int
    end: int
    index: int
    name: Optional[str]
    hosts: Optional[str]


_PLAY_START_RE = re.compile(r"(?m)^(?P<indent>\s*)-\s*(?:(?:name|hosts)\s*:)\s*")
_NAME_RE = re.compile(r"(?m)^\s*name\s*:\s*(?P<val>.+?)\s*$")
_HOSTS_RE = re.compile(r"(?m)^\s*hosts\s*:\s*(?P<val>.+?)\s*$")
_TASKS_RE = re.compile(r"(?m)^\s*tasks\s*:\s*")


def _iter_lines(text: str) -> List[_Line]:
    out: List[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), plain=text))
    return out


def _extract_play_name(block_text: str) -> Optional[str]:
    head = (block_text or "")[:2000]
    m = _NAME_RE.search(head)
    if not m:
        return None
    val = (m.group("val") or "").strip()
    return val[:120] or None


def _extract_play_hosts(block_text: str) -> Optional[str]:
    head = (block_text or "")[:2000]
    m = _HOSTS_RE.search(head)
    if not m:
        return None
    val = (m.group("val") or "").strip()
    return val[:120] or None


def _build_play_blocks(text: str) -> List[_PlayBlock]:
    lines = _iter_lines(text)
    idxs: List[int] = []
    for i, ln in enumerate(lines):
        plain = ln.plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        m = _PLAY_START_RE.match(plain)
        if not m:
            continue
        indent = len(m.group("indent") or "")
        if indent != 0:
            continue
        idxs.append(i)

    if not idxs:
        return []

    blocks: List[_PlayBlock] = []
    for j, i in enumerate(idxs):
        start = lines[i].start
        end = lines[idxs[j + 1]].start if j + 1 < len(idxs) else len(text)
        end = max(start, min(end, len(text)))
        blk_text = (text or "")[start:end]
        blocks.append(
            _PlayBlock(
                start=start,
                end=end,
                index=int(j),
                name=_extract_play_name(blk_text),
                hosts=_extract_play_hosts(blk_text),
            )
        )
    return blocks


def looks_like_ansible_playbook(text: str) -> bool:
    if not text or len(text) < 160:
        return False
    head = (text or "")[:20000].lower()
    if "hosts:" not in head:
        return False
    if not _TASKS_RE.search(text[:200000]):
        return False
    blocks = _build_play_blocks(text)
    return len(blocks) >= 1


class AnsiblePlaybookChunker(BaseChunker):
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

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _build_play_blocks(text)
            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "ansible_playbook"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["ansible_playbook_fallback"] = True
                    meta.setdefault("doc_type_kwd", "ansible")
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
                        meta["chunk_strategy"] = "ansible_playbook"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["ansible_playbook_preamble"] = True
                        meta.setdefault("doc_type_kwd", "ansible")
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
                    meta["chunk_strategy"] = "ansible_playbook"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "ansible")
                    meta["ansible_play_index"] = int(blk.index)
                    meta["ansible_play_count"] = int(len(blocks))
                    if blk.name:
                        meta["ansible_play_name"] = blk.name
                    if blk.hosts:
                        meta["ansible_hosts"] = blk.hosts

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

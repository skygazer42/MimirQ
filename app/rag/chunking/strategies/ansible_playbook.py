"""
Ansible playbook aware chunking strategy.

Targets Ansible YAML playbooks (typically a top-level list of plays) and splits
by play blocks (each top-level `- name:` / `- hosts:` entry) while preserving
character offsets.
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
class _PlayBlock:
    start: int
    end: int
    index: int
    name: str | None
    hosts: str | None


_PLAY_START_RE = re.compile(r"(?m)^(?P<indent>\s*)-\s*(?:name|hosts)\s*:\s*")
_TASKS_RE = re.compile(r"(?m)^\s*tasks\s*:\s*")


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


def _is_tasks_key_line(line: str) -> bool:
    s = (line or "").lstrip()
    if s.startswith("-"):
        s = s[1:].lstrip()
    if not s.lower().startswith("tasks"):
        return False
    rest = s[5:].lstrip()
    return rest.startswith(":")


def _parse_yaml_inline_key_value(line: str, *, key: str) -> str | None:
    """
    Parse a simple inline YAML key/value, supporting both:
      - name: Value
        hosts: all
      name: Value
      hosts: all
    """
    raw = (line or "").rstrip("\r\n")
    if not raw.strip():
        return None

    s = raw.lstrip()
    if s.startswith("-"):
        s = s[1:].lstrip()

    low = s.lower()
    key_low = (key or "").strip().lower()
    if not key_low or not low.startswith(key_low):
        return None

    i = len(key_low)
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i >= n or s[i] != ":":
        return None
    i += 1
    val = s[i:].strip()
    return val or None


def _extract_play_field(block_text: str, *, key: str) -> str | None:
    head = (block_text or "")[:2000]
    for ln in head.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if _is_tasks_key_line(ln):
            break
        val = _parse_yaml_inline_key_value(ln, key=key)
        if not val:
            continue
        return val[:120] or None
    return None


def _extract_play_name(block_text: str) -> str | None:
    return _extract_play_field(block_text, key="name")


def _extract_play_hosts(block_text: str) -> str | None:
    return _extract_play_field(block_text, key="hosts")


def _build_play_blocks(text: str) -> list[_PlayBlock]:
    lines = _iter_lines(text)
    idxs: list[int] = []
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

    blocks: list[_PlayBlock] = []
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
    if not text or len(text) < 60:
        return False
    head = text[:20000].lower()
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

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

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

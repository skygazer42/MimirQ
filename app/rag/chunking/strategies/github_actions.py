"""
GitHub Actions workflow aware chunking strategy.

Targets GitHub Actions workflow YAML (typically .github/workflows/*.yml) with a
top-level `jobs:` section. The chunker splits by job blocks while preserving
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
class _JobBlock:
    start: int
    end: int
    name: str
    index: int


_JOBS_RE = re.compile(r"(?m)^(?P<indent>\s*)jobs\s*:\s*(?:#.*)?$")
_KEY_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9][A-Za-z0-9_.-]{0,200})\s*:\s*(?:#.*)?$")
_RUNS_ON_RE = re.compile(r"(?m)^\s*runs-on\s*:\s*")
_ON_RE = re.compile(r"(?m)^(?P<indent>\s*)on\s*:\s*")


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


def _find_jobs_anchor(text: str) -> tuple[int, int] | None:
    m = _JOBS_RE.search(text or "")
    if not m:
        return None
    return m.start(), len(m.group("indent") or "")


def _extract_workflow_name(text: str) -> str | None:
    head = (text or "")[:8000]
    offset = 0
    for raw_line in head.splitlines(keepends=True):
        _ = offset
        offset += len(raw_line)
        plain = raw_line.rstrip("\r\n")
        if not plain or plain.lstrip().startswith("#"):
            continue
        # Only accept top-level "name:".
        if plain[:1].isspace():
            continue
        if ":" not in plain:
            continue
        key, rest = plain.split(":", 1)
        if key.strip().casefold() != "name":
            continue
        # Strip common inline comment pattern.
        val = rest.strip()
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        val = val.strip().strip("'\"")
        return val[:120] or None
    return None


def _build_job_blocks(text: str) -> list[_JobBlock]:
    anchor = _find_jobs_anchor(text)
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
    jobs_end = len(text)

    for i in range(anchor_idx + 1, len(lines)):
        plain = lines[i].plain
        if not plain.strip() or plain.lstrip().startswith("#"):
            continue
        indent = len(plain) - len(plain.lstrip(" "))
        if indent <= base_indent:
            jobs_end = lines[i].start
            break
        m = _KEY_RE.match(plain)
        if not m:
            continue
        key = (m.group("key") or "").strip()
        if key:
            candidates.append((i, indent, key))

    if not candidates:
        return []

    job_indent = min(ind for _, ind, _ in candidates)
    job_keys: list[tuple[int, str]] = [(i, key) for i, ind, key in candidates if ind == job_indent]
    if not job_keys:
        return []

    blocks: list[_JobBlock] = []
    for idx, (i, key) in enumerate(job_keys):
        start = lines[i].start
        end = lines[job_keys[idx + 1][0]].start if idx + 1 < len(job_keys) else jobs_end
        end = max(start, min(end, len(text)))
        blocks.append(_JobBlock(start=start, end=end, name=key, index=int(idx)))

    return blocks


def looks_like_github_actions_workflow(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    head = text[:20000].lower()
    if "jobs:" not in head:
        return False
    if not (_ON_RE.search(head) or "workflow_dispatch" in head):
        return False
    if not _RUNS_ON_RE.search(head):
        return False
    blocks = _build_job_blocks(text)
    return len(blocks) >= 1


class GitHubActionsChunker(BaseChunker):
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

            wf_name = _extract_workflow_name(text)
            blocks = _build_job_blocks(text)

            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "github_actions"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["github_actions_fallback"] = True
                    if wf_name:
                        meta["github_workflow_name"] = wf_name
                    meta.setdefault("doc_type_kwd", "github-actions")
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
                        meta["chunk_strategy"] = "github_actions"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["github_actions_preamble"] = True
                        if wf_name:
                            meta["github_workflow_name"] = wf_name
                        meta.setdefault("doc_type_kwd", "github-actions")
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
                    meta["chunk_strategy"] = "github_actions"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "github-actions")
                    if wf_name:
                        meta["github_workflow_name"] = wf_name
                    meta["github_job"] = blk.name
                    meta["github_job_index"] = int(blk.index)
                    meta["github_job_count"] = int(len(blocks))

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

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

    candidates, jobs_end = _collect_job_candidates(lines, anchor_idx=anchor_idx, base_indent=base_indent, text_length=len(text))
    if not candidates:
        return []

    job_keys = _job_keys_from_candidates(candidates)
    if not job_keys:
        return []

    blocks: list[_JobBlock] = []
    for idx, (i, key) in enumerate(job_keys):
        start = lines[i].start
        end = lines[job_keys[idx + 1][0]].start if idx + 1 < len(job_keys) else jobs_end
        end = max(start, min(end, len(text)))
        blocks.append(_JobBlock(start=start, end=end, name=key, index=int(idx)))

    return blocks


def _collect_job_candidates(
    lines: list[_Line],
    *,
    anchor_idx: int,
    base_indent: int,
    text_length: int,
) -> tuple[list[tuple[int, int, str]], int]:
    candidates: list[tuple[int, int, str]] = []
    jobs_end = text_length
    for i in range(anchor_idx + 1, len(lines)):
        candidate = _job_candidate_for_line(lines[i], base_indent=base_indent)
        if candidate == "stop":
            jobs_end = lines[i].start
            break
        if candidate is not None:
            candidates.append((i, *candidate))
    return candidates, jobs_end


def _job_candidate_for_line(line: _Line, *, base_indent: int) -> tuple[int, str] | str | None:
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


def _job_keys_from_candidates(candidates: list[tuple[int, int, str]]) -> list[tuple[int, str]]:
    job_indent = min(indent for _, indent, _ in candidates)
    return [(line_index, key) for line_index, indent, key in candidates if indent == job_indent]


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


def _workflow_base_meta(base_meta: dict[str, Any], *, start_char: int, end_char: int, workflow_name: str | None) -> dict[str, Any]:
    meta: dict[str, Any] = dict(base_meta)
    meta["chunk_strategy"] = "github_actions"
    meta["start_char"] = start_char
    meta["end_char"] = end_char
    if workflow_name:
        meta["github_workflow_name"] = workflow_name
    meta.setdefault("doc_type_kwd", "github-actions")
    return meta


def _split_workflow_text_docs(
    splitter: RecursiveCharacterTextSplitter,
    text: str,
    base_meta: dict[str, Any],
    *,
    workflow_name: str | None,
    marker_key: str,
    start_offset: int = 0,
) -> list[Document]:
    split_docs = splitter.create_documents(texts=[text], metadatas=[base_meta])
    chunks: list[Document] = []
    for split_doc in split_docs:
        split_meta = dict(split_doc.metadata or {})
        local_start = int(split_meta.pop("start_index", None) or 0)
        abs_start = start_offset + local_start
        meta = _workflow_base_meta(
            base_meta,
            start_char=abs_start,
            end_char=abs_start + len(split_doc.page_content),
            workflow_name=workflow_name,
        )
        meta.update(split_meta)
        meta[marker_key] = True
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


def _split_job_chunk_docs(
    splitter: RecursiveCharacterTextSplitter,
    text: str,
    base_meta: dict[str, Any],
    *,
    block: _JobBlock,
    workflow_name: str | None,
    job_count: int,
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
        meta = _workflow_base_meta(
            base_meta,
            start_char=abs_start,
            end_char=abs_start + len(split_doc.page_content),
            workflow_name=workflow_name,
        )
        meta.update(split_meta)
        meta["github_job"] = block.name
        meta["github_job_index"] = int(block.index)
        meta["github_job_count"] = int(job_count)
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


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
        workflow_name = _extract_workflow_name(text)
        blocks = _build_job_blocks(text)
        if not blocks:
            return _split_workflow_text_docs(
                self._fallback_splitter,
                text,
                base_meta,
                workflow_name=workflow_name,
                marker_key="github_actions_fallback",
            )

        chunks: list[Document] = []
        first = blocks[0]
        if first.start > 0:
            preamble = text[: first.start]
            if preamble.strip():
                chunks.extend(
                    _split_workflow_text_docs(
                        self._fallback_splitter,
                        preamble,
                        base_meta,
                        workflow_name=workflow_name,
                        marker_key="github_actions_preamble",
                    )
                )

        for block in blocks:
            chunks.extend(
                _split_job_chunk_docs(
                    self._fallback_splitter,
                    text,
                    base_meta,
                    block=block,
                    workflow_name=workflow_name,
                    job_count=len(blocks),
                )
            )
        return chunks

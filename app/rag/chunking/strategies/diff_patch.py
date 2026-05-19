"""
Diff / patch aware chunking strategy.

Targets unified diff text (e.g., `git diff`) and avoids splitting inside hunks.
Splits by file blocks first (`diff --git ...`), then splits large file blocks
at hunk boundaries (`@@ -a,b +c,d @@`) while preserving character offsets.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _FileBlock:
    start: int
    end: int
    index: int
    a_path: str
    b_path: str


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


_HUNK_RE = re.compile(r"(?m)^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@.*$")


def _strip_quotes(s: str) -> str:
    t = (s or "").strip()
    if len(t) >= 2 and ((t[0] == '"' and t[-1] == '"') or (t[0] == "'" and t[-1] == "'")):
        t = t[1:-1].strip()
    return t


def _parse_diff_header_line(line: str) -> tuple[str, str] | None:
    """
    Parse a unified diff header line:
      diff --git a/path b/path
      diff --git "a/path with spaces" "b/path with spaces"

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = (line or "").strip()
    prefix = "diff --git "
    if not s.startswith(prefix):
        return None
    rest = s[len(prefix) :].strip()
    if not rest:
        return None

    try:
        parts = shlex.split(rest)
    except ValueError:
        parts = rest.split()
    if len(parts) < 2:
        return None
    return _strip_quotes(parts[0]), _strip_quotes(parts[1])


def _iter_file_blocks(text: str) -> list[_FileBlock]:
    raw = text or ""
    if not raw:
        return []

    headers: list[tuple[int, str, str]] = []
    offset = 0
    for raw_line in raw.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        parsed = _parse_diff_header_line(raw_line.rstrip("\r\n"))
        if not parsed:
            continue
        a_path, b_path = parsed
        headers.append((line_start, a_path, b_path))

    if not headers:
        return []

    blocks: list[_FileBlock] = []
    for idx, (start, a_path, b_path) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(raw)
        blocks.append(_FileBlock(start=start, end=end, index=idx, a_path=a_path, b_path=b_path))
    return blocks


def _iter_hunks(text: str, *, start: int, end: int) -> list[_Span]:
    window = text[start:end]
    matches = list(_HUNK_RE.finditer(window))
    if not matches:
        return []
    hunks: list[_Span] = []
    for i, m in enumerate(matches):
        hs = start + m.start()
        he = start + (matches[i + 1].start() if i + 1 < len(matches) else len(window))
        hunks.append(_Span(start=hs, end=he))
    return hunks


def looks_like_diff_patch(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    files = _iter_file_blocks(text)
    if not files:
        return False
    # Require at least one hunk or multiple files.
    if len(files) >= 2:
        return True
    hunks = _iter_hunks(text, start=files[0].start, end=files[0].end)
    return len(hunks) >= 1


class DiffPatchChunker(BaseChunker):
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

            files = _iter_file_blocks(text)
            if not files:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "diff_patch"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["diff_fallback"] = True
                    meta.setdefault("doc_type_kwd", "diff")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            for file_block in files:
                file_text = text[file_block.start : file_block.end]
                if not file_text.strip():
                    continue

                hunks = _iter_hunks(text, start=file_block.start, end=file_block.end)
                if not hunks:
                    meta: dict[str, Any] = dict(base_meta)
                    meta["chunk_strategy"] = "diff_patch"
                    meta["start_char"] = file_block.start
                    meta["end_char"] = file_block.end
                    meta.setdefault("doc_type_kwd", "diff")
                    meta["diff_file_index"] = int(file_block.index)
                    meta["diff_path_a"] = file_block.a_path
                    meta["diff_path_b"] = file_block.b_path
                    meta["diff_hunk_count"] = 0
                    out.append(Document(page_content=file_text, metadata=meta))
                    continue

                start_idx = 0
                first = True
                while start_idx < len(hunks):
                    end_idx = start_idx
                    while end_idx < len(hunks):
                        cand_start = file_block.start if first else hunks[start_idx].start
                        cand_end = hunks[end_idx].end
                        cand_len = cand_end - cand_start
                        if end_idx == start_idx or cand_len <= self.chunk_size:
                            end_idx += 1
                            continue
                        break

                    if end_idx == start_idx:
                        end_idx = start_idx + 1

                    chunk_start = file_block.start if first else hunks[start_idx].start
                    chunk_end = hunks[end_idx - 1].end
                    content = text[chunk_start:chunk_end]

                    meta: dict[str, Any] = dict(base_meta)
                    meta["chunk_strategy"] = "diff_patch"
                    meta["start_char"] = chunk_start
                    meta["end_char"] = chunk_end
                    meta.setdefault("doc_type_kwd", "diff")
                    meta["diff_file_index"] = int(file_block.index)
                    meta["diff_path_a"] = file_block.a_path
                    meta["diff_path_b"] = file_block.b_path
                    meta["diff_hunk_count"] = int(end_idx - start_idx)
                    meta["diff_hunk_start_index"] = int(start_idx)
                    meta["diff_hunk_end_index"] = int(end_idx - 1)
                    out.append(Document(page_content=content, metadata=meta))

                    # Hunk-level overlap.
                    next_start = end_idx
                    if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                        desired = end_idx - 1
                        while desired > start_idx:
                            overlap_len = hunks[end_idx - 1].end - hunks[desired - 1].start
                            if overlap_len <= self.chunk_overlap:
                                desired -= 1
                                continue
                            break
                        next_start = desired if desired > start_idx else (end_idx - 1)

                    if next_start <= start_idx:
                        next_start = end_idx
                    start_idx = next_start
                    first = False

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

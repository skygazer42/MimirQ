"""
Git commit-log aware chunking strategy.

Targets `git log` / `git show` like text with repeated commit headers:
- commit <sha>
- Author: ...
- Date: ...

The chunker splits by commit blocks and preserves offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Commit:
    start: int
    end: int
    index: int
    sha: str
    author: str | None
    date: str | None


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    commit: _Commit | None


_COMMIT_RE = re.compile(r"(?m)^\s*commit\s+(?P<sha>[0-9a-f]{7,40})\b")
_AUTHOR_PREFIX = "author:"
_DATE_PREFIX = "date:"
_HEADER_SCAN_CHAR_LIMIT = 2000
_HEADER_SCAN_LINE_LIMIT = 60
_HEADER_VALUE_CHAR_LIMIT = 200


def _extract_commit_header_value(line: str, *, prefix: str) -> str | None:
    stripped = (line or "").strip()
    if not stripped:
        return None
    prefix_norm = prefix.casefold()
    if not stripped.casefold().startswith(prefix_norm):
        return None
    value = stripped[len(prefix) :].strip()
    return value[:_HEADER_VALUE_CHAR_LIMIT] or None


def _iter_commits(text: str) -> list[_Commit]:
    starts = [m.start() for m in _COMMIT_RE.finditer(text or "")]
    if not starts:
        return []
    commits: list[_Commit] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(text)
        chunk = (text or "")[start:end]
        m = _COMMIT_RE.search(chunk)
        if not m:
            continue
        sha = (m.group("sha") or "").strip()
        author = None
        date = None
        for ln in chunk[:_HEADER_SCAN_CHAR_LIMIT].splitlines()[:_HEADER_SCAN_LINE_LIMIT]:
            if author is None:
                author = _extract_commit_header_value(ln, prefix=_AUTHOR_PREFIX)
                if author is not None:
                    if date is not None:
                        break
                    continue
            if date is None:
                date = _extract_commit_header_value(ln, prefix=_DATE_PREFIX)
                if date is not None:
                    if author is not None:
                        break
                    continue
            if author is not None and date is not None:
                break
        commits.append(_Commit(start=start, end=end, index=len(commits), sha=sha, author=author, date=date))
    return commits


def _build_sections(text: str, commits: list[_Commit]) -> list[_Section]:
    if not commits:
        return [_Section(start=0, end=len(text), commit=None)]

    sections: list[_Section] = []
    first = commits[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, commit=None))
    for idx, c in enumerate(commits):
        start = c.start
        end = commits[idx + 1].start if idx + 1 < len(commits) else len(text)
        end = max(end, c.end)
        sections.append(_Section(start=start, end=end, commit=c))
    return sections


def looks_like_git_commit_log(text: str) -> bool:
    if not text or len(text) < 160:
        return False
    head = text[:12000]
    commits = len(_COMMIT_RE.findall(head))
    if commits >= 2:
        return True
    head_lower = head.lower()
    if commits == 1 and (_AUTHOR_PREFIX in head_lower and _DATE_PREFIX in head_lower):
        return True
    return False


class GitCommitLogChunker(BaseChunker):
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

            commits = _iter_commits(text)
            sections = _build_sections(text, commits)

            current: _Commit | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue
                if section.commit is not None:
                    current = section.commit

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "git_commit_log"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "git")
                    if current is not None:
                        meta["git_commit"] = current.sha
                        if current.author:
                            meta["git_author"] = current.author
                        if current.date:
                            meta["git_date"] = current.date

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

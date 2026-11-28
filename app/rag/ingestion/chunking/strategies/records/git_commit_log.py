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

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


@dataclass(frozen=True)
class _Commit:
    start: int
    end: int
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
    stripped = (line).strip()
    if not stripped:
        return None
    prefix_norm = prefix.casefold()
    if not stripped.casefold().startswith(prefix_norm):
        return None
    value = stripped[len(prefix) :].strip()
    return value[:_HEADER_VALUE_CHAR_LIMIT] or None


def _scan_commit_headers(header: str) -> tuple[str | None, str | None]:
    author = None
    date = None
    for line in header.splitlines()[:_HEADER_SCAN_LINE_LIMIT]:
        if author is None:
            author = _extract_commit_header_value(line, prefix=_AUTHOR_PREFIX)
        if date is None:
            date = _extract_commit_header_value(line, prefix=_DATE_PREFIX)
        if author is not None and date is not None:
            break
    return author, date


def _iter_commits(text: str) -> list[_Commit]:
    matches = list(_COMMIT_RE.finditer(text))
    commits: list[_Commit] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sha = m.group("sha")
        author, date = _scan_commit_headers(text[start : min(end, start + _HEADER_SCAN_CHAR_LIMIT)])
        commits.append(_Commit(start=start, end=end, sha=sha, author=author, date=date))
    return commits


def _build_sections(text: str, commits: list[_Commit]) -> list[_Section]:
    if not commits:
        return [_Section(start=0, end=len(text), commit=None)]

    sections: list[_Section] = []
    first = commits[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, commit=None))
    for c in commits:
        sections.append(_Section(start=c.start, end=c.end, commit=c))
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


def _split_commit_section_docs(
    splitter: RecursiveCharacterTextSplitter,
    section_text: str,
    base_meta: dict[str, Any],
    *,
    section: _Section,
) -> list[Document]:
    split_docs = splitter.create_documents(texts=[section_text], metadatas=[base_meta])
    chunks: list[Document] = []
    commit = section.commit
    for split_doc in split_docs:
        split_meta = dict(split_doc.metadata)
        local_start = split_meta.pop("start_index", None)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_meta)
        meta["chunk_strategy"] = "git_commit_log"
        apply_splitter_span(meta, start_index=local_start, content=split_doc.page_content, base_offset=section.start)
        meta.setdefault("doc_type_kwd", "git")
        if commit is not None:
            meta["git_commit"] = commit.sha
            if commit.author:
                meta["git_author"] = commit.author
            if commit.date:
                meta["git_date"] = commit.date
        chunks.append(Document(page_content=split_doc.page_content, metadata=meta))
    return chunks


class GitCommitLogChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
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
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

    def _split_document(self, doc: Document) -> list[Document]:
        text = doc.page_content
        if not text.strip():
            return []

        base_meta = dict(doc.metadata)
        sections = _build_sections(text, _iter_commits(text))
        chunks: list[Document] = []
        for section in sections:
            sec_text = text[section.start : section.end]
            if not sec_text.strip():
                continue
            chunks.extend(
                _split_commit_section_docs(
                    self._fallback_splitter,
                    sec_text,
                    base_meta,
                    section=section,
                )
            )
        return chunks

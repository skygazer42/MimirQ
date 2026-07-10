"""
Changelog / release-notes aware chunking strategy.

Targets changelog-like documents with multiple release headings, e.g.:
- ## [1.2.3] - 2024-01-01
- ## v1.2.3
- ## Unreleased

The chunker splits the document into release sections first, then applies a
fallback RecursiveCharacterTextSplitter inside each release while preserving
character offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading


@dataclass(frozen=True)
class _ReleaseHeading:
    start: int
    end: int
    title: str
    version: str
    date: str | None
    index: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: _ReleaseHeading | None


_VERSION_TOKEN_RE = re.compile(r"(?i)^(?:unreleased|v?\d+\.\d+(?:\.\d+)?(?:[-+][0-9a-z.-]+)?)$")
_RELEASE_REST_PREFIX_RE = re.compile(r"^\s*[-–—:]\s*")
_DATE_RE = re.compile(r"\b(?P<date>\d{4}-\d{2}-\d{2})\b")


def _normalize_heading(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""

    parsed = parse_markdown_hash_heading(t)
    if parsed is not None:
        _level, title = parsed
        t = title

    # Strip leading "Changelog" labels sometimes present.
    s = t.strip()
    low = s.casefold()
    if low.startswith("changelog"):
        rest = s[len("changelog") :].lstrip()
        if rest[:1] in (":", "：", "-"):
            s = rest[1:].strip()
    return s


def _split_release_token(text: str) -> tuple[str, str] | None:
    """
    Best-effort parser for release headings like:
      [1.2.3] - 2024-01-01
      v1.2.3
      Unreleased

    We intentionally avoid regex here to prevent catastrophic-backtracking hotspots.
    """
    s = (text or "").strip()
    if not s:
        return None

    if s.startswith("["):
        close = s.find("]")
        if close > 1:
            token = s[1:close].strip()
            rest = s[close + 1 :].strip()
            return token, rest

    parts = s.split(None, 1)
    token = (parts[0] or "").strip()
    if token.startswith("[") and token.endswith("]") and len(token) > 2:
        token = token[1:-1].strip()
    elif token.startswith("["):
        token = token[1:].strip()
    elif token.endswith("]"):
        token = token[:-1].strip()
    rest = parts[1].strip() if len(parts) > 1 else ""
    return token, rest


def _iter_release_headings(text: str) -> list[_ReleaseHeading]:
    if not text:
        return []

    headings: list[_ReleaseHeading] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 200:
            continue

        norm = _normalize_heading(line)
        split = _split_release_token(norm)
        if not split:
            continue

        token, rest_raw = split
        if not token or not _VERSION_TOKEN_RE.match(token):
            continue
        version = token
        rest = _RELEASE_REST_PREFIX_RE.sub("", rest_raw or "").strip()
        date = None
        dm = _DATE_RE.search(rest)
        if dm:
            date = (dm.group("date") or "").strip() or None

        title = norm
        headings.append(
            _ReleaseHeading(
                start=line_start,
                end=line_start + len(raw_line),
                title=title,
                version=version.lower(),
                date=date,
                index=len(headings),
            )
        )

    # De-dup by start position.
    deduped: list[_ReleaseHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[_ReleaseHeading]) -> list[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: list[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))
    for i, h in enumerate(headings):
        start = h.start
        end = headings[i + 1].start if i + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))
    return sections


def looks_like_changelog(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    headings = _iter_release_headings(text)
    # Require multiple release headings to avoid false positives.
    return len(headings) >= 2


class ChangelogChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", ". ", "!", "?", " ", ""],
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

            headings = _iter_release_headings(text)
            sections = _build_sections(text, headings)

            current_release: _ReleaseHeading | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    current_release = section.heading

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "changelog"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "changelog")
                    if current_release is not None:
                        meta["release_index"] = int(current_release.index)
                        meta["release_version"] = current_release.version
                        meta["release_title"] = current_release.title
                        if current_release.date:
                            meta["release_date"] = current_release.date
                    else:
                        meta["release_index"] = -1

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

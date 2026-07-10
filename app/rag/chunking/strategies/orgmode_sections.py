"""
Org-mode section-aware chunking strategy.

Targets Emacs Org files with headings like:
- * Heading
- ** Subheading

The chunker splits the document into heading blocks first, then applies a
fallback RecursiveCharacterTextSplitter while preserving character offsets.
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
    text: str


@dataclass(frozen=True)
class OrgHeading:
    start: int
    end: int
    level: int
    title: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: OrgHeading | None


_FILE_KWD_RE = re.compile(r"(?mi)^\s*#\+(title|author|date|options|startup):")
_ORG_TAG_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@#%:.-")
_ORG_TODO_KEYWORDS = frozenset({"todo", "done", "next", "wait", "cancelled"})


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, text=raw))
    if not out and text:
        out.append(_Line(start=0, end=len(text), text=text))
    return out


def _clean_title(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""

    # Strip Org tags at end, e.g. "Heading :tag1:tag2:"
    tokens = s.split()
    if tokens:
        last = tokens[-1].strip()
        if (
            len(last) >= 3
            and last.startswith(":")
            and last.endswith(":")
            and all(ch in _ORG_TAG_ALLOWED for ch in last)
        ):
            tokens = tokens[:-1]
            s = " ".join(tokens).strip()

    if not s:
        return ""

    # Strip common TODO keywords.
    first_rest = s.split(None, 1)
    if first_rest:
        head = first_rest[0].strip().casefold()
        if head in _ORG_TODO_KEYWORDS and len(first_rest) > 1:
            s = (first_rest[1] or "").strip()
    return s


def _parse_heading_line(line: str) -> tuple[int, str] | None:
    plain = (line or "").rstrip("\r\n")
    if not plain.strip():
        return None

    i = 0
    n = len(plain)
    while i < n and plain[i].isspace():
        i += 1
    star_start = i
    while i < n and i - star_start < 12 and plain[i] == "*":
        i += 1
    if i == star_start:
        return None
    if i >= n or not plain[i].isspace():
        return None

    level = i - star_start
    while i < n and plain[i].isspace():
        i += 1
    title = _clean_title(plain[i:])
    if not title:
        return None
    return max(1, min(10, int(level))), title


def _iter_headings(text: str) -> list[OrgHeading]:
    headings: list[OrgHeading] = []
    for ln in _iter_lines(text):
        parsed = _parse_heading_line(ln.text)
        if not parsed:
            continue
        level, title = parsed
        headings.append(
            OrgHeading(
                start=ln.start,
                end=ln.end,
                level=max(1, min(10, int(level))),
                title=title,
            )
        )
    deduped: list[OrgHeading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[OrgHeading]) -> list[_Section]:
    if not headings:
        return [_Section(start=0, end=len(text), heading=None)]

    sections: list[_Section] = []
    first = headings[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, heading=None))
    for idx, h in enumerate(headings):
        start = h.start
        end = headings[idx + 1].start if idx + 1 < len(headings) else len(text)
        sections.append(_Section(start=start, end=end, heading=h))
    return sections


def _update_heading_stack(stack: list[str], *, level: int, heading_text: str) -> None:
    level = max(1, int(level))
    while len(stack) >= level:
        stack.pop()
    stack.append(heading_text)


def looks_like_orgmode(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if len(headings) >= 2:
        return True
    if len(headings) == 1 and _FILE_KWD_RE.search(text):
        return True
    return False


class OrgModeSectionsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", "！", "？", " ", ""],
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

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            heading_stack: list[str] = []
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    _update_heading_stack(
                        heading_stack,
                        level=section.heading.level,
                        heading_text=section.heading.title,
                    )

                path = list(heading_stack)
                path_str = " / ".join(path) if path else None

                split_docs = self._fallback_splitter.create_documents(
                    texts=[sec_text],
                    metadatas=[base_meta],
                )
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "orgmode_sections"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "org")

                    if section.heading is not None:
                        meta["org_heading"] = section.heading.title
                        meta["org_level"] = int(section.heading.level)
                    if path:
                        meta["org_path"] = path
                    if path_str:
                        meta["org_path_str"] = path_str

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

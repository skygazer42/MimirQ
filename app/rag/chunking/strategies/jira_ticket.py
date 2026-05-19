"""
Jira/issue-ticket aware chunking strategy.

Targets issue/ticket style text with field blocks such as:
- Summary / Description / Steps to Reproduce / Expected / Actual / Environment
- Acceptance Criteria / Comments

The chunker splits the document into these sections first, then applies a
fallback RecursiveCharacterTextSplitter inside each section while preserving
character offsets.
"""

from __future__ import annotations

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
class _Heading:
    start: int
    end: int
    title: str
    key: str


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    heading: _Heading | None


_ISSUE_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_FIELD_KEY_ALLOWED = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _/-")


def _norm(s: str) -> str:
    # Faster and avoids regex backtracking hotspots.
    return " ".join((s or "").strip().split()).lower()


def _strip_numbered_prefix(s: str) -> str:
    """
    Strip a numbered outline prefix such as:
      1. Title
      1) Title
      1.2.3) Title
    """
    raw = (s or "").lstrip()
    if not raw:
        return ""

    i = 0
    n = len(raw)
    if i >= n or not raw[i].isdigit():
        return raw

    # First segment digits.
    while i < n and raw[i].isdigit():
        i += 1

    segs = 1
    while segs < 4 and i + 1 < n and raw[i] == "." and raw[i + 1].isdigit():
        i += 1
        while i < n and raw[i].isdigit():
            i += 1
        segs += 1

    # Require at least one delimiter character ('.', ')', or whitespace).
    j = i
    while j < n and (raw[j].isspace() or raw[j] in (".", ")")):
        j += 1
    if j == i:
        return raw

    return raw[j:].strip()


def _strip_trailing_colon(s: str) -> str:
    out = (s or "").rstrip()
    while out and out[-1].isspace():
        out = out[:-1]
    if out.endswith((":", "：")):
        out = out[:-1].rstrip()
    return out


def _parse_confluence_heading(s: str) -> str | None:
    """
    Parse 'h1. Title' style headings.
    """
    line = (s or "").strip()
    if len(line) < 4:
        return None
    if line[0].lower() != "h":
        return None
    if line[1] not in "123456":
        return None
    if line[2] != ".":
        return None
    if not line[3].isspace():
        return None
    title = line[3:].strip()
    return title or None


def _parse_md_heading(s: str) -> str | None:
    """
    Parse Markdown ATX headings (1-6 '#') and return the title.
    """
    line = (s or "").strip()
    if not line:
        return None
    i = 0
    n = len(line)
    while i < n and i < 6 and line[i] == "#":
        i += 1
    if i == 0 or i >= n or not line[i].isspace():
        return None
    title = line[i:].strip()
    return title or None


def _parse_field_heading(s: str) -> str | None:
    """
    Parse 'Key: Value' style headings and return the key.
    """
    line = (s or "").strip()
    if not line:
        return None
    pos = line.find(":")
    pos2 = line.find("：")
    if pos == -1:
        pos = pos2
    elif pos2 != -1:
        pos = min(pos, pos2)
    if pos <= 0:
        return None
    key = line[:pos].strip()
    if len(key) < 2 or len(key) > 41:
        return None
    if not key[0].isalpha():
        return None
    if any(ch not in _FIELD_KEY_ALLOWED for ch in key):
        return None
    return key


_SECTION_SYNONYMS: dict[str, list[str]] = {
    "summary": ["summary", "title", "标题", "概要", "问题概述"],
    "description": ["description", "details", "描述", "详情", "问题描述"],
    "steps": ["steps to reproduce", "repro steps", "reproduction steps", "复现步骤", "重现步骤", "复现", "步骤"],
    "expected": ["expected result", "expected", "期望结果", "预期结果"],
    "actual": ["actual result", "actual", "实际结果", "实际表现", "现象", "结果"],
    "environment": ["environment", "env", "环境", "系统环境", "版本信息"],
    "acceptance": ["acceptance criteria", "acceptance", "验收标准", "验收"],
    "comments": ["comments", "comment", "discussion", "讨论", "备注", "评论"],
    "attachments": ["attachments", "attachment", "附件"],
}

_TITLE_TO_KEY: dict[str, str] = {}
for k, vals in _SECTION_SYNONYMS.items():
    for v in vals:
        _TITLE_TO_KEY[_norm(v)] = k


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


def _parse_heading_line(plain: str) -> tuple[str, str] | None:
    s = (plain or "").strip()
    if not s:
        return None
    s = _strip_numbered_prefix(s)

    if (title := _parse_confluence_heading(s)) is not None:
        key = _TITLE_TO_KEY.get(_norm(title))
        if key:
            return title, key
        return None

    if (title := _parse_md_heading(s)) is not None:
        title = _strip_trailing_colon(title)
        key = _TITLE_TO_KEY.get(_norm(title))
        if key:
            return title, key
        return None

    if (title := _parse_field_heading(s)) is not None:
        key = _TITLE_TO_KEY.get(_norm(title))
        if key:
            return title, key
        return None

    # Standalone heading with trailing colon.
    if s.endswith((":", "：")) and len(s) <= 80:
        title = _strip_trailing_colon(s)
        key = _TITLE_TO_KEY.get(_norm(title))
        if key:
            return title, key

    return None


def _iter_headings(text: str) -> list[_Heading]:
    headings: list[_Heading] = []
    for ln in _iter_lines(text):
        parsed = _parse_heading_line(ln.plain)
        if not parsed:
            continue
        title, key = parsed
        headings.append(_Heading(start=ln.start, end=ln.end, title=title, key=key))

    deduped: list[_Heading] = []
    last_start = -1
    for h in headings:
        if h.start == last_start:
            continue
        deduped.append(h)
        last_start = h.start
    return deduped


def _build_sections(text: str, headings: list[_Heading]) -> list[_Section]:
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


def _extract_issue_key(text: str) -> str | None:
    if not text:
        return None
    m = _ISSUE_KEY_RE.search(text[:4000])
    if not m:
        return None
    return (m.group(0) or "").strip() or None


def looks_like_jira_ticket(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    headings = _iter_headings(text)
    if not headings:
        return False
    keys = {h.key for h in headings}
    # Require multiple distinct ticket sections.
    if len(keys) >= 4:
        return True
    lowered = (text or "").lower()
    if len(keys) >= 3 and any(k in lowered for k in ("issue type", "assignee", "reporter", "priority", "component")):
        return True
    return False


class JiraTicketChunker(BaseChunker):
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

            issue_key = _extract_issue_key(text)
            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            current: _Heading | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    current = section.heading

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "jira_ticket"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "ticket")
                    if issue_key:
                        meta["ticket_key"] = issue_key
                    if current is not None:
                        meta["ticket_section"] = current.key
                        meta["ticket_section_title"] = current.title

                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out

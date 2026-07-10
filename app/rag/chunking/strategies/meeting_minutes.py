"""
Meeting minutes / notes aware chunking strategy.

Targets meeting minutes that have common sections like agenda, discussion,
decisions, and action items (often not speaker-turn transcripts).

The chunker splits the document into sections first, then applies a fallback
RecursiveCharacterTextSplitter inside each section while preserving offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading


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


_EN_SECTIONS: dict[str, str] = {
    "agenda": "agenda",
    "attendees": "attendees",
    "participants": "attendees",
    "notes": "notes",
    "minutes": "notes",
    "discussion": "discussion",
    "decisions": "decisions",
    "decision": "decisions",
    "action items": "action_items",
    "action item": "action_items",
    "actions": "action_items",
    "next steps": "next_steps",
    "next step": "next_steps",
    "summary": "summary",
}

_CN_SECTIONS: dict[str, str] = {
    "议程": "agenda",
    "参会人员": "attendees",
    "参会人": "attendees",
    "出席人员": "attendees",
    "会议纪要": "notes",
    "纪要": "notes",
    "讨论": "discussion",
    "结论": "decisions",
    "决议": "decisions",
    "决定": "decisions",
    "行动项": "action_items",
    "待办": "action_items",
    "下一步": "next_steps",
    "总结": "summary",
}

_EN_CANON = {re.sub(r"\s+", " ", k.strip().lower()): v for k, v in _EN_SECTIONS.items()}


def _normalize_title(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    parsed = parse_markdown_hash_heading(t)
    if parsed is not None:
        _level, title = parsed
        t = title

    # Strip bullet markers.
    t = re.sub(r"^\s*(?:[-*+]\s+|\d+\.\s+)", "", t).strip()
    # Strip numbering prefixes like "1." / "1)" / "一、" / "（一）".
    t = re.sub(r"^\s*\d{1,3}[.、)）]\s*", "", t)
    t = re.sub(r"^\s*[一二三四五六七八九十]{1,3}[、.]\s*", "", t)
    t = re.sub(r"^\s*[（(][一二三四五六七八九十]{1,3}[)）]\s*", "", t).strip()
    t = t.strip(":：").strip()
    return t


def _section_key(title: str) -> str | None:
    if not title:
        return None
    if title in _CN_SECTIONS:
        return _CN_SECTIONS[title]
    lower = re.sub(r"\s+", " ", title.strip().lower())
    return _EN_CANON.get(lower)


def _iter_headings(text: str) -> list[_Heading]:
    if not text:
        return []
    headings: list[_Heading] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)

        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 160:
            continue

        title = _normalize_title(line)
        key = _section_key(title)
        if not key:
            continue

        headings.append(_Heading(start=line_start, end=line_start + len(raw_line), title=title, key=key))

    # De-dup by start pos.
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


def looks_like_meeting_minutes(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    headings = _iter_headings(text)
    if len(headings) < 2:
        return False
    keys = {h.key for h in headings}
    # Strong signals: action items or decisions sections.
    return bool(keys & {"action_items", "decisions", "agenda"})


class MeetingMinutesChunker(BaseChunker):
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

            headings = _iter_headings(text)
            sections = _build_sections(text, headings)

            current_heading: _Heading | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue

                if section.heading is not None:
                    current_heading = section.heading

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "meeting_minutes"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "minutes")
                    if current_heading is not None:
                        meta["minutes_section"] = current_heading.key
                        meta["minutes_section_title"] = current_heading.title
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
